"""Acceptance checks isolate Senso verdicts from local money/catalog eligibility."""
from contextlib import contextmanager
from copy import deepcopy

import pytest
import httpx
from fastapi.testclient import TestClient

from app.config import DEMO_USER, Settings
from app.main import create_app
from app.integrations.senso import SensoEvidenceProvider


class ClaimProvider:
    requires_context = True

    def __init__(self, write_depth):
        self.write_depth = write_depth
        self.state = "supported"
        self.version = "evidence-v1"
        self.checks = 0
        self.calls = []
        self.omit_check_id = False
        self.omit_source_version = False
        self.on_verify = None
        self.feature_override = None

    def for_product(self, product):
        assert self.write_depth[0] == 0, "Remote retrieval ran in a write transaction"
        self.calls.append(("retrieve", product["id"]))
        return [{"content_id": "document-" + product["id"], "kb_node_id": "node-" + product["id"],
                 "version_id": None if self.omit_source_version else self.version,
                 "source_id": "document-" + product["id"],
                 "source_version": None if self.omit_source_version else self.version,
                 "excerpt": product["name"] + (" has a sealed bulb that cannot be replaced." if self.state == "conflict"
                                               else ": " + product["description"]),
                 "provider": "senso", "provenance": "live"}]

    def verify_product(self, product, passages):
        assert self.write_depth[0] == 0, "Remote fact-check ran in a write transaction"
        self.calls.append(("verify", product["id"]))
        self.checks += 1
        if self.on_verify is not None:
            self.on_verify(product)
        feature, fact = {"fold-light": ("replaceable_module", "a replaceable light module"),
                         "halo-light": ("serviceable_components", "serviceable components")}.get(
                             product["id"], ("replaceable_bulb", "a replaceable bulb"))
        if self.feature_override:
            feature, fact = self.feature_override
        return {"requirement": "repairability", "feature": feature,
                "claim": product["name"] + " has " + fact + ".", "state": self.state,
                "reason": "Senso required claim is " + self.state + ".",
                "check_id": None if self.omit_check_id else "check-" + str(self.checks),
                "sources": deepcopy(passages), "provider": "senso", "provenance": "live"}


@pytest.fixture
def live_claim_client(tmp_path, monkeypatch):
    with TestClient(create_app(Settings(sqlite_path=tmp_path / "claims.db"))) as client:
        depth = [0]
        original = client.app.state.store.transaction

        @contextmanager
        def guarded_transaction(user_id, write=False):
            with original(user_id, write=write) as unit:
                depth[0] += int(write)
                try:
                    yield unit
                finally:
                    depth[0] -= int(write)

        monkeypatch.setattr(client.app.state.store, "transaction", guarded_transaction)
        provider = ClaimProvider(depth)
        client.app.state.service.evidence = provider
        yield client, provider


def run(client, **fields):
    response = client.post("/api/tasks", json={"goal": "Choose an affordable repairable desk light", **fields})
    assert response.status_code == 201
    task = response.json()
    response = client.post(f"/api/tasks/{task['id']}/run")
    assert response.status_code == 200, response.text
    return response.json()


def arc(task):
    return next(candidate for candidate in task["checkpoint"]["candidates"] if candidate["id"] == "arc-light")


def prepare(client, task):
    return client.post(f"/api/tasks/{task['id']}/proposals", json={"product_id": "arc-light"})


def approve(client, proposal):
    return client.post(f"/api/proposals/{proposal['id']}/decision",
                       json={"decision": "approve", "terms_digest": proposal["terms_digest"]})


def execute(client, proposal):
    return client.post(f"/api/proposals/{proposal['id']}/execute")


def test_supported_claim_complete_approved_cart_and_release(live_claim_client):
    client, provider = live_claim_client
    before = client.get("/api/dashboard").json()["budget"]["available_minor"]
    task = run(client)
    candidate = arc(task)
    assert candidate["repairable"] and candidate["total_minor"] < before
    assert candidate["verification"]["state"] == "supported"
    assert candidate["verification"]["feature"] == "replaceable_bulb"
    assert candidate["proposal_allowed"] is True
    assert candidate["evidence"][0]["excerpt"]
    response = prepare(client, task)
    assert response.status_code == 201, response.text
    proposal = response.json()
    verification = proposal["terms"]["verification"]
    assert verification["check_id"]
    assert verification["product_id"] == "arc-light"
    assert verification["product_version"] == candidate["version"]
    assert verification["evidence_fingerprint"]
    assert verification["sources"][0]["version_id"] == "evidence-v1"
    assert approve(client, proposal).status_code == 200
    action = execute(client, proposal)
    assert action.status_code == 200, action.text
    action = action.json()
    assert client.get("/api/dashboard").json()["budget"]["available_minor"] == before - action["total_minor"]
    assert execute(client, proposal).json()["id"] == action["id"]
    assert client.post(f"/api/actions/{action['id']}/remove").status_code == 200
    assert client.post(f"/api/actions/{action['id']}/remove").status_code == 200
    assert client.get("/api/dashboard").json()["budget"]["available_minor"] == before
    assert any(kind == "verify" for kind, _ in provider.calls)


@pytest.mark.parametrize("state", ["conflict", "unsupported", "not_verifiable", "pending", "error"])
def test_essential_claim_negative_blocks_otherwise_eligible_product(live_claim_client, state):
    client, provider = live_claim_client
    provider.state = state
    task = run(client)
    candidate = arc(task)
    # The negative comes from the external evidence, not local price/stock/repairability.
    assert candidate["repairable"] is True
    assert candidate["stock"] > 0
    assert candidate["total_minor"] == 8246
    assert task["checkpoint"]["budget"]["available_minor"] == 20000
    assert candidate["verification"]["state"] == state
    assert candidate["verification"]["reason"]
    assert candidate["evidence"][0]["version_id"] == "evidence-v1"
    assert candidate["proposal_allowed"] is False
    assert candidate["eligible"] is False
    assert prepare(client, task).status_code == 409
    assert client.get("/api/dashboard").json()["actions"] == []


@pytest.mark.parametrize("missing", ["omit_check_id", "omit_source_version"])
def test_incomplete_supported_response_is_not_verification(live_claim_client, missing):
    client, provider = live_claim_client
    setattr(provider, missing, True)
    task = run(client)
    assert arc(task)["proposal_allowed"] is False
    assert prepare(client, task).status_code == 409


@pytest.mark.parametrize("stage", ["prepare", "approve", "execute", "repeat_approval"])
def test_fresh_conflict_cannot_bypass_any_purchase_stage(live_claim_client, stage):
    client, provider = live_claim_client
    task = run(client)
    proposal = None
    if stage != "prepare":
        response = prepare(client, task)
        assert response.status_code == 201, response.text
        proposal = response.json()
    if stage in {"execute", "repeat_approval"}:
        assert approve(client, proposal).status_code == 200
    provider.state = "conflict"
    response = (prepare(client, task) if stage == "prepare" else execute(client, proposal)
                if stage == "execute" else approve(client, proposal))
    assert response.status_code == 409, response.text
    assert client.get("/api/dashboard").json()["actions"] == []


@pytest.mark.parametrize("stage", ["approve", "execute"])
def test_changed_source_version_requires_new_proposal_even_if_supported(live_claim_client, stage):
    client, provider = live_claim_client
    task = run(client)
    response = prepare(client, task)
    assert response.status_code == 201, response.text
    proposal = response.json()
    if stage == "execute":
        assert approve(client, proposal).status_code == 200
    provider.version = "evidence-v2"
    response = approve(client, proposal) if stage == "approve" else execute(client, proposal)
    assert response.status_code == 409, response.text
    assert client.get("/api/dashboard").json()["actions"] == []


def test_watch_rechecks_required_claim_outside_write_transaction(live_claim_client):
    client, provider = live_claim_client
    task = run(client, urgency="flexible", target_price_minor=7000)
    saved = client.post(f"/api/tasks/{task['id']}/watch", json={})
    assert saved.status_code == 200, saved.text
    provider.state = "conflict"
    scanned = client.post("/api/background/scan")
    assert scanned.status_code == 200, scanned.text
    watched = client.get(f"/api/tasks/{task['id']}").json()["task"]
    assert arc(watched)["verification"]["state"] == "conflict"
    assert arc(watched)["proposal_allowed"] is False
    assert watched["checkpoint"]["recommendation"]["decision"] == "Skip"
    assert prepare(client, watched).status_code == 409


def test_legacy_task_without_verification_does_not_reuse_retrieval_as_proof(live_claim_client):
    client, provider = live_claim_client
    task = run(client)
    with client.app.state.store.transaction(DEMO_USER, write=True) as unit:
        stored = unit.get("tasks", task["id"])
        for candidate in stored["checkpoint"]["candidates"]:
            candidate.pop("verification", None)
        unit.save("tasks", task["id"], stored, stored["version"])
    provider.state = "unsupported"
    assert prepare(client, task).status_code == 409


def test_provider_cannot_mark_essential_requirement_not_required(live_claim_client):
    client, provider = live_claim_client
    provider.state = "not_required"
    task = run(client)
    assert arc(task)["verification"]["state"] == "not_verifiable"
    assert arc(task)["proposal_allowed"] is False
    assert prepare(client, task).status_code == 409


def test_product_change_during_remote_check_invalidates_proposal(live_claim_client):
    client, provider = live_claim_client
    task = run(client)

    def change_source(product):
        if product["id"] == "arc-light":
            provider.on_verify = None
            with client.app.state.store.transaction(DEMO_USER, write=True) as unit:
                current = unit.get("products", "arc-light")
                unit.save("products", current["id"], {**current, "source_version": current["source_version"] + 1},
                          current["version"])

    provider.on_verify = change_source
    response = prepare(client, task)
    assert response.status_code == 409, response.text
    assert client.get(f"/api/tasks/{task['id']}").json()["proposals"] == []


def test_different_repairability_feature_cannot_replace_approved_fact(live_claim_client):
    client, provider = live_claim_client
    task = run(client)
    response = prepare(client, task)
    assert response.status_code == 201, response.text
    proposal = response.json()
    provider.feature_override = ("serviceable_components", "serviceable components")
    # Both are possible repairability features, but they are not the same approved claim.
    response = approve(client, proposal)
    assert response.status_code == 409, response.text
    assert client.get("/api/dashboard").json()["actions"] == []


def test_check_exception_preserves_retrieval_without_false_verification(live_claim_client):
    client, provider = live_claim_client

    def unavailable(product):
        raise RuntimeError("private provider diagnostic must not reach shoppers")

    provider.on_verify = unavailable
    task = run(client)
    candidate = arc(task)
    assert candidate["evidence"]
    assert candidate["verification"]["state"] == "error"
    assert candidate["proposal_allowed"] is False
    assert "private provider diagnostic" not in str(task)
    assert prepare(client, task).status_code == 409


def test_watch_rechecks_error_even_when_local_quote_versions_are_unchanged(live_claim_client):
    client, provider = live_claim_client
    task = run(client, urgency="flexible", target_price_minor=7000)
    assert client.post(f"/api/tasks/{task['id']}/watch", json={}).status_code == 200
    assert client.post("/api/background/scan").json()["watchlist_checked"] == 1
    provider.state = "error"
    response = client.post("/api/background/scan")
    assert response.status_code == 200, response.text
    assert response.json()["watchlist_checked"] == 1
    watched = client.get(f"/api/tasks/{task['id']}").json()["task"]
    assert arc(watched)["verification"]["state"] == "error"
    assert arc(watched)["proposal_allowed"] is False


def test_actual_senso_adapter_service_error_is_explicit_to_shopper(live_claim_client):
    client, _ = live_claim_client
    provider = SensoEvidenceProvider("unit-test-key", transport=httpx.MockTransport(
        lambda request: httpx.Response(503, json={"detail": "unavailable"})))
    client.app.state.service.evidence = provider
    task = run(client)
    candidate = arc(task)
    assert candidate["verification"]["state"] == "error"
    assert "retrieval" in candidate["verification"]["reason"].lower()
    assert candidate["proposal_allowed"] is False
    assert prepare(client, task).status_code == 409
