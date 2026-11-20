"""Tenant request contracts and isolation, without live Cognee traffic."""
import json

import httpx
import pytest

from app.integrations.cognee import CogneeClient, CogneeError


DATASET = "735ba479-09c3-4d86-885a-c213ab0cd03b"


def client(handler, **kwargs):
    return CogneeClient("test-only", "https://tenant-example.aws.cognee.ai",
                        transport=httpx.MockTransport(handler), **kwargs)


def test_permanent_remember_uses_multipart_without_session_or_promotion():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"pipeline_run_id": "actual-run", "data_id": "actual-data"})

    with client(handler) as api:
        result = api.remember("Sourced product knowledge", "intent-job-catalog",
                              filename="source-hash.txt", metadata={"source_id": "dummyjson:product:1"})
    assert result == {"pipeline_run_id": "actual-run", "data_id": "actual-data"}
    request = seen[0]
    assert request.url.path == "/api/v1/remember"
    assert request.headers["X-Api-Key"] == "test-only"
    body = request.content.decode()
    assert 'name="data"; filename="source-hash.txt"' in body
    assert 'name="datasetName"\r\n\r\nintent-job-catalog' in body
    assert 'name="self_improvement"\r\n\r\nfalse' in body
    assert 'name="run_in_background"\r\n\r\ntrue' in body
    assert 'name="session_id"' not in body
    assert 'dummyjson:product:1' in body


def test_temporary_entry_is_typed_and_session_scoped():
    seen = []
    with client(lambda req: seen.append(req) or httpx.Response(200, json={"entry_id": "real-qa"})) as api:
        api.remember_entry("intent-job-persona-a", "session-a", "Exception for this session only.",
                           metadata={"synthetic_demo": True})
    assert seen[0].url.path == "/api/v1/remember/entry"
    payload = json.loads(seen[0].content)
    assert payload["dataset_name"] == "intent-job-persona-a"
    assert payload["session_id"] == "session-a"
    assert payload["entry"]["type"] == "qa"
    assert payload["entry"]["answer"] == "Exception for this session only."
    assert json.loads(payload["entry"]["context"])["synthetic_demo"] is True
    assert payload["self_improvement"] is False


def test_recall_separates_current_session_and_fresh_graph_and_preserves_ids():
    seen = []
    response = [{"source": "graph", "used_graph_element_ids": {"nodes": ["actual-node"]}}]
    with client(lambda req: seen.append(req) or httpx.Response(200, json=response)) as api:
        api.recall("exception", datasets=["intent-job-persona-a"], session_id="session-a", scope="session")
        result = api.recall("What confirmed requirement applies?", datasets=[DATASET],
                            session_id="fresh-session-b", scope="graph", search_type="GRAPH_COMPLETION")
    current, fresh = [json.loads(req.content) for req in seen]
    assert current["scope"] == "session" and "searchType" not in current
    assert current["datasets"] == ["intent-job-persona-a"]
    assert fresh["scope"] == "graph" and fresh["datasetIds"] == [DATASET]
    assert fresh["sessionId"] == "fresh-session-b"
    assert fresh["includeReferences"] is True and fresh["stream"] is False
    assert result == response


@pytest.mark.parametrize("kwargs", [
    {"datasets": []}, {"datasets": [DATASET, "intent-job-catalog"]},
    {"datasets": ["main_dataset"]},
    {"datasets": [DATASET], "scope": "all"},
    {"datasets": [DATASET], "scope": "session"},
    {"datasets": [DATASET], "scope": "session", "session_id": "a", "search_type": "CHUNKS"},
])
def test_recall_cannot_accidentally_search_all_or_change_scope(kwargs):
    with client(lambda _: pytest.fail("No request should leave the client")) as api:
        with pytest.raises(ValueError):
            api.recall("query", **kwargs)


def test_explicit_authorization_rejects_unrelated_dataset():
    with client(lambda _: pytest.fail("No request should leave the client"),
                allowed_datasets={"intent-job-persona-a"}) as api:
        with pytest.raises(ValueError, match="authorized"):
            api.recall("query", datasets=["unrelated-private-data"])


def test_ambiguous_post_is_never_retried_and_exception_does_not_leak_details():
    calls = []

    def timeout(request):
        calls.append(request)
        raise httpx.ReadTimeout("sensitive raw request description", request=request)

    with client(timeout, read_retries=2) as api:
        with pytest.raises(CogneeError) as error:
            api.remember("Known sample fact", "intent-job-catalog")
    assert len(calls) == 1
    assert error.value.ambiguous
    assert "sensitive" not in str(error.value)


def test_status_and_export_remain_scoped_and_bounded():
    seen = []
    raw = {"nodes": [{"id": "actual-1"}], "links": []}
    with client(lambda req: seen.append(req) or httpx.Response(200, json=raw)) as api:
        api.status(DATASET)
        api.processing_status(DATASET)
        result = api.export_graph(DATASET, max_nodes=100)
        with pytest.raises(ValueError):
            api.export_graph(DATASET, max_nodes=101)
    assert seen[0].url.params["dataset"] == DATASET
    assert seen[1].url.path == f"/api/v1/datasets/{DATASET}/processing-status"
    params = seen[2].url.params
    assert params["dataset_id"] == DATASET and params["max_nodes"] == "100"
    assert params["full"] == params["stream"] == params["include_session_events"] == "false"
    assert result == raw


def test_read_retry_is_bounded_and_response_bytes_are_capped(monkeypatch):
    monkeypatch.setattr("app.integrations.cognee.time.sleep", lambda _: None)
    calls = []

    def unavailable(request):
        calls.append(request)
        return httpx.Response(503, json={"detail": "unavailable"})

    with client(unavailable, read_retries=1) as api:
        with pytest.raises(CogneeError) as error:
            api.status(DATASET)
    assert len(calls) == 2
    assert error.value.status_code == 503 and not error.value.ambiguous
    with client(lambda _: httpx.Response(200, json={"large": "x" * 200}), max_response_bytes=100) as api:
        with pytest.raises(CogneeError, match="byte limit"):
            api.export_graph(DATASET)


@pytest.mark.parametrize("base", ["http://tenant.aws.cognee.ai", "https://cognee.ai.evil.invalid",
                                   "https://key@tenant.aws.cognee.ai", "https://tenant.aws.cognee.ai/path"])
def test_credentials_only_go_to_configured_cognee_https_origin(base):
    with pytest.raises(ValueError):
        CogneeClient("test-only", base)
