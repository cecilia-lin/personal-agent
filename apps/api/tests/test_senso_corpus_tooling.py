"""Corpus upload idempotency and exact-source binding without provider traffic."""
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/senso_corpus_check.py"
spec = importlib.util.spec_from_file_location("senso_corpus_tooling", SCRIPT)
corpus = importlib.util.module_from_spec(spec)
spec.loader.exec_module(corpus)


class Publisher:
    def __init__(self, documents, *, ambiguous=False, altered=False, fail_binding=False):
        self.documents = documents
        self.ambiguous, self.altered = ambiguous, altered
        self.fail_binding = fail_binding
        self.uploads = []

    def _request(self, method, path, **kwargs):
        if path == "/org/kb/find":
            return 200, {"nodes": []}
        if path.endswith("/content"):
            if self.fail_binding:
                raise corpus.SensoJobError("Temporary read failure")
            product_id = path.split("/")[-2].removeprefix("node-")
            text = self.documents[product_id]["text"]
            return 200, {"id": "content-" + product_id, "text": text + "altered" if self.altered else text,
                         "version_num": 1, "processing_status": "complete"}
        if path == "/org/search/context":
            data = kwargs["json"]
            assert data["require_scoped_ids"] is True
            content_id = data["content_ids"][0]
            return 200, {"results": [{"content_id": content_id, "version_id": "version-" + content_id,
                                     "content_chunk_id": "chunk-" + content_id, "chunk_text": "fixture passage"}]}
        pytest.fail("Unexpected remote operation: " + path)

    def publish(self, document, existing, checkpoint):
        if existing:
            return existing
        entry = {**{k: v for k, v in document.items() if k != "text"}, "namespace": corpus.NAMESPACE,
                 "status": "inflight", "content_id": None, "kb_node_id": None, "version_id": None}
        checkpoint(entry)
        # A durable entry must exist before the external mutation.
        self.uploads.append(document)
        if self.ambiguous:
            entry["status"] = "ambiguous"
        else:
            entry.update(status="processing", content_id="content-" + document["source_id"],
                         kb_node_id="node-" + document["source_id"])
        checkpoint(entry)
        return entry

    def wait_ready(self, entry, **kwargs):
        return {**entry, "status": "ready"}


def test_only_four_fictional_specs_are_eligible_for_upload():
    docs = corpus.documents()
    assert set(docs) == set(corpus.DOCS)
    assert all("Fictional demo data" in doc["text"] for doc in docs.values())
    assert all("Expected verdict" not in doc["text"] for doc in docs.values())
    assert "not user-replaceable" in docs["fold-light"]["text"]
    halo_bulb = next(case for case in corpus.CASES if case[0] == "halo-light" and case[2] == "replaceable_bulb")
    assert halo_bulb[-1] == "unsupported"


def test_repeat_upload_reuses_ledger_and_keeps_exact_scoped_versions(tmp_path):
    path = tmp_path / "ledger.json"
    publisher = Publisher(corpus.documents())
    ledger = corpus.load_ledger(path)
    assert corpus.prepare(publisher, ledger, path, allow_upload=True)
    assert len(publisher.uploads) == 4
    assert corpus.prepare(publisher, corpus.load_ledger(path), path, allow_upload=True)
    assert len(publisher.uploads) == 4
    assert all(entry["status"] == "ready" and entry["version_id"] and entry["source_path"].endswith("_spec_v1.md")
               for entry in corpus.load_ledger(path)["products"].values())


def test_ambiguous_upload_is_reconciled_without_replaying_mutation(tmp_path):
    path = tmp_path / "ledger.json"
    publisher = Publisher(corpus.documents(), ambiguous=True)
    assert not corpus.prepare(publisher, corpus.load_ledger(path), path, allow_upload=True)
    assert not corpus.prepare(publisher, corpus.load_ledger(path), path, allow_upload=True)
    assert len(publisher.uploads) == 4
    assert {entry["status"] for entry in corpus.load_ledger(path)["products"].values()} == {"ambiguous"}


def test_wrong_remote_body_is_blocked_even_when_processing_is_complete(tmp_path):
    path = tmp_path / "ledger.json"
    publisher = Publisher(corpus.documents(), altered=True)
    assert not corpus.prepare(publisher, corpus.load_ledger(path), path, allow_upload=True)
    assert {entry["status"] for entry in corpus.load_ledger(path)["products"].values()} == {"blocked"}


def test_checks_only_does_not_publish_missing_specs_and_later_upload_is_allowed(tmp_path):
    path = tmp_path / "ledger.json"
    publisher = Publisher(corpus.documents())
    assert not corpus.prepare(publisher, corpus.load_ledger(path), path, allow_upload=False)
    assert not publisher.uploads
    assert corpus.prepare(publisher, corpus.load_ledger(path), path, allow_upload=True)
    assert len(publisher.uploads) == 4


def test_network_error_after_ingestion_does_not_claim_verified_readiness(tmp_path):
    path = tmp_path / "ledger.json"
    publisher = Publisher(corpus.documents(), fail_binding=True)
    assert not corpus.prepare(publisher, corpus.load_ledger(path), path, allow_upload=True)
    assert {entry["status"] for entry in corpus.load_ledger(path)["products"].values()} == {"pending"}


def test_concurrent_upload_process_is_rejected(tmp_path):
    path = tmp_path / "ledger.json"
    with corpus.exclusive_run(path):
        with pytest.raises(ValueError, match="lock"):
            with corpus.exclusive_run(path):
                pytest.fail("Concurrent mutation was allowed")
    assert not path.with_suffix(".lock").exists()
