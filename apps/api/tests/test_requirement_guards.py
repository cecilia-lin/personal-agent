"""Exact shopper features stay essential at every server purchase boundary."""
import pytest

from app.config import DEMO_USER
from app.integrations.senso import repairability_claim
from test_claim_verification import live_claim_client, run, arc, prepare, approve, execute


@pytest.mark.parametrize("selected", [None, "repairability"])
def test_explicit_repairability_is_essential_even_when_global_preference_is_off(live_claim_client, selected):
    client, provider = live_claim_client
    assert client.patch("/api/demo/preferences", json={"repairable": False}).status_code == 200
    provider.state = "error"
    task = run(client, requirement=selected)
    assert task["essential_requirement"] is True
    assert arc(task)["verification"]["required"] is True
    assert arc(task)["proposal_allowed"] is False
    assert prepare(client, task).status_code == 409


def exact_bulb_task(client, **kwargs):
    return run(client, goal="Find a desk light with a replaceable bulb",
               requirement="replaceable_bulb", **kwargs)


def test_supported_different_catalog_feature_cannot_satisfy_requested_bulb(live_claim_client):
    client, _ = live_claim_client
    task = exact_bulb_task(client)
    halo = next(c for c in task["checkpoint"]["candidates"] if c["id"] == "halo-light")
    assert repairability_claim(halo)["feature"] == "serviceable_components"
    assert arc(task)["proposal_allowed"]
    assert not halo["proposal_allowed"]
    assert halo["verification"]["state"] in {"unsupported", "not_verifiable", "conflict"}
    response = client.post(f"/api/tasks/{task['id']}/proposals", json={"product_id": "halo-light"})
    assert response.status_code == 409
    assert client.get("/api/dashboard").json()["actions"] == []


@pytest.mark.parametrize("requirement", ["repairability", "replaceable_bulb"])
def test_provider_cannot_relabel_catalog_fact_before_first_proposal(live_claim_client, requirement):
    client, provider = live_claim_client
    provider.feature_override = ("serviceable_components", "serviceable components")
    task = run(client, requirement=requirement)
    assert repairability_claim(arc(task))["feature"] == "replaceable_bulb"
    assert not arc(task)["proposal_allowed"]
    assert prepare(client, task).status_code == 409


def test_feature_label_alone_cannot_verify_a_different_concrete_claim(live_claim_client, monkeypatch):
    client, provider = live_claim_client
    original = provider.verify_product

    def mismatched_claim(product, passages):
        result = original(product, passages)
        if product["id"] == "arc-light":
            result["claim"] = product["name"] + " has serviceable components."
        return result

    monkeypatch.setattr(provider, "verify_product", mismatched_claim)
    task = exact_bulb_task(client)
    assert not arc(task)["proposal_allowed"]
    assert prepare(client, task).status_code == 409


@pytest.mark.parametrize("stage", ["prepare", "approve", "execute", "repeat_approval"])
def test_wrong_feature_cannot_bypass_fresh_purchase_checks(live_claim_client, stage):
    client, provider = live_claim_client
    task = exact_bulb_task(client)
    proposal = None
    if stage != "prepare":
        response = prepare(client, task)
        assert response.status_code == 201
        proposal = response.json()
    if stage in {"execute", "repeat_approval"}:
        assert approve(client, proposal).status_code == 200
    provider.feature_override = ("serviceable_components", "serviceable components")
    response = prepare(client, task) if stage == "prepare" else execute(client, proposal) if stage == "execute" else approve(client, proposal)
    assert response.status_code == 409
    assert client.get("/api/dashboard").json()["actions"] == []


def test_specific_task_requirement_cannot_be_disabled_by_general_preferences(live_claim_client):
    client, provider = live_claim_client
    assert client.patch("/api/demo/preferences", json={"repairable": False}).status_code == 200
    provider.state = "unsupported"
    task = exact_bulb_task(client)
    assert arc(task)["verification"]["required"] is True
    assert not arc(task)["proposal_allowed"]
    assert prepare(client, task).status_code == 409


def test_watch_revalidates_changed_feature_even_when_source_version_is_stable(live_claim_client):
    client, provider = live_claim_client
    task = exact_bulb_task(client, urgency="flexible")
    assert client.post(f"/api/tasks/{task['id']}/watch", json={"product_id": "arc-light"}).status_code == 200
    assert client.post("/api/background/scan").json()["watchlist_checked"] == 1
    provider.feature_override = ("serviceable_components", "serviceable components")
    scan = client.post("/api/background/scan")
    assert scan.status_code == 200
    assert scan.json()["watchlist_checked"] == 1
    watched = client.get(f"/api/tasks/{task['id']}").json()["task"]
    assert not arc(watched)["eligible"]
    assert watched["checkpoint"]["recommendation"]["decision"] == "Skip"


def test_watch_detects_requirement_changed_during_remote_check(live_claim_client):
    client, provider = live_claim_client
    task = exact_bulb_task(client, urgency="flexible")
    assert client.post(f"/api/tasks/{task['id']}/watch", json={"product_id": "arc-light"}).status_code == 200
    assert client.post("/api/background/scan").json()["watchlist_checked"] == 1

    def change_task_requirement(product):
        if product["id"] != "arc-light":
            return
        provider.on_verify = None
        with client.app.state.store.transaction(DEMO_USER, write=True) as unit:
            stored = unit.get("tasks", task["id"])
            unit.save("tasks", stored["id"], {**stored, "requirement": "serviceable_components"}, stored["version"])

    provider.on_verify = change_task_requirement
    scan = client.post("/api/background/scan")
    assert scan.status_code == 200
    assert scan.json()["watchlist_checked"] == 1
    watched = client.get(f"/api/tasks/{task['id']}").json()["task"]
    assert not arc(watched)["eligible"]
    assert watched["checkpoint"]["recommendation"]["decision"] == "Skip"


def test_new_check_ids_do_not_invalidate_unchanged_feature_and_evidence(live_claim_client):
    client, provider = live_claim_client
    task = exact_bulb_task(client)
    proposal = prepare(client, task).json()
    original_check = proposal["terms"]["verification"]["check_id"]
    assert approve(client, proposal).status_code == 200
    checked_task = client.get(f"/api/tasks/{task['id']}").json()["task"]
    assert arc(checked_task)["verification"]["check_id"] != original_check
    assert execute(client, proposal).status_code == 200
    assert provider.checks >= 3  # Provider guard also asserts calls stay outside write transactions.


@pytest.mark.parametrize("goal,requirement", [
    ("Find a desk light with free returns", "replaceable_bulb"),
    ("Find a desk light with a replaceable light module", "replaceable_bulb"),
    ("Find a desk light", "free_returns"),
])
def test_unsupported_or_conflicting_goal_is_rejected_before_remote_calls(live_claim_client, goal, requirement):
    client, provider = live_claim_client
    response = client.post("/api/tasks", json={"goal": goal, "requirement": requirement})
    assert response.status_code == 422
    assert provider.calls == []
    assert client.get("/api/dashboard").json()["tasks"] == []
