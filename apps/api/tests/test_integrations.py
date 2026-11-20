from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import DEMO_USER, Settings
from app.integrations import amplitude_client, statsig_client
from app.integrations.senso import SensoEvidenceProvider
from app.integrations.sie import SIERanker
from app.main import create_app
from app.repositories.store import UnitOfWork


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(Settings(sqlite_path=tmp_path / "integrations.db"))) as api:
        yield api


def test_analytics_runs_after_commit_and_not_on_repeated_run(client, monkeypatch):
    task = client.post("/api/tasks", json={"goal": "Find a repairable desk light"}).json()
    events = []

    def capture(event):
        with client.app.state.store.transaction(DEMO_USER) as unit:
            assert unit.get("tasks", task["id"])["status"] != "queued"
        events.append((event.event_type, event.user_id, event.event_properties))

    monkeypatch.setattr(amplitude_client, "client", SimpleNamespace(track=capture, shutdown=lambda: None))
    statsig_events = []
    monkeypatch.setattr(statsig_client, "client", SimpleNamespace(
        log_event=lambda **event: statsig_events.append(event),
        shutdown=lambda: SimpleNamespace(wait=lambda: None),
    ))
    monkeypatch.setattr(statsig_client, "initialization_verified", True)
    first = client.post(f"/api/tasks/{task['id']}/run")
    assert first.status_code == 200
    assert client.post(f"/api/tasks/{task['id']}/run").status_code == 200
    assert [e[0] for e in events].count("task_started") == 1
    assert all(e[1] == DEMO_USER for e in events)
    assert all(e[2]["task_id"] == task["id"] for e in events)
    assert all("goal" not in e[2] and "details" not in e[2] and "budget" not in e[2] for e in events)
    assert len(statsig_events) == 1
    assert statsig_events[0]["event_name"] == "task_started"
    assert "metadata" not in statsig_events[0]


def test_rolled_back_task_does_not_emit(client, monkeypatch):
    task = client.post("/api/tasks", json={"goal": "Find a repairable desk light"}).json()
    original_save = UnitOfWork.save
    emitted = []

    def fail_task_commit(unit, table, *args, **kwargs):
        if table == "tasks":
            raise RuntimeError("database write failed")
        return original_save(unit, table, *args, **kwargs)

    monkeypatch.setattr(UnitOfWork, "save", fail_task_commit)
    monkeypatch.setattr(amplitude_client, "track_task_started", emitted.append)
    monkeypatch.setattr(statsig_client, "track_task_started", emitted.append)
    with pytest.raises(RuntimeError, match="database write failed"):
        client.post(f"/api/tasks/{task['id']}/run")
    assert emitted == []


def test_analytics_failure_does_not_fail_a_committed_task(client, monkeypatch):
    def fail(event):
        raise RuntimeError("network unavailable")

    monkeypatch.setattr(amplitude_client, "client", SimpleNamespace(track=fail, shutdown=lambda: None))
    task = client.post("/api/tasks", json={"goal": "Find a repairable desk light"}).json()
    assert client.post(f"/api/tasks/{task['id']}/run").status_code == 200


def test_senso_retains_citations_and_uses_runtime_api(senso_runtime_ledger):
    def respond(request):
        assert request.headers["X-API-Key"] == "unit-test-key"
        if request.url.path == "/api/v1/org/kb/nodes/node-1/content":
            return httpx.Response(200, json={"id": "content-1", "text": "Arc Light is repairable.",
                                            "version_num": 3, "processing_status": "complete"})
        assert request.url.path == "/api/v1/org/search/context"
        import json
        payload = json.loads(request.content)
        assert payload["content_ids"] == ["content-1"] and payload["require_scoped_ids"] is True
        return httpx.Response(200, json={"search_type": "hybrid", "results": [{
            "content_id": "content-1", "kb_node_id": "node-1", "version_id": "version-3",
            "chunk_text": "Arc Light is repairable.", "score": 0.9, "rank": 1,
            "retrieval": {"lexical": {"rank": 1}},
        }]})

    provider = SensoEvidenceProvider("unit-test-key", transport=httpx.MockTransport(respond), ledger=senso_runtime_ledger)
    try:
        evidence = provider.for_product({"id": "arc-light", "name": "Arc Light"})
        assert evidence[0]["kb_node_id"] == "node-1"
        assert evidence[0]["version_id"] == "version-3"
        assert evidence[0]["source_id"] == "content-1"
        assert evidence[0]["provenance"] == "live"
        assert evidence[0]["retrieval"] == {"lexical": {"rank": 1}}
    finally:
        provider.close()


def test_sie_scores_only_eligible_catalog_entries():
    def score(model, query, items, **kwargs):
        assert [item["id"] for item in items] == ["allowed"]
        assert "budget" not in query["text"]
        return {"scores": [{"item_id": "allowed", "score": 0.8}]}

    ranker = SIERanker(client=SimpleNamespace(score=score))
    candidates = [
        {"id": "allowed", "name": "Desk light", "description": "Repairable", "eligible": True},
        {"id": "too-expensive", "name": "Studio light", "description": "Repairable", "eligible": False},
    ]
    result = ranker.score(candidates, "desk-light", True)
    assert result["provenance"] == "live"
    assert candidates[0]["relevance_score"] == 0.8
    assert "relevance_score" not in candidates[1]
    assert candidates[1]["eligible"] is False


def test_invalid_sie_scores_are_an_explicit_local_fallback():
    ranker = SIERanker(client=SimpleNamespace(score=lambda *a, **kw: {"scores": []}))
    candidates = [{"id": "light", "name": "Light", "description": "Repairable", "eligible": True}]
    result = ranker.score(candidates, "desk-light", True)
    assert result["provider"] == "deterministic-demo"
    assert "fallback_reason" in result
    assert "relevance_score" not in candidates[0]
    assert ranker.status()["status"] == "error"


@pytest.mark.parametrize("status,payload", [
    (401, {"detail": "bad credentials"}),
    (200, {"results": []}),
    (200, {"results": [{"content_id": "unrelated", "chunk_text": "Unrelated product"}]}),
])
def test_missing_senso_context_blocks_recommendations(client, status, payload, senso_runtime_ledger):
    def respond(request):
        if request.method == "GET":
            return httpx.Response(200, json={"id": "content-1", "text": "Arc Light is repairable.",
                                            "version_num": 3, "processing_status": "complete"})
        return httpx.Response(status, json=payload)
    provider = SensoEvidenceProvider("unit-test-key", transport=httpx.MockTransport(respond), ledger=senso_runtime_ledger)
    client.app.state.service.evidence = provider
    task = client.post("/api/tasks", json={"goal": "Find a repairable desk light"}).json()
    result = client.post(f"/api/tasks/{task['id']}/run").json()
    assert result["status"] == "failed"
    assert all(not c["eligible"] and c["evidence"] == [] for c in result["checkpoint"]["candidates"])
    assert client.post(f"/api/tasks/{task['id']}/proposals", json={"product_id": "arc-light"}).status_code == 409


def test_persisted_gate_controls_real_ranking(client, monkeypatch):
    calls = []
    monkeypatch.setattr(client.app.state.service.ranker, "score",
        lambda *args: calls.append(args) or {"provider":"stub"})
    monkeypatch.setattr(statsig_client, "choose_reranker",
        lambda user: {"key":"enable_reranker", "enabled":False, "source":"test"})
    first = client.post("/api/tasks", json={"goal":"Repairable desk light"}).json()
    client.post(f"/api/tasks/{first['id']}/run")
    assert calls == []
    monkeypatch.setattr(statsig_client, "choose_reranker",
        lambda user: {"key":"enable_reranker", "enabled":True, "source":"test"})
    client.post(f"/api/tasks/{first['id']}/run")
    assert calls == []
    second = client.post("/api/tasks", json={"goal":"Repairable desk light"}).json()
    result = client.post(f"/api/tasks/{second['id']}/run").json()
    assert len(calls)==1
    assert result["checkpoint"]["recommendation"]["decision"]=="Buy"
    assert result["routing"]["enabled"] is True


def test_amplitude_ai_exports_only_safe_correlated_metadata(monkeypatch):
    product_events, tool_events = [], []
    monkeypatch.setattr(amplitude_client, "client", SimpleNamespace(track=product_events.append))
    monkeypatch.setattr(amplitude_client, "ai_client", SimpleNamespace(track_tool_call=lambda **kw: tool_events.append(kw)))
    metric = {"id":"metric-safe", "kind":"action_executed", "timestamp":"2026-11-20T12:00:00+00:00",
              "session_id":"session-safe", "task_id":"task-safe", "run_id":"run-safe",
              "latency_ms":12.5, "provenance":"simulated", "routing":{"enabled":False},
              "details":{"raw_email":"PRIVATE CONTENT", "account":"PRIVATE ACCOUNT"}}
    amplitude_client.track_metadata("demo-user", metric)
    assert product_events[0].insert_id == metric["id"]
    assert tool_events[0]["session_id"] == metric["session_id"]
    assert tool_events[0]["latency_ms"] == 12.5
    assert "input" not in tool_events[0] and "output" not in tool_events[0]
    assert "PRIVATE" not in str(product_events[0].event_properties) + str(tool_events[0])


def test_statsig_failed_or_incomplete_init_is_not_verified(monkeypatch):
    monkeypatch.setenv("INTEGRATIONS_ENABLED", "true")
    monkeypatch.setenv("STATSIG_SERVER_SECRET_KEY", "test-secret")
    monkeypatch.setattr(statsig_client, "client", None)
    monkeypatch.setattr(statsig_client, "Statsig", lambda *a: SimpleNamespace(
        initialize=lambda: SimpleNamespace(wait=lambda:None),
        get_initialize_details=lambda: SimpleNamespace(init_success=True, is_config_spec_ready=False, failure_details=None)))
    statsig_client.initialize()
    assert statsig_client.initialization_verified is False
    assert statsig_client.choose_reranker("demo-user")["enabled"] is False
    monkeypatch.setattr(statsig_client, "last_error", None)
