"""Unknown shopper constraints fail before any proposal or ignored requirement."""
import pytest
from test_journey import client, settings


@pytest.mark.parametrize("goal", [
    "Find a repairable desk light with free returns",
    "Find a desk light under $50",
    "Find a desk light delivered tomorrow",
    "Find a desk light without a replaceable bulb",
    "Find a blue desk light",
    "Find a desk light with a replaceable bulb and serviceable components",
])
def test_unsupported_or_multiple_requirements_rejected_before_task(client, goal):
    response = client.post("/api/tasks", json={"goal": goal})
    assert response.status_code == 422
    assert client.get("/api/dashboard").json()["tasks"] == []


def test_explicit_selector_cannot_disagree_with_request(client):
    response = client.post("/api/tasks", json={"goal": "Find a desk light with a replaceable bulb",
                                              "requirement": "serviceable_components"})
    assert response.status_code == 422


def test_specific_requirement_is_retained_on_task_and_watch(client):
    response = client.post("/api/tasks", json={"goal": "Find a desk light with a replaceable bulb",
                                              "requirement": "replaceable_bulb", "urgency": "flexible"})
    assert response.status_code == 201
    task = response.json()
    assert task["requirement"] == "replaceable_bulb"
    run = client.post(f"/api/tasks/{task['id']}/run").json()
    arc = next(c for c in run["checkpoint"]["candidates"] if c["id"] == "arc-light")
    halo = next(c for c in run["checkpoint"]["candidates"] if c["id"] == "halo-light")
    assert arc["verification"]["requirement"] == "replaceable_bulb"
    assert arc["eligible"] is True
    assert halo["proposal_allowed"] is False
    assert halo["verification"]["state"] == "unsupported"
    watch = client.post(f"/api/tasks/{task['id']}/watch", json={"product_id": "arc-light"})
    assert watch.status_code == 200
    assert watch.json()["requirement"] == "replaceable_bulb"
