"""Live research recall cannot become a household preference or purchase bypass."""
import copy
import hashlib
import json
import sqlite3

import httpx
import pytest

from app.integrations.prepared_memory import PreparedMemoryError, PreparedPreferenceMemory
from app.preparation.job import content_hash, save_json
from app.preparation.senso_publish import SensoPublisher
from app.services.research_memory import get_research_memory


PERSONA = "test-owner:persona:A"
DATASET = "11111111-1111-4111-8111-111111111111"
CURRENT_TEXT = "Confirmed synthetic durable requirement: an explicitly stated return window of at least 30 days."


@pytest.fixture
def prepared(tmp_path):
    products, documents, ledger = [], [], {}
    for number, days in ((1, 30), (2, 7)):
        product_id = f"dummyjson:product:{number}"
        source_version = str(number) * 64
        text = f"Sample product {number}. Return policy: {days} days return policy"
        digest = hashlib.sha256(text.encode()).hexdigest()
        products.append({"product_id": product_id, "source_version": source_version,
                         "title": f"Sample product {number}", "research_only": True,
                         "executable_quote": False, "application_product_id": None, "return_window_days": days,
                         "policies": {"return_policy": f"{days} days return policy", "shipping": None, "warranty": None}})
        documents.append({"source_id": product_id, "source_version": source_version,
                          "content_hash": digest, "schema_version": "intent-cognee-v1", "title": product_id, "text": text})
        ledger[str(number)] = {"source_id": product_id, "source_version": source_version,
                              "content_hash": digest, "schema_version": "intent-cognee-v1", "namespace": "test-job",
                              "content_id": f"content-{number}", "kb_node_id": f"node-{number}",
                              "version_id": f"version-{number}", "status": "ready"}
    current = {"id": PERSONA + ":preference:current", "type": "confirmed_preference", "status": "confirmed",
               "synthetic_demo": True, "owner": PERSONA, "text": CURRENT_TEXT,
               "requirement": {"kind": "minimum_return_window_days", "value": 30}}
    personas = [{"id": PERSONA, "owner": PERSONA, "synthetic_demo": True, "durable_records": [current]}]
    artifacts = {"normalized.json": {"products": products}, "documents.json": documents,
                 "research-findings.json": [], "personas.json": personas}
    manifest = {"job_id": "test-job", "smoke_verified": True, "config": {"synthetic_owner": "test-owner"},
                "stages": {"verify": {"state": "complete", "dry_run": False, "result": {"state": "complete"}}},
                "validated_artifacts": {name: content_hash(value) for name, value in artifacts.items()},
                "datasets": {PERSONA: {"id": DATASET, "name": "test-job_persona_a", "status": "complete"}},
                "cognee_ledger": {"persona": {"source_id": PERSONA, "dataset_id": DATASET,
                                               "data_id": "persona-data", "status": "complete"}},
                "senso_ledger": ledger}
    for name, value in artifacts.items():
        save_json(tmp_path / name, value)
    save_json(tmp_path / "manifest.json", manifest)
    return tmp_path


class MemoryService:
    def __init__(self):
        self.calls = []
        self.graph = {"nodes": [{"id": "requirement-node", "description": CURRENT_TEXT},
                                {"id": "persona-node", "name": PERSONA}],
                      "links": [{"id": "confirmed-edge", "source": "persona-node", "target": "requirement-node"}]}
        self.response = [{"source": "graph", "dataset_id": DATASET, "dataset_name": "test-job_persona_a",
                          "text": CURRENT_TEXT, "metadata": {"evidence": [
                              {"kind": "graph_node", "artifact_id": "requirement-node", "dataset_id": DATASET}]}}]

    def export_graph(self, dataset_id, **kwargs):
        assert dataset_id == DATASET and kwargs["max_nodes"] == 100
        return self.graph

    def recall(self, query, **kwargs):
        self.calls.append({"query": query, **kwargs})
        return self.response


def senso_provider(unavailable=False):
    def handler(request):
        if unavailable:
            return httpx.Response(503, json={"detail": "secret remote diagnostic"})
        if request.method == "GET":
            number = request.url.path[-1]
            return httpx.Response(200, json={"content_id": "content-" + number,
                                            "content": {"processing_status": "complete"}})
        body = json.loads(request.content)
        assert body["require_scoped_ids"] is True and len(body["content_ids"]) == 1
        number = body["content_ids"][0][-1]
        days = 30 if number == "1" else 7
        return httpx.Response(200, json={"results": [{"content_id": "content-" + number,
            "kb_node_id": "node-" + number, "version_id": "version-" + number,
            "content_chunk_id": "chunk-" + number, "chunk_text": f"{days} days return policy"}]})
    return SensoPublisher("test-key", "test-job", transport=httpx.MockTransport(handler), sleep=lambda _: None)


@pytest.mark.parametrize("change", ["unverified", "dry-run", "pending", "unfinished-ingestion"])
def test_bridge_is_unavailable_until_live_preparation_is_verified(prepared, change):
    manifest = json.loads((prepared / "manifest.json").read_text())
    if change == "unverified":
        manifest["smoke_verified"] = False
    elif change == "dry-run":
        manifest["stages"]["verify"]["dry_run"] = True
    elif change == "pending":
        manifest["stages"]["verify"]["state"] = "pending"
    else:
        manifest["cognee_ledger"]["persona"]["status"] = "accepted"
    save_json(prepared / "manifest.json", manifest)
    result = get_research_memory(prepared)
    assert result["state"] == "pending" and not result["proposal_allowed"] and not result["candidates"]


def test_changed_prepared_source_is_blocked_before_recall(prepared):
    save_json(prepared / "personas.json", [{"owner": "real-user"}])
    result = get_research_memory(prepared)
    assert result["state"] == "blocked" and result["requirement"] is None


def test_active_household_user_and_preference_writes_are_rejected(prepared):
    client = MemoryService()
    memory = PreparedPreferenceMemory(prepared, client=client)
    with pytest.raises(PreparedMemoryError):
        memory.recall("demo-user", "requirements")
    with pytest.raises(PreparedMemoryError):
        memory.remember(PERSONA, {"kind": "budget"})
    assert not client.calls


def test_recall_uses_a_new_session_persona_only_and_does_not_repeat_the_answer(prepared):
    client = MemoryService()
    memory = PreparedPreferenceMemory(prepared, client=client)
    first = memory.recall(PERSONA, "requirement")[0]
    second = memory.recall(PERSONA, "requirement")[0]
    assert first["session_id"] != second["session_id"]
    assert first["source_ids"] == ["requirement-node"] and first["data_ids"] == ["persona-data"]
    for call in client.calls:
        assert call["datasets"] == [DATASET] and call["scope"] == "graph" and call["only_context"] is True
        assert "30" not in call["query"] and "days" not in call["query"]


@pytest.mark.parametrize("case", ["invented-id", "unrelated-node", "other-dataset", "session-result", "wrong-value"])
def test_plausible_recall_text_cannot_replace_matching_semantic_graph_evidence(prepared, case):
    client = MemoryService()
    row = client.response[0]
    if case == "invented-id":
        row["metadata"]["evidence"][0]["artifact_id"] = "invented"
    elif case == "unrelated-node":
        row["metadata"]["evidence"][0]["artifact_id"] = "persona-node"
    elif case == "other-dataset":
        row["metadata"]["evidence"][0]["dataset_id"] = "catalog-dataset"
    elif case == "session-result":
        row["source"] = "session"
    else:
        row["text"] = "Confirmed synthetic durable requirement: a 14-day return window."
    memory = PreparedPreferenceMemory(prepared, client=client)
    with pytest.raises(PreparedMemoryError, match="matching source IDs"):
        memory.recall(PERSONA, "requirement")


def test_recalled_requirement_changes_policy_eligibility_but_never_authorizes_purchase(prepared, monkeypatch):
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **kw: pytest.fail("Research comparison must not open household storage"))
    memory = PreparedPreferenceMemory(prepared, client=MemoryService())
    publisher = senso_provider()
    try:
        result = get_research_memory(prepared, memory=memory, publisher=publisher)
    finally:
        publisher.close()
    assert result["state"] == "ready" and result["synthetic_demo"] and result["research_only"]
    assert result["requirement"]["value"] == 30 and not result["proposal_allowed"]
    positive, negative = result["candidates"]
    assert positive["requirement_state"] == "supported" and positive["policy_eligible"]
    assert negative["requirement_state"] == "contradicted" and not negative["policy_eligible"]
    assert negative["passages"][0]["passage"] == "7 days return policy"
    assert all(c["decision"] == "Wait" and not c["proposal_allowed"] for c in result["candidates"])


def test_senso_outage_keeps_the_recalled_preference_but_marks_all_evidence_unresolved(prepared):
    memory = PreparedPreferenceMemory(prepared, client=MemoryService())
    publisher = senso_provider(unavailable=True)
    try:
        result = get_research_memory(prepared, memory=memory, publisher=publisher)
    finally:
        publisher.close()
    assert result["state"] == "pending" and result["requirement"]["value"] == 30
    assert all(c["requirement_state"] == "unknown" and not c["policy_eligible"] for c in result["candidates"])
    assert "secret remote diagnostic" not in json.dumps(result)


def test_research_products_cannot_be_promoted_to_application_quotes(prepared):
    memory = PreparedPreferenceMemory(prepared, client=MemoryService())
    memory.artifacts = copy.deepcopy(memory.artifacts)
    memory.artifacts["normalized.json"]["products"][0]["application_product_id"] = "arc-light"
    result = get_research_memory(prepared, memory=memory)
    assert result["state"] == "blocked" and not result["candidates"] and not result["proposal_allowed"]
