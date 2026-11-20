"""Documented Senso evals require an exact claim and approved unchanged evidence."""
import copy
import hashlib
import json

import httpx
import pytest

from app.integrations.claim_verification import allowed, evidence_fingerprint
from app.integrations.senso import SensoEvidenceProvider, evidence_provider, repairability_claim


CLAIM = "Arc desk light has a replaceable bulb."
QUOTE = "The Arc desk light bulb is user-replaceable without tools."
BODY = "# Arc desk light spec\n" + QUOTE
PRODUCT = {"id": "arc-light", "name": "Arc desk light", "version": 1,
           "description": "Adjustable arm, replaceable bulb, and a two-year fixture warranty."}


def fixtures():
    source = {"status": "ready", "content_id": "approved-content", "kb_node_id": "approved-node",
              "version_id": "approved-version", "content_hash": hashlib.sha256(BODY.encode()).hexdigest(),
              "title": "Arc desk light spec"}
    ledger = {"schema_version": "intent-senso-corpus-v1", "products": {"arc-light": source}}
    run = {"eval_run_id": "real-run", "evaluator_key": "kb_accuracy", "evaluator_version": "1.2",
           "status": "completed", "subject": {"text": CLAIM}, "finished_at": "2026-11-20T23:28:07Z",
           "claims": [{"eval_claim_id": "real-claim", "source_text": CLAIM.rstrip("."), "claim_text": CLAIM,
                       "verdict": "verified", "passed": True, "quote": QUOTE, "grounding_failed": False,
                       "evidence": [{"content_id": "approved-content", "chunk_index": 0, "relation": "entails"}]}],
           "evidence_chunks": [{"content_id": "approved-content", "chunk_index": 0, "text": QUOTE}]}
    return ledger, run


def provider_for(run, *, changed_body=False, replay=False, pending=False, outage=False):
    ledger, _ = fixtures()
    calls, bodies = [], [0]

    def handler(request):
        calls.append((request.method, request.url.path))
        if outage:
            return httpx.Response(503, json={"error": "sensitive provider body"})
        if request.url.path.endswith("/content"):
            bodies[0] += 1
            body = BODY + " changed" if changed_body and bodies[0] >= 3 else BODY
            return httpx.Response(200, json={"id": "approved-content", "text": body,
                                            "version_num": 1, "processing_status": "complete"})
        if request.url.path.endswith("/search/context"):
            payload = json.loads(request.content)
            assert payload["content_ids"] == ["approved-content"] and payload["require_scoped_ids"] is True
            return httpx.Response(200, json={"results": [{"content_id": "approved-content", "version_id": "approved-version",
                                                         "content_chunk_id": "actual-chunk", "chunk_text": BODY}]})
        if request.url.path.endswith("/evals/text"):
            payload = json.loads(request.content)
            assert payload["text"] == CLAIM and payload["evaluator"] == "kb_accuracy"
            assert "content_ids" not in payload and payload["idempotency_key"].startswith("intent-claim-")
            if pending:
                return httpx.Response(202, json={"eval_run_id": "real-run", "status": "queued"})
            if replay:
                return httpx.Response(202, json={"eval_run_id": "real-run", "status": "completed"})
            return httpx.Response(200, json=run)
        assert request.url.path.endswith("/evals/runs/real-run")
        return httpx.Response(200, json=run)

    provider = SensoEvidenceProvider("test-key", transport=httpx.MockTransport(handler), ledger=ledger,
                                      max_wait_seconds=0)
    return provider, calls


def evaluate(run, **kwargs):
    provider, calls = provider_for(run, **kwargs)
    try:
        return provider.verify_product(PRODUCT, provider.for_product(PRODUCT)), calls
    finally:
        provider.close()


def test_real_evaluation_preserves_check_quote_and_actual_context_version_when_eval_version_is_absent():
    _, run = fixtures()
    result, _ = evaluate(run)
    assert result["state"] == "supported" and allowed(result, True)
    assert result["check_id"] == "real-run" and result["eval_claim_id"] == "real-claim"
    assert result["quote"] == QUOTE and result["sources"][0]["version_id"] == "approved-version"
    assert result["sources"][0]["evaluator_content_version_id"] is None
    assert result["version_binding"] == "scoped_context_uuid_and_unchanged_body_before_after_evaluation"


@pytest.mark.parametrize("change", ["wrong-claim", "wrong-subject", "wrong-version", "wrong-source", "invented-quote", "grounding-failed"])
def test_verified_label_alone_cannot_authorize_a_purchase(change):
    _, run = fixtures()
    checked = run["claims"][0]
    if change == "wrong-claim":
        checked["source_text"] = "Arc desk light has serviceable components."
    elif change == "wrong-subject":
        run["subject"]["text"] = "Another product has a replaceable bulb."
    elif change == "wrong-version":
        checked["evidence"][0]["content_version_id"] = "unapproved-version"
    elif change == "wrong-source":
        checked["evidence"][0]["content_id"] = "unapproved-content"
    elif change == "invented-quote":
        checked["quote"] = "A made-up assertion not in the approved document."
    else:
        checked["grounding_failed"] = True
    result, _ = evaluate(run)
    assert result["state"] != "supported" and not allowed(result, True)


def test_additional_org_wide_entails_citation_is_ignored_and_cannot_supply_support():
    _, run = fixtures()
    run["claims"][0]["evidence"].append({"content_id": "old-combined", "relation": "entails", "chunk_index": 0})
    result, _ = evaluate(run)
    assert result["state"] == "supported" and len(result["sources"]) == 1
    assert result["sources"][0]["content_id"] == "approved-content"
    assert result["ignored_evidence"][0]["content_id"] == "old-combined"
    run["claims"][0]["evidence"] = [run["claims"][0]["evidence"][1]]
    result, _ = evaluate(run)
    assert not allowed(result, True)


@pytest.mark.parametrize("verdict", ["conflict", "unsupported", "not_verifiable"])
def test_every_unresolved_or_negative_verdict_blocks(verdict):
    _, run = fixtures()
    run["claims"][0].update(verdict=verdict, passed=False)
    result, _ = evaluate(run)
    assert result["state"] == verdict and not allowed(result, True)


def test_source_changed_during_evaluation_blocks_even_a_verified_verdict():
    _, run = fixtures()
    result, _ = evaluate(run, changed_body=True)
    assert result["state"] == "error" and not allowed(result, True)


def test_idempotent_completed_summary_is_followed_to_full_run_detail():
    _, run = fixtures()
    result, calls = evaluate(run, replay=True)
    assert result["state"] == "supported"
    assert ("GET", "/api/v1/org/evals/runs/real-run") in calls


def test_pending_and_service_failure_are_honest_and_non_executable():
    _, run = fixtures()
    pending, _ = evaluate(run, pending=True)
    outage, _ = evaluate(run, outage=True)
    assert pending["state"] == "pending" and pending["check_id"] == "real-run"
    assert outage["state"] == "error" and "sensitive provider body" not in json.dumps(outage)
    assert not allowed(pending, True) and not allowed(outage, True)


def test_same_source_body_version_stays_stable_across_new_checks_and_quote_selection():
    _, run = fixtures()
    first, _ = evaluate(run)
    second = copy.deepcopy(first)
    second["check_id"] = "new-real-check"
    second["sources"][0]["excerpt"] = "Another valid passage from the same approved body."
    assert evidence_fingerprint(first["sources"]) == evidence_fingerprint(second["sources"])
    second["sources"][0]["version_id"] = "changed-source-version"
    assert evidence_fingerprint(first["sources"]) != evidence_fingerprint(second["sources"])


def test_missing_live_key_never_silently_falls_back_to_fixture(monkeypatch):
    monkeypatch.setenv("INTEGRATIONS_ENABLED", "true")
    monkeypatch.delenv("EVIDENCE_PROVIDER", raising=False)
    monkeypatch.setenv("SENSO_API_KEY", "")
    provider = evidence_provider()
    try:
        assert isinstance(provider, SensoEvidenceProvider) and provider.requires_context
    finally:
        provider.close()


@pytest.mark.parametrize("feature,phrase", [("replaceable_bulb", "a replaceable bulb"),
    ("replaceable_light_module", "a replaceable light module"), ("serviceable_components", "serviceable components")])
def test_precise_user_requirement_does_not_collapse_distinct_capabilities(feature, phrase):
    found = repairability_claim(PRODUCT | {"_required_feature": feature})
    assert found == {"feature": feature, "claim": "Arc desk light has " + phrase + "."}
