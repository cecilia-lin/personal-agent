"""Source semantics, reproducibility and session boundaries of preparation data."""
from copy import deepcopy
from decimal import Decimal
import json

import httpx
import pytest
from pydantic import ValidationError

from app.preparation.catalog import (
    LICENSE_URL, SOURCE_URL, ProductEvidence, fetch_snapshot, normalize_product,
    normalize_snapshot, product_document, research_findings, return_days, sha,
    synthetic_scenarios,
)


META = {"sha256": "a" * 64, "retrieved_at": "2026-11-20T12:00:00+00:00"}


def raw_product(identifier=1, category="laptops", **changes):
    return {
        "id": identifier, "title": f"Sample device {identifier}", "category": category,
        "description": "Sample catalog description", "price": Decimal("19.990"),
        "discountPercentage": Decimal("4.25"), "stock": 10, "minimumOrderQuantity": 3,
        "returnPolicy": "30 days return policy", "shippingInformation": "Ships in 1 week",
        "warrantyInformation": "1 year warranty", "dimensions": {"width": 4}, "weight": 2,
        "meta": {"createdAt": "2025-01-01T00:00:00Z", "updatedAt": "2025-02-01T00:00:00Z"},
        **changes,
    }


def test_decimal_observation_preserves_value_without_guessing_merchant_terms():
    result = normalize_product(raw_product(), META)
    assert result["price_observation"]["amount_decimal"] == "19.990"
    assert result["price_observation"]["currency"] is None
    assert result["price_observation"]["minor_units"] is None
    assert result["minimum_order_quantity"] == 3
    assert result["source_timestamps"]["updatedAt"] == "2025-02-01T00:00:00Z"
    assert result["application_product_id"] is None and not result["executable_quote"]
    assert {"shipping_fee", "delivery_date", "free_return_shipping", "dimension_units", "weight_units"} <= set(result["unknowns"])
    assert result["policies"]["shipping"] == "Ships in 1 week"
    assert result["return_window_days"] == 30
    assert result["source_version"] == sha(raw_product())


@pytest.mark.parametrize("value", ["No return policy", "Free returns", "30 days delivery", None])
def test_ambiguous_policy_never_establishes_a_return_window(value):
    result = normalize_product(raw_product(returnPolicy=value, minimumOrderQuantity=None), META)
    assert return_days(value) is None
    assert result["return_window_days"] is None
    assert result["minimum_order_quantity"] is None
    assert result["policies"]["return_policy"] == value
    assert {"return_window_days", "minimum_order_quantity"} <= set(result["unknowns"])


def test_reviews_are_bounded_anonymized_opinions():
    review = {"reviewerName": "Personal-looking name", "reviewerEmail": "person@example.com",
              "comment": "x" * 700, "rating": 4, "date": "2025-01-01"}
    result = normalize_product(raw_product(reviews=[review] * 5), META)
    assert len(result["reviews"]) == 3
    assert len(result["reviews"][0]["comment"]) == 600
    assert result["reviews"][0]["truncated"]
    assert "opinion" in result["reviews"][0]["interpretation"]
    output = json.dumps(result) + product_document(result)
    assert "person@example.com" not in output and "Personal-looking name" not in output


@pytest.mark.parametrize("identifier", [True, "1", 0, -1, Decimal("1")])
def test_source_identity_is_not_silently_repaired(identifier):
    with pytest.raises(ValueError):
        normalize_product(raw_product(identifier=identifier), META)


def test_research_record_schema_cannot_be_promoted_to_live_quote():
    result = normalize_product(raw_product(), META)
    with pytest.raises(ValidationError):
        ProductEvidence.model_validate({**result, "executable_quote": True})
    with pytest.raises(ValidationError):
        ProductEvidence.model_validate({**result, "application_product_id": "arc"})


def test_discovery_uses_two_present_categories_and_stable_six_product_prefix():
    raw = [raw_product(i, category) for i, category in enumerate(
        ["groceries"] * 5 + ["laptops"] * 5 + ["mobile-accessories"] * 14, start=1)]
    snapshot = {"products": raw, "metadata": META}
    smoke = normalize_snapshot(snapshot, 6)
    expanded = normalize_snapshot(snapshot, 24)
    assert smoke["categories"] == ["laptops", "mobile-accessories"]
    assert len(smoke["products"]) == 6 and len(expanded["products"]) == 19
    assert smoke["products"] == expanded["products"][:6]
    with pytest.raises(ValueError):
        normalize_snapshot(snapshot, 25)


def test_duplicate_and_invalid_records_are_rejected_without_invention():
    products = [raw_product(), raw_product(), raw_product(2, price="NaN")]
    result = normalize_snapshot({"products": products, "metadata": META}, 6)
    assert len(result["products"]) == 1
    assert len(result["rejected"]) == 2


def test_cache_reuses_exact_snapshot_and_rejects_tampering(tmp_path):
    payload = json.dumps({"products": [{"id": 1, "price": 19.99}], "total": 1}).encode()
    license_bytes = b"MIT License\nCopyright DummyJSON\nPermission is hereby granted"
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, content=license_bytes if str(request.url) == LICENSE_URL else payload)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        original = fetch_snapshot(tmp_path, client=client)
        again = fetch_snapshot(tmp_path, client=client)
        assert original == again
        assert calls == [SOURCE_URL, LICENSE_URL]
        assert (tmp_path / "snapshot.json").read_bytes() == payload
        assert original["metadata"]["sha256"] == sha(payload)
        assert original["products"][0]["price"] == Decimal("19.99")
        (tmp_path / "source-LICENSE.txt").write_bytes(b"changed")
        with pytest.raises(ValueError, match="license hash"):
            fetch_snapshot(tmp_path, client=client)
        (tmp_path / "source-LICENSE.txt").write_bytes(license_bytes)
        (tmp_path / "snapshot.json").write_bytes(b"{}")
        with pytest.raises(ValueError, match="snapshot hash"):
            fetch_snapshot(tmp_path, client=client)


def test_paginated_fallback_is_bounded_and_keeps_source_pages(tmp_path):
    calls = []

    def handler(request):
        url = str(request.url)
        calls.append(url)
        if url == SOURCE_URL:
            return httpx.Response(503)
        if url == LICENSE_URL:
            return httpx.Response(200, content=b"MIT\nPermission is hereby granted")
        return httpx.Response(200, json={"products": [{"id": 1}], "total": 1})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        snapshot = fetch_snapshot(tmp_path, client=client)
    assert len(calls) == 3
    assert snapshot["bounded_paginated_snapshot"]
    page = snapshot["metadata"]["pages"][0]
    assert page["sha256"] == sha((tmp_path / page["file"]).read_bytes())


def test_personas_only_reference_prior_research_and_keep_exceptions_out_of_durable_memory():
    products = [normalize_product(raw_product(i), META) for i in range(1, 25)]
    findings = research_findings(products[:6], "test-run")
    personas = synthetic_scenarios(products, findings, "intent-test-owner", "test-run")
    assert len(personas) == 3
    finding_ids = {finding["id"] for finding in findings}
    researched_ids = {finding["product_id"] for finding in findings}
    for persona in personas:
        assert set(persona["product_ids"]) <= researched_ids
        assert persona["session_id"] != persona["new_session_id"]
        for record in persona["durable_records"]:
            assert record["synthetic_demo"] and record["owner"] == persona["owner"]
            assert set(record["read_contribution_ids"]) <= finding_ids
            assert record["type"] != "temporary_exception"
        pref = next(record for record in persona["durable_records"] if record["type"] == "confirmed_preference")
        assert pref["requirement"]["value"] == 30
        assert pref["supersedes"] in {record["id"] for record in persona["durable_records"]}
        assert persona["session_entries"][0]["scope"] == "session_only"
    assert synthetic_scenarios(products, [], "intent-test-owner", "test-run") == []


def test_source_timestamps_do_not_change_existing_published_document_text():
    product = normalize_product(raw_product(), META)
    previous = deepcopy(product)
    previous.pop("source_timestamps")
    assert product_document(product) == product_document(previous)
