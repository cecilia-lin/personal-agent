from test_journey import client, settings

def run(client, **fields):
    task = client.post("/api/tasks", json={"goal":"Consider a repairable desk light", **fields}).json()
    return client.post(f"/api/tasks/{task['id']}/run").json()

def test_buy_wait_skip_and_sample_history(client):
    buy = run(client, urgency="now", target_price_minor=9000)
    assert buy["checkpoint"]["recommendation"]["decision"] == "Buy"
    wait = run(client, urgency="flexible", target_price_minor=7000)
    assert wait["checkpoint"]["recommendation"]["decision"] == "Wait"
    assert wait["checkpoint"]["recommendation"]["prediction"] is None
    assert client.post(f"/api/tasks/{wait['id']}/proposals",json={"product_id":"arc-light"}).status_code == 409
    skip = run(client, max_price_minor=100)
    assert skip["checkpoint"]["recommendation"]["decision"] == "Skip"
    history = client.get("/api/products/arc-light/history").json()
    assert len(history["observations"]) == 4
    assert all(p["provenance"]=="fixture" and p["observed_at"] for p in history["observations"])
    assert client.post(f"/api/tasks/{buy['id']}/proposals", json={"product_id":"fold-light"}).status_code == 409

def test_watchlist_persists_and_rechecks_without_spending(client):
    task = run(client, urgency="soon", target_price_minor=7000)
    first = client.post(f"/api/tasks/{task['id']}/watch",json={}).json()
    assert client.post(f"/api/tasks/{task['id']}/watch",json={}).json()["id"] == first["id"]
    assert len(client.get("/api/watchlist").json()["items"]) == 1
    assert client.post("/api/background/scan").json()["watchlist_checked"] == 1
    assert client.post("/api/background/scan").json()["watchlist_checked"] == 0
    client.patch("/api/demo/products/arc-light",json={"price_minor":7000,"stock":8})
    scanned = client.post("/api/background/scan").json()
    assert scanned["watchlist_checked"] == 1
    watch = client.get("/api/watchlist").json()["items"][0]
    assert watch["recommendation"]["decision"] == "Buy"
    assert watch["last_checked_at"]
    assert not client.get("/api/dashboard").json()["actions"]
    assert client.get(f"/api/tasks/{task['id']}").json()["task"]["checkpoint"]["recommendation"]["decision"] == "Buy"
    next_count = len(client.get("/api/dashboard").json()["next_actions"])
    client.post("/api/background/scan")
    assert len(client.get("/api/dashboard").json()["next_actions"]) == next_count
    assert client.post(f"/api/watchlist/{first['id']}/archive").json()["status"]=="archived"


def test_watch_survives_restart_and_guild_redelivery(client, settings, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import create_app
    task = run(client, urgency="flexible", target_price_minor=7000)
    watch = client.post(f"/api/tasks/{task['id']}/watch", json={}).json()
    monkeypatch.setenv("BACKGROUND_TOOL_TOKEN", "local-test-token")
    url = "/api/guild/scan?guild_run_id=platform-run-123"
    assert client.post(url).status_code == 401
    headers = {"Authorization": "Bearer local-test-token"}
    first = client.post(url, headers=headers).json()
    second = client.post(url, headers=headers).json()
    assert first["run_id"] == second["run_id"]
    assert second["duplicate"] is True
    assert first["guild_execution_verified"] is False
    with client.app.state.store.transaction("demo-user") as unit:
        stored = unit.get("runs", first["run_id"])
        assert stored["guild_run_id"] == "platform-run-123"
        assert stored["status"] == "completed"
    with TestClient(create_app(settings)) as restarted:
        item = next(w for w in restarted.get("/api/watchlist").json()["items"] if w["id"]==watch["id"])
        assert item["recommendation"]["decision"] == "Wait"
        assert item["last_checked_at"]
        assert restarted.get(f"/api/tasks/{task['id']}").status_code == 200
