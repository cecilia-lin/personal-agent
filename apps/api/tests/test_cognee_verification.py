import json

import pytest

from app.preparation.verification import _evidence_text, _support, export_prepared_graphs, verify_prepared


def fixtures():
    products = [{"product_id": "dummyjson:product:1", "return_window_days": 30,
                 "policies": {"return_policy": "30 days return policy", "shipping": "Ships in 3-5 business days",
                              "warranty": "1 year warranty"}, "source_version": "source-hash"}]
    personas = [{"id": "intent-demo:persona:A", "session_id": "old-session", "new_session_id": "new-session",
                 "durable_records": [{"type": "confirmed_preference", "requirement": {"kind": "minimum_return_window_days", "value": 30}}],
                 "session_entries": [{"id": "exception-a"}]}]
    manifest = {"datasets": {"catalog": {"id": "catalog-id", "name": "job-catalog"},
                             personas[0]["id"]: {"id": "persona-id", "name": "job-persona"}}}
    return manifest, products, personas


class ObservedClient:
    def __init__(self, references=True, graph=True):
        self.calls = []
        self.references = references
        self.graph = graph

    def export_graph(self, dataset_id, max_nodes):
        assert dataset_id in {"catalog-id", "persona-id"} and max_nodes == 100
        return {"nodes": [{"id": "node-real", "name": "<script>bad()</script>"}, {"id": "node-related"}],
                "links": [{"source": "node-real", "target": "node-related", "relation": "has_policy"}] if self.graph else []}

    def recall(self, **request):
        self.calls.append(request)
        if request["scope"] == "session":
            if request["session_id"] == "old-session":
                return [{"source": "session", "qa_id": "actual-qa", "answer": "In this session only permits comparison of products with unknown return windows."}]
            return []
        response = {"source": "graph", "text": "dummyjson:product:1 has 30 days return policy. Ships in 3-5 business days. 1 year warranty. Source source-hash. User confirmed a durable return window of at least 30 days."}
        if self.references:
            response["metadata"] = {"used_graph_element_ids": {"nodes": ["node-real"]}}
        return [response]


def test_all_checks_require_actual_graph_references_and_fresh_session_does_not_replay(tmp_path):
    manifest, products, personas = fixtures()
    api = ObservedClient()
    result = verify_prepared(api, manifest, products, personas, tmp_path)
    assert result["state"] == "complete" and result["passed"] == 6
    request = api.calls[3]
    assert request["datasets"] == ["persona-id"]
    assert request["only_context"] is True
    assert "return" not in request["query"].lower() and "30" not in request["query"]
    assert request["session_id"] not in {"old-session", "new-session"}
    assert api.calls[5]["session_id"] == request["session_id"]
    assert result["application_decision_changed"] is False
    assert json.loads((tmp_path / "graphs/catalog.json").read_text())["nodes"][0]["id"] == "node-real"
    html = (tmp_path / "graphs/catalog.html").read_text()
    assert "<script>" not in html and "&lt;script&gt;" in html
    second = verify_prepared(ObservedClient(), manifest, products, personas, tmp_path)
    assert second["fresh_session_id"] != result["fresh_session_id"]


def test_plausible_answer_without_actual_supporting_ids_cannot_pass(tmp_path):
    manifest, products, personas = fixtures()
    result = verify_prepared(ObservedClient(references=False), manifest, products, personas, tmp_path)
    assert result["state"] == "pending"
    assert result["passed"] == 2  # Only genuine session retrieval and isolation.
    assert all(not c["provenance_verified"] for c in result["checks"][:4])


def test_graph_without_relationships_is_reported_incomplete(tmp_path):
    manifest, products, personas = fixtures()
    result = verify_prepared(ObservedClient(graph=False), manifest, products, personas, tmp_path)
    assert result["state"] == "pending"
    graph = result["graph_report"]["graphs"]["catalog"]
    assert graph["node_count"] == 2 and graph["edge_count"] == 0
    assert graph["disconnected_node_count"] == 2


def test_unavailable_provider_is_honest_pending_not_fake_graph(tmp_path):
    class Unavailable:
        def export_graph(self, *args, **kwargs):
            raise RuntimeError("private-provider-detail")

    manifest, _, personas = fixtures()
    result = export_prepared_graphs(Unavailable(), manifest, personas, tmp_path)
    assert result["state"] == "pending"
    assert not (tmp_path / "graphs/catalog.json").exists()
    assert "private-provider-detail" not in json.dumps(result)


def test_live_tenant_evidence_fields_preserve_ids_without_copying_context():
    raw = [{"source": "graph", "metadata": {"evidence": [
        {"kind": "graph_node", "artifact_id": "actual-node", "role": "used_as_context"},
        {"kind": "graph_edge", "artifact_id": "actual-edge", "source_node_id": "actual-node"},
    ]}, "raw": {"value": "Large duplicate full context " * 1000}}]
    result = _support(raw, {"actual-node"})
    assert result["supporting_graph_ids"] == ["actual-node"]
    assert result["returned_reference_ids"] == ["actual-edge", "actual-node"]
    assert len(json.dumps(result)) < 500
    assert not _support([{"source": "graph", "raw": {"value": "actual-node"}}], {"actual-node"})["supporting_graph_ids"]


def test_context_envelope_question_cannot_supply_missing_product_or_preference():
    response = [{"source": "graph", "text": "The question is: dummyjson:product:111 30 days\n"
                 "Node: source\n__node_content_start__\nUnknown policy.\n__node_content_end__"}]
    assert _evidence_text(response) == "unknown policy."
    assert _evidence_text([{"source": "graph", "text": "The question is: 30 days"}]) == ""


@pytest.mark.parametrize("completed", [True, False])
def test_lexical_fallback_requires_exact_graph_chunk_and_completed_document(tmp_path, completed):
    text = "Source ID: dummyjson:product:1. Recorded source policy: 30 days return policy. This is sample research data; currency, shipping cost and merchant terms remain unknown."

    class LexicalClient(ObservedClient):
        def export_graph(self, dataset_id, max_nodes):
            graph = super().export_graph(dataset_id, max_nodes)
            graph["nodes"][0].update(text=text, document_id="accepted-document")
            return graph

        def recall(self, **request):
            if request["query"].startswith("Which selected products"):
                return [{"source": "graph", "text": "Only a partial result.",
                         "metadata": {"evidence": [{"artifact_id": "node-real"}]}}]
            if request.get("search_type") == "CHUNKS_LEXICAL":
                return [{"source": "graph", "kind": "chunk", "text": text, "metadata": {}}]
            return super().recall(**request)

    manifest, products, personas = fixtures()
    manifest["cognee_ledger"] = {"record": {"status": "complete" if completed else "accepted", "data_id": "accepted-document"}}
    result = verify_prepared(LexicalClient(), manifest, products, personas, tmp_path)
    check = result["checks"][0]
    assert (check["state"] == "passed") == completed
    assert bool(check["export_linked_chunks"]) == completed
