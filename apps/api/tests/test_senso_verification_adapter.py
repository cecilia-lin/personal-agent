"""The retrieval-only fallback must never manufacture a fact-check verdict."""
import json

import httpx
import pytest

from app.config import ROOT
from app.integrations.claim_verification import allowed
from app.integrations.senso import SensoEvidenceProvider, repairability_claim


@pytest.fixture
def products():
    return {p["id"]: p for p in json.loads((ROOT / "fixtures/demo.json").read_text())["products"]}


def test_catalog_features_are_distinct_precise_claims(products):
    expected = {
        "arc-light": ("replaceable_bulb", "Arc desk light has a replaceable bulb."),
        "fold-light": ("replaceable_light_module", "Fold task light has a replaceable light module."),
        "halo-light": ("serviceable_components", "Halo studio light has serviceable components."),
    }
    for product_id, (feature, claim) in expected.items():
        assert repairability_claim(products[product_id]) == {"feature": feature, "claim": claim}
    assert repairability_claim(products["mini-light"])["claim"] is None
    changed = {**products["arc-light"], "description": "No replaceable bulb; sealed assembly."}
    assert repairability_claim(changed)["claim"] is None


def test_retrieved_passage_never_becomes_fact_check_support(products):
    def forbidden_request(request):
        raise AssertionError("No fact-check endpoint has been confirmed.")

    provider = SensoEvidenceProvider("test-key", transport=httpx.MockTransport(forbidden_request))
    passages = [{"content_id": "doc-1", "version_id": "v1", "excerpt": "Arc desk light has a replaceable bulb."}]
    try:
        result = provider.verify_product(products["arc-light"], passages)
        assert result["state"] == "not_verifiable"
        assert result["check_id"] is None
        assert result["checked_at"] is None
        assert result["sources"] == []
        assert result["retrieved_sources"] == passages
        assert not allowed(result, live=True)
        assert provider.status()["fact_check_verified"] is False
    finally:
        provider.close()


def test_unknown_catalog_claim_is_not_verifiable(products):
    provider = SensoEvidenceProvider("test-key")
    try:
        result = provider.verify_product({**products["arc-light"], "id": "new-light"}, [])
        assert result["state"] == "not_verifiable"
        assert result["feature"] is None
        assert not allowed(result, live=True)
    finally:
        provider.close()


def test_retrieval_service_error_is_explicit_and_blocks(products):
    provider = SensoEvidenceProvider("test-key", transport=httpx.MockTransport(
        lambda request: httpx.Response(503, json={"message": "unavailable"})))
    try:
        passages = provider.for_product(products["arc-light"])
        result = provider.verify_product(products["arc-light"], passages)
        assert result["state"] == "error"
        assert "retrieval is unavailable" in result["reason"]
        assert result["check_id"] is None and not allowed(result, live=True)
    finally:
        provider.close()
