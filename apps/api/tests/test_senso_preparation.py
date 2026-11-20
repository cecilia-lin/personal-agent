"""Preparation uploads are bounded, resumable, scoped and semantically modest."""
import hashlib
import json

import httpx
import pytest
from pydantic import ValidationError

from app.preparation.senso_publish import SensoJobError, SensoPublisher, SourceDocument, policy_findings


@pytest.fixture
def document():
    text = "DummyJSON sample product 1\nReturn policy: 30 days return policy\nShipping: Ships in 3-5 business days\nWarranty: 1 year warranty"
    return {"source_id": "dummyjson:product:1", "title": "Sample product", "text": text,
            "content_hash": hashlib.sha256(text.encode()).hexdigest(), "schema_version": "intent-cognee-v1"}


@pytest.fixture
def ledger(document):
    return {k: v for k, v in document.items() if k != "text"} | {
        "namespace": "preparation-test", "content_id": "content-1", "kb_node_id": "node-1",
        "version_id": "version-1", "status": "ready"}


@pytest.fixture
def product(document):
    return {"product_id": document["source_id"], "source_version": "normalized-source-hash",
            "policies": {"return_policy": "30 days return policy", "shipping": "Ships in 3-5 business days",
                         "warranty": "1 year warranty"}}


def provider(handler, **kwargs):
    return SensoPublisher("test-key", "preparation-test", transport=httpx.MockTransport(handler), **kwargs)


def result(**overrides):
    return {"content_id": "content-1", "content_chunk_id": "chunk-1", "version_id": "version-1",
            "kb_node_id": "node-1", "chunk_text": "30 days return policy", **overrides}


def test_source_digest_and_utf8_size_are_validated_before_publication(document):
    SourceDocument.model_validate(document)
    with pytest.raises(ValidationError, match="content_hash"):
        SourceDocument.model_validate(document | {"text": "changed"})
    text = "日" * 15000
    with pytest.raises(ValidationError, match="40 KB"):
        SourceDocument.model_validate(document | {"text": text, "content_hash": hashlib.sha256(text.encode()).hexdigest()})


def test_upload_checkpoints_before_and_after_external_mutation(document):
    checkpoints, calls = [], []

    def handler(request):
        assert len(checkpoints) == 1 and checkpoints[0]["status"] == "inflight"
        assert request.url.path == "/api/v1/org/kb/raw"
        body = json.loads(request.content)
        assert body == {"title": "preparation-test | Sample product", "text": document["text"]}
        calls.append(body)
        return httpx.Response(202, json={"id": "content-1", "kb_node_id": "node-1",
                                        "latest_content_version_id": "version-1"})

    pub = provider(handler)
    try:
        entry = pub.publish(document, checkpoint=checkpoints.append)
        assert entry["status"] == "processing" and entry["version_id"] == "version-1"
        assert [x["status"] for x in checkpoints] == ["inflight", "processing"]
        assert pub.publish(document, entry, checkpoints.append) == entry
        assert len(calls) == 1
    finally:
        pub.close()


def test_timeout_is_ambiguous_and_resume_never_reposts(document):
    calls, checkpoints = [], []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("secret backend detail", request=request)

    pub = provider(handler)
    try:
        entry = pub.publish(document, checkpoint=checkpoints.append)
        assert entry["status"] == "ambiguous"
        assert "secret" not in entry["error"]
        assert pub.publish(document, entry)["status"] == "ambiguous"
        assert len(calls) == 1
        assert [x["status"] for x in checkpoints] == ["inflight", "ambiguous"]
    finally:
        pub.close()


def test_duplicate_is_not_rewritten_or_reuploaded(document):
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(409, json={"detail": "duplicate"})

    pub = provider(handler)
    try:
        entry = pub.publish(document)
        assert entry["status"] == "duplicate" and entry["content_id"] is None
        pub.publish(document, entry)
        assert len(calls) == 1 and calls[0]["text"] == document["text"]
    finally:
        pub.close()


@pytest.mark.parametrize("change", [{"namespace": "unrelated"}, {"content_hash": "a" * 64}])
def test_resume_refuses_an_unrelated_ledger(document, ledger, change):
    pub = provider(lambda _: pytest.fail("No remote call is allowed"))
    try:
        with pytest.raises(ValueError):
            pub.publish(document, ledger | change)
    finally:
        pub.close()


def test_actual_node_readiness_is_polled_and_pending_is_bounded(ledger):
    elapsed, calls = [0], []

    def handler(request):
        assert request.method == "GET" and request.url.path.endswith("/org/kb/nodes/node-1")
        calls.append(request)
        return httpx.Response(200, json={"content_id": "content-1", "content": {"processing_status": "processing"}})

    pub = provider(handler, clock=lambda: elapsed[0], sleep=lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds))
    try:
        pending = pub.wait_ready(ledger, max_wait_seconds=10)
        assert pending["status"] == "pending" and elapsed[0] == 10 and len(calls) == 3
    finally:
        pub.close()


def test_complete_node_is_ready_but_changed_identity_is_rejected(ledger):
    pub = provider(lambda _: httpx.Response(200, json={"content_id": "content-1", "content": {"processing_status": "complete"}}))
    try:
        assert pub.wait_ready(ledger | {"status": "processing"})["status"] == "ready"
    finally:
        pub.close()
    pub = provider(lambda _: httpx.Response(200, json={"content_id": "other", "content": {"processing_status": "complete"}}))
    try:
        with pytest.raises(SensoJobError, match="identity"):
            pub.wait_ready(ledger)
    finally:
        pub.close()


def test_scoped_retrieval_also_filters_content_node_version_and_chunk(ledger):
    def handler(request):
        body = json.loads(request.content)
        assert body["content_ids"] == ["content-1"] and body["require_scoped_ids"] is True
        assert body["max_results"] == 5
        return httpx.Response(200, json={"results": [
            result(content_id="unrelated"), result(version_id="old-version"), result(kb_node_id="other"),
            result(content_chunk_id=None), result(version_id=None), result()]})

    pub = provider(handler)
    try:
        found = pub.retrieve(ledger, "return policy", max_results=50)
        assert len(found) == 1
        assert found[0]["content_chunk_id"] == "chunk-1"
        assert found[0]["source_hash"] == ledger["content_hash"]
        assert found[0]["operation"] == "context_retrieval"
        assert found[0]["checked_at"]
    finally:
        pub.close()


@pytest.mark.parametrize("change", [{"status": "processing"}, {"version_id": None}, {"namespace": "other"}])
def test_unready_or_unversioned_sources_cannot_be_queried(ledger, change):
    pub = provider(lambda _: pytest.fail("No remote call is allowed"))
    try:
        with pytest.raises(SensoJobError):
            pub.retrieve(ledger | change, "return policy")
    finally:
        pub.close()


def get_passages(ledger, text):
    pub = provider(lambda _: httpx.Response(200, json={"results": [result(chunk_text=text)]}))
    try:
        return pub.retrieve(ledger, "policy")
    finally:
        pub.close()


@pytest.mark.parametrize("policy,state,value", [
    ("30 days return policy", "supported", 30), ("14 days return policy", "contradicted", 14),
    ("No return policy", "unknown", None)])
def test_return_window_is_grounded_and_ambiguous_policy_stays_unknown(product, ledger, policy, state, value):
    product["policies"]["return_policy"] = policy
    findings = policy_findings(product, ledger, get_passages(ledger, policy), run_id="test-run-1")
    found = findings[0]
    assert found["state"] == state and found["extracted_value"] == value
    assert found["sources"][0]["version_id"] == "version-1"
    assert found["execution_kind"] == "deterministic_parser" and found["run_id"] == "test-run-1"
    assert found["synthetic_demo"] is True


def test_matching_id_without_supporting_text_does_not_establish_a_policy(product, ledger):
    findings = policy_findings(product, ledger, get_passages(ledger, "A stylish product in several colors."))
    assert all(x["state"] == "unknown" and not x["sources"] for x in findings)


def test_numeric_substring_does_not_count_as_the_exact_source_statement(product, ledger):
    findings = policy_findings(product, ledger, get_passages(ledger, "130 days return policy"))
    assert findings[0]["state"] == "unknown" and not findings[0]["sources"]


def test_shipping_and_warranty_preserve_only_the_recorded_statement(product, ledger, document):
    findings = policy_findings(product, ledger, get_passages(ledger, document["text"]))
    shipping, warranty = findings[1:]
    assert shipping["state"] == "supported" and shipping["extracted_value"] == "Ships in 3-5 business days"
    assert "no delivery date or fee" in shipping["reason"]
    assert warranty["extracted_value"] == "1 year warranty"
    assert "shipping costs remain unknown" in findings[0]["reason"]


@pytest.mark.parametrize("forgery", [{"content_id": "other"}, {"source_hash": "forged"}, {"version_id": "old"}])
def test_policy_parser_rejects_citations_outside_approved_ledger(product, ledger, forgery):
    passages = get_passages(ledger, "30 days return policy")
    passages[0].update(forgery)
    with pytest.raises(ValueError, match="approved source ledger"):
        policy_findings(product, ledger, passages)


def test_response_size_is_bounded_and_raw_body_is_not_exposed(ledger):
    pub = provider(lambda _: httpx.Response(200, content=b"private" * 100), max_response_bytes=50)
    try:
        with pytest.raises(SensoJobError, match="size limit") as error:
            pub.retrieve(ledger, "policy")
        assert "private" not in str(error.value)
    finally:
        pub.close()
