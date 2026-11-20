"""Safeguards for the isolated data-preparation job, without provider traffic."""
import json
import sqlite3

import httpx
import pytest

from app.preparation.job import PreparationJob, content_hash, save_json


@pytest.mark.parametrize("setting,value", [
    ("max_products", 0), ("max_products", 25), ("enrich_products", -1), ("enrich_products", 7),
    ("max_model_calls", -1), ("max_model_calls", 13), ("concurrency", 0), ("concurrency", 3),
])
def test_unbounded_jobs_are_rejected_before_artifacts_are_created(tmp_path, setting, value):
    with pytest.raises(ValueError):
        PreparationJob(tmp_path / "job", **{setting: value})
    assert not (tmp_path / "job" / "manifest.json").exists()


@pytest.mark.parametrize("owner", ["demo-user", "../real-user", "a", "has spaces"])
def test_synthetic_owner_cannot_reuse_active_user_or_escape_scope(tmp_path, owner):
    with pytest.raises(ValueError):
        PreparationJob(tmp_path / "job", synthetic_owner=owner)


def test_existing_job_requires_explicit_resume_and_preserves_namespace_and_external_ledger(tmp_path):
    original = PreparationJob(tmp_path)
    original.manifest["senso_ledger"]["dummyjson:product:1"] = {
        "content_id": "accepted-content", "status": "ambiguous", "content_hash": "h"}
    original.checkpoint()
    before = original.path.read_bytes()
    with pytest.raises(ValueError, match="resume"):
        PreparationJob(tmp_path)
    assert original.path.read_bytes() == before
    resumed = PreparationJob(tmp_path, resume=True)
    assert resumed.manifest["job_id"] == original.manifest["job_id"]
    assert resumed.manifest["senso_ledger"] == original.manifest["senso_ledger"]


def test_resume_cannot_reassign_private_synthetic_memory_to_another_owner(tmp_path):
    original = PreparationJob(tmp_path, synthetic_owner="intent-test-owner")
    before = original.path.read_bytes()
    with pytest.raises(ValueError, match="owner"):
        PreparationJob(tmp_path, resume=True, synthetic_owner="other-owner")
    assert original.path.read_bytes() == before


def test_expansion_requires_a_completed_live_smoke_not_only_local_validation(tmp_path):
    with pytest.raises(ValueError):
        PreparationJob(tmp_path / "fresh", max_products=24)
    job = PreparationJob(tmp_path / "smoke", dry_run=True)
    job.manifest["smoke_validated"] = True
    job.checkpoint()
    with pytest.raises(ValueError):
        PreparationJob(tmp_path / "smoke", resume=True, max_products=24)
    job.manifest["smoke_verified"] = True
    job.checkpoint()
    expanded = PreparationJob(tmp_path / "smoke", resume=True, max_products=24)
    assert expanded.manifest["job_id"] == job.manifest["job_id"]
    assert expanded.manifest["config"]["max_products"] == 24


def test_pending_external_stage_stops_later_actions_and_is_checkpointed(tmp_path, monkeypatch):
    job = PreparationJob(tmp_path)
    monkeypatch.setattr(job, "fetch", lambda: {"state": "pending", "reason": "still indexing"})
    monkeypatch.setattr(job, "normalize", lambda: pytest.fail("Must not advance past pending processing"))
    result = job.run("all")
    saved = json.loads(job.path.read_text())
    assert result["stages"]["fetch"]["state"] == saved["stages"]["fetch"]["state"] == "pending"
    assert "normalize" not in saved["stages"]


def test_failed_stage_records_safe_error_without_copying_credentials(tmp_path, monkeypatch, capsys):
    job = PreparationJob(tmp_path)

    def fail():
        saved = json.loads(job.path.read_text())
        assert saved["stages"]["fetch"]["state"] == "running"
        raise RuntimeError("credential-like-sensitive-value")

    monkeypatch.setattr(job, "fetch", fail)
    with pytest.raises(RuntimeError):
        job.run("fetch")
    saved = json.loads(job.path.read_text())
    assert saved["stages"]["fetch"]["state"] == "failed"
    assert saved["stages"]["fetch"]["error_class"] == "RuntimeError"
    assert "credential-like-sensitive-value" not in job.path.read_text()
    assert "credential-like-sensitive-value" not in capsys.readouterr().out


def test_job_construction_resume_and_checkpoints_do_not_open_application_database(tmp_path, monkeypatch):
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **kw: pytest.fail("Preparation cannot open the app database"))
    job = PreparationJob(tmp_path)
    job.checkpoint()
    resumed = PreparationJob(tmp_path, resume=True)
    assert resumed.manifest["job_id"] == job.manifest["job_id"]


def prepared_artifacts(job, count=1):
    """A sealed prior validation result, used to exercise publication guards."""
    documents = [{"source_id": f"dummyjson:product:{i}", "text": f"Sample product {i}",
                  "content_hash": content_hash(f"Sample product {i}"), "schema_version": "intent-cognee-v1",
                  "title": f"Sample product {i}"} for i in range(count)]
    artifacts = {"documents.json": documents, "normalized.json": {"products": []},
                 "research-findings.json": [], "personas.json": []}
    for name, value in artifacts.items():
        save_json(job.output / name, value)
    job.manifest["validated_artifacts"] = {name: content_hash(value) for name, value in artifacts.items()}
    job.checkpoint()
    return documents


@pytest.mark.parametrize("artifact", ["normalized.json", "documents.json", "research-findings.json", "personas.json"])
def test_mutation_stage_rejects_changed_artifacts_before_remote_client_creation(tmp_path, monkeypatch, artifact):
    job = PreparationJob(tmp_path)
    prepared_artifacts(job)
    save_json(job.output / artifact, {"altered": "unvalidated value"})
    monkeypatch.setattr(httpx, "Client", lambda *a, **kw: pytest.fail("Must validate before creating a provider client"))
    with pytest.raises(ValueError, match="changed|validated"):
        job.publish_senso()
    assert not job.manifest["senso_ledger"]


def test_standalone_publication_requires_validation_even_with_a_document_file(tmp_path, monkeypatch):
    job = PreparationJob(tmp_path)
    save_json(job.output / "documents.json", [{"source_id": "dummyjson:product:1"}])
    monkeypatch.setattr(httpx, "Client", lambda *a, **kw: pytest.fail("Unvalidated upload attempted"))
    with pytest.raises(ValueError, match="validated"):
        job.publish_senso()


def test_publication_rechecks_bounds_after_resuming_with_a_smaller_limit(tmp_path, monkeypatch):
    job = PreparationJob(tmp_path, max_products=6)
    prepared_artifacts(job, count=6)
    resumed = PreparationJob(tmp_path, max_products=3, resume=True)
    monkeypatch.setattr(httpx, "Client", lambda *a, **kw: pytest.fail("Oversized upload attempted"))
    with pytest.raises(ValueError, match="bound"):
        resumed.publish_senso()


def test_duplicate_sources_cannot_be_published_even_if_artifact_is_sealed(tmp_path, monkeypatch):
    job = PreparationJob(tmp_path)
    documents = prepared_artifacts(job)
    documents.append(documents[0])
    save_json(job.output / "documents.json", documents)
    job.manifest["validated_artifacts"]["documents.json"] = content_hash(documents)
    monkeypatch.setattr(httpx, "Client", lambda *a, **kw: pytest.fail("Duplicate upload attempted"))
    with pytest.raises(ValueError, match="Duplicate"):
        job.publish_senso()


def test_dry_run_senso_never_creates_a_provider_client_or_marks_live_smoke_verified(tmp_path, monkeypatch):
    job = PreparationJob(tmp_path, dry_run=True)
    prepared_artifacts(job)
    monkeypatch.setattr(httpx, "Client", lambda *a, **kw: pytest.fail("Dry-run must not open a provider client"))
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **kw: pytest.fail("Dry-run must not open the app database"))
    result = job.publish_senso()
    assert result["state"] == "planned" and result["remote_mutations"] == 0
    assert not job.manifest["senso_ledger"] and not job.manifest.get("smoke_verified")
