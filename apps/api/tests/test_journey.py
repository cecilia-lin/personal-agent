from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
import pytest
from app.config import Settings, DEMO_USER
from app.main import create_app

@pytest.fixture
def settings(tmp_path):
    return Settings(sqlite_path=tmp_path / "state.db")

@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
        yield c

def proposal(client):
    created = client.post("/api/tasks", json={"goal": "Find a repairable desk light"})
    assert created.status_code == 201
    task = created.json()
    assert client.post(f"/api/tasks/{task['id']}/run").json()["status"] == "awaiting_selection"
    response = client.post(f"/api/tasks/{task['id']}/proposals", json={"product_id": "arc-light"})
    assert response.status_code == 201
    return task, response.json()

def approve(client, p):
    return client.post(f"/api/proposals/{p['id']}/decision", json={"decision": "approve", "terms_digest": p["terms_digest"]})

def execute(client, p):
    return client.post(f"/api/proposals/{p['id']}/execute")

def test_journey_idempotency_and_restart(settings):
    app = create_app(settings)
    with TestClient(app) as c:
        assert c.get("/api/dashboard").json()["budget"]["available_minor"] == 20000
        task, p = proposal(c)
        assert p["terms"]["total_minor"] == 8246
        assert approve(c, p).status_code == 200
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: execute(c, p), range(4)))
        assert all(r.status_code == 200 for r in results)
        assert len({r.json()["id"] for r in results}) == 1
        action = results[0].json()
        assert approve(c, p).status_code == 200
        assert len(c.get("/api/dashboard").json()["actions"]) == 1
        assert c.get("/api/dashboard").json()["budget"]["available_minor"] == 11754
    with TestClient(create_app(settings)) as restarted:
        detail = restarted.get(f"/api/tasks/{task['id']}").json()
        assert detail["actions"][0]["id"] == action["id"]
        assert detail["task"]["status"] == "completed"
        assert sum(e["kind"] == "task_completed" for e in detail["audit"]) == 1
        assert detail["actions"][0]["posted_expense"] is False
        assert execute(restarted, p).json()["id"] == action["id"]

def test_bill_changes_available_allowance(client):
    before = client.get("/api/dashboard").json()["budget"]["available_minor"]
    assert client.patch("/api/demo/bills/electricity", json={"amount_minor": 15200}).status_code == 200
    after = client.get("/api/dashboard").json()["budget"]["available_minor"]
    assert before - after == 4000

@pytest.mark.parametrize("mutation", ["price", "budget", "bill", "preference", "stock", "expiry"])
def test_stale_approved_terms_never_execute(client, mutation):
    task, p = proposal(client)
    assert approve(client, p).status_code == 200
    if mutation in {"price", "stock"}:
        client.patch("/api/demo/products/arc-light", json={"price_minor": 9900 if mutation == "price" else 8900, "stock": 0 if mutation == "stock" else 8})
    elif mutation == "budget":
        client.patch("/api/demo/budget", json={"spendable_minor": 90000, "protected_minor": 90000})
    elif mutation == "bill":
        client.patch("/api/demo/bills/electricity", json={"amount_minor": 12000})
    elif mutation == "preference":
        client.patch("/api/demo/preferences", json={"repairable": False})
    else:
        with client.app.state.store.transaction(DEMO_USER, write=True) as u:
            stored = u.get("proposals", p["id"])
            stored["terms"]["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
            u.save("proposals", p["id"], stored, stored["version"])
    blocked = execute(client, p)
    assert blocked.status_code == 409
    detail = client.get(f"/api/tasks/{task['id']}").json()
    assert not detail["actions"]
    assert detail["proposals"][0]["status"] == "stale"
    assert any(e["kind"] == "execution_blocked" for e in detail["audit"])
    assert not any(e["kind"] == "task_completed" for e in detail["audit"])

def test_exact_approval_ownership_and_rejection(client):
    task, p = proposal(client)
    assert execute(client, p).status_code == 409
    assert client.post(f"/api/proposals/{p['id']}/decision", json={"approved": True}).status_code == 422
    assert client.post(f"/api/proposals/{p['id']}/decision", json={"decision": "approve", "terms_digest": "0" * 64}).status_code == 409
    assert client.get(f"/api/tasks/{task['id']}", headers={"X-Demo-User": "someone-else"}).status_code == 403
    rejected = client.post(f"/api/proposals/{p['id']}/decision", json={"decision": "reject", "terms_digest": p["terms_digest"]})
    assert rejected.status_code == 200
    assert execute(client, p).status_code == 409
    assert not any(e["kind"] == "task_completed" for e in client.get(f"/api/tasks/{task['id']}").json()["audit"])
    with client.app.state.store.transaction("another-owner", write=True) as u:
        u.save("accounts", "other-cash", {"source_id": "private"})
    client.post("/api/demo/reset")
    with client.app.state.store.transaction("another-owner") as u:
        assert u.get("accounts", "other-cash")["source_id"] == "private"

def test_unknown_fees_failed_task_and_no_fake_completion(client):
    with client.app.state.store.transaction(DEMO_USER, write=True) as u:
        for product in u.all("products"):
            u.save("products", product["id"], {**product, "tax_minor": None}, product["version"])
    task = client.post("/api/tasks", json={"goal": "Find a desk light"}).json()
    assert client.post(f"/api/tasks/{task['id']}/run").json()["status"] == "failed"
    audit = client.get(f"/api/tasks/{task['id']}").json()["audit"]
    assert any(e["kind"] == "task_failed" for e in audit)
    assert not any(e["kind"] == "task_completed" for e in audit)

def test_competing_proposals_do_not_overreserve(client):
    _, first = proposal(client)
    _, second = proposal(client)
    assert approve(client, first).status_code == 200
    assert approve(client, second).status_code == 200
    assert execute(client, first).status_code == 200
    assert execute(client, second).status_code == 409
    assert len(client.get("/api/dashboard").json()["actions"]) == 1

def test_scan_is_bounded_and_reuses_handler(client):
    queued = client.post("/api/tasks", json={"goal": "Find a desk light"}).json()
    scan = client.post("/api/background/scan").json()
    assert scan["processed"] == 2
    assert scan["guild_execution_verified"] is False
    assert client.get(f"/api/tasks/{queued['id']}").json()["task"]["status"] == "awaiting_selection"
    assert client.post("/api/background/scan").json()["processed"] == 0
    assert client.post("/api/background/scan?limit=100").status_code == 422

def test_modes_and_provider_status(settings, client, monkeypatch):
    assert client.get("/api/health").json()["ready"] is True
    statuses = {x["name"]: x for x in client.get("/api/integrations").json()["integrations"]}
    assert statuses["Superlinked SIE"]["verified"] is False
    monkeypatch.setenv("SIE_API_KEY", "test-not-a-real-key")
    # A changed env variable alone does not initialize the running service's client.
    assert next(i for i in client.get("/api/integrations").json()["integrations"] if i["name"] == "Superlinked SIE")["status"] == "not_configured"
    with TestClient(create_app(Settings(mode="live", sqlite_path=settings.sqlite_path))) as live:
        assert live.get("/api/health").status_code == 503
        assert live.post("/api/demo/reset").status_code == 503
        assert live.post("/api/tasks", json={"goal": "Find a light"}).status_code == 503
    monkeypatch.setenv("GUILD_BACKEND_TOKEN", "local-test-token")
    assert client.post("/api/guild/scan?guild_run_id=test-run-1").status_code == 401
    assert client.post("/api/guild/scan?guild_run_id=test-run-1", headers={"Authorization": "Bearer local-test-token"}).status_code == 200
