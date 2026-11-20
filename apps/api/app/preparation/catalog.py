"""Bounded DummyJSON research knowledge and explicitly synthetic memory fixtures."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "intent-catalog-v1"
SOURCE_URL = "https://dummyjson.com/products?limit=0"
LICENSE_URL = "https://raw.githubusercontent.com/Ovi/DummyJSON/master/LICENSE"
SOURCE_LABEL = "DummyJSON sample/synthetic product data; research only, not executable retailer offers"
MAX_BYTES = 5_000_000


def stamp():
    return datetime.now(timezone.utc).isoformat()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value).encode()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def _bounded_get(client, url, max_bytes=MAX_BYTES):
    chunks, size = [], 0
    with client.stream("GET", url) as response:
        response.raise_for_status()
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > max_bytes:
                raise ValueError("Source response exceeds the configured byte bound")
            chunks.append(chunk)
    return b"".join(chunks)


def fetch_snapshot(output: Path, refresh=False, client=None):
    """Cache source bytes: at most 12 GETs, 10 pages, 5 MB per snapshot attempt."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    target, manifest_path = output / "snapshot.json", output / "snapshot-manifest.json"
    own_client = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(20, connect=5), follow_redirects=False)
    try:
        if target.exists() and manifest_path.exists() and not refresh:
            raw = target.read_bytes()
            metadata = json.loads(manifest_path.read_text(encoding="utf-8"))
            if sha(raw) != metadata["sha256"]:
                raise ValueError("Cached snapshot hash mismatch; do not ingest modified source")
            if len(raw) > MAX_BYTES:
                raise ValueError("Cached source exceeds byte bound")
            license_path = output / "source-LICENSE.txt"
            if not license_path.exists() or sha(license_path.read_bytes()) != metadata["license_sha256"]:
                raise ValueError("Cached license hash mismatch; review before ingestion")
            payload = json.loads(raw, parse_float=Decimal)
            return {**payload, "metadata": metadata}
        urls, pages = [SOURCE_URL], []
        try:
            raw = _bounded_get(client, SOURCE_URL)
            payload = json.loads(raw, parse_float=Decimal)
            if not isinstance(payload.get("products"), list):
                raise ValueError("Source response has no products list")
        except (httpx.HTTPError, ValueError, TypeError):
            products, consumed = [], 0
            for page in range(10):
                url = f"https://dummyjson.com/products?limit=100&skip={page * 100}"
                part = _bounded_get(client, url, MAX_BYTES - consumed)
                consumed += len(part)
                data = json.loads(part, parse_float=Decimal)
                batch = data.get("products")
                if not isinstance(batch, list):
                    raise ValueError("Invalid paginated source")
                products.extend(batch)
                urls.append(url)
                filename = f"source-page-{page:02d}.json"
                (output / filename).write_bytes(part)
                pages.append({"url": url, "sha256": sha(part), "file": filename})
                if len(batch) < 100 or len(products) >= int(data.get("total", 1000)):
                    break
            payload = {"products": products, "total": len(products), "bounded_paginated_snapshot": True}
            raw = canonical(payload).encode()
        if len(raw) > MAX_BYTES:
            raise ValueError("Combined source exceeds byte bound")
        license_file = output / "source-LICENSE.txt"
        if refresh or not license_file.exists():
            license_file.write_bytes(_bounded_get(client, LICENSE_URL, 100_000))
        license_text = license_file.read_text(encoding="utf-8")
        if "MIT" not in license_text or "Permission is hereby granted" not in license_text:
            raise ValueError("Unexpected upstream license text; review before ingestion")
        target.write_bytes(raw)
        metadata = {"url": SOURCE_URL, "request_urls": urls, "retrieved_at": stamp(),
                    "sha256": sha(raw), "schema_version": SCHEMA_VERSION, "source_label": SOURCE_LABEL,
                    "source_count": len(payload["products"]), "pages": pages,
                    "attribution": "DummyJSON — Muhammad Ovi (Owais)", "license": "MIT",
                    "license_url": "https://github.com/Ovi/DummyJSON/blob/master/LICENSE",
                    "license_file": license_file.name, "license_sha256": sha(license_file.read_bytes()),
                    "official_source": "https://github.com/Ovi/DummyJSON/blob/master/database/products.json"}
        write_json(manifest_path, metadata)
        return {**payload, "metadata": metadata}
    finally:
        if own_client:
            client.close()


class ProductEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    product_id: str
    id: str
    source_id: int
    source_version: str
    snapshot_hash: str
    source_url: str
    schema_version: str = SCHEMA_VERSION
    source_label: str = SOURCE_LABEL
    sample_data: Literal[True] = True
    research_only: Literal[True] = True
    application_product_id: None = None
    executable_quote: Literal[False] = False
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(max_length=10000)
    category: str = Field(min_length=1, max_length=150)
    brand: str | None = None
    sku: str | None = None
    source_attributes: dict[str, Any]
    source_timestamps: dict[str, str] = Field(default_factory=dict)
    stock: int | None = Field(default=None, ge=0)
    minimum_order_quantity: int | None = Field(default=None, ge=1)
    policies: dict[str, str | None]
    return_window_days: int | None = None
    price_observation: dict[str, Any]
    discount_observation: dict[str, Any]
    reviews: list[dict[str, Any]] = Field(max_length=3)
    unknowns: list[str]


def decimal_text(value):
    if value is None:
        return None
    amount = Decimal(str(value))
    if not amount.is_finite() or amount < 0:
        raise ValueError("Invalid nonnegative decimal observation")
    return format(amount, "f")


def return_days(statement):
    match = re.fullmatch(r"\s*(\d{1,4})\s+days?\s+return\s+policy\s*", statement or "", re.I)
    return int(match.group(1)) if match else None


def normalize_product(raw, metadata):
    source_id = raw["id"]
    if isinstance(source_id, bool) or not isinstance(source_id, int) or source_id <= 0:
        raise ValueError("Source identity must be a positive integer")
    identifier = f"dummyjson:product:{source_id}"
    reviews = []
    for index, review in enumerate((raw.get("reviews") or [])[:3]):
        text = str(review.get("comment", ""))
        # Never retain reviewerName/reviewerEmail; comments remain sample opinions.
        reviews.append({"attribution": f"DummyJSON sample review {index + 1}", "comment": text[:600],
                        "rating": review.get("rating"), "date": review.get("date"),
                        "source_field": f"reviews.{index}", "truncated": len(text) > 600,
                        "interpretation": "attributed sample opinion, not verified product specification"})
    unknowns = ["currency", "currency_minor_unit_rounding", "tax", "shipping_fee", "delivery_date",
                "merchant_identity", "free_return_shipping", "price_history"]
    if raw.get("minimumOrderQuantity") is None:
        unknowns.append("minimum_order_quantity")
    if raw.get("dimensions"):
        unknowns.append("dimension_units")
    if raw.get("weight") is not None:
        unknowns.append("weight_units")
    if return_days(raw.get("returnPolicy")) is None:
        unknowns.append("return_window_days")
    product = ProductEvidence(
        product_id=identifier, id=identifier, source_id=source_id, source_version=sha(raw),
        snapshot_hash=metadata["sha256"], source_url=f"https://dummyjson.com/products/{source_id}",
        title=raw["title"], description=raw.get("description", ""), category=raw["category"],
        brand=raw.get("brand"), sku=raw.get("sku"), stock=raw.get("stock"),
        minimum_order_quantity=raw.get("minimumOrderQuantity"),
        source_attributes={key: raw[key] for key in ("tags", "weight", "dimensions", "rating", "availabilityStatus") if key in raw},
        source_timestamps={key: raw["meta"][key] for key in ("createdAt", "updatedAt")
                           if isinstance(raw.get("meta"), dict) and raw["meta"].get(key) is not None},
        policies={"return_policy": raw.get("returnPolicy"), "warranty": raw.get("warrantyInformation"),
                  "shipping": raw.get("shippingInformation")},
        return_window_days=return_days(raw.get("returnPolicy")),
        price_observation={"amount_decimal": decimal_text(raw.get("price")), "currency": None,
                           "minor_units": None, "observed_at": metadata["retrieved_at"], "source_field": "price"},
        discount_observation={"percent_decimal": decimal_text(raw.get("discountPercentage")),
                              "kind": "sample_catalog_discount", "source_field": "discountPercentage"},
        reviews=reviews, unknowns=unknowns,
    )
    return product.model_dump(mode="json")


def normalize_snapshot(snapshot, max_products=6):
    if not 1 <= max_products <= 24:
        raise ValueError("max_products must be between 1 and 24")
    available = sorted({p.get("category") for p in snapshot["products"] if isinstance(p.get("category"), str)})
    preferred = [name for name in ("laptops", "mobile-accessories", "tablets", "furniture", "home-decoration") if name in available]
    categories = (preferred + [x for x in available if x not in preferred])[:2]
    groups = [[p for p in snapshot["products"] if p.get("category") == category] for category in categories]
    for group in groups:
        group.sort(key=lambda p: p.get("id", 0))
    selected = []
    while any(groups) and len(selected) < max_products:
        for group in groups:
            if group and len(selected) < max_products:
                selected.append(group.pop(0))
    products, rejected, seen = [], [], set()
    for raw in selected:
        try:
            product = normalize_product(raw, snapshot["metadata"])
            if product["product_id"] in seen:
                raise ValueError("Duplicate source identity")
            seen.add(product["product_id"])
            products.append(product)
        except (ValueError, TypeError, KeyError, InvalidOperation) as exc:
            rejected.append({"source_id": raw.get("id"), "reason": type(exc).__name__})
    return {"products": products, "rejected": rejected, "categories": categories,
            "available_categories": available, "source_manifest": snapshot["metadata"]}


def product_document(product):
    """Concise source document for Senso/Cognee; no personal-looking review fields."""
    lines = [f"Source ID: {product['product_id']}", f"Source version: {product['source_version']}",
             f"Snapshot SHA-256: {product['snapshot_hash']}", f"Source URL: {product['source_url']}",
             f"Source: {SOURCE_LABEL}", "Attribution: DummyJSON / Muhammad Ovi (Owais), MIT license.",
             "This product is research-only and is NOT mapped to the app's Arc/Fold/Halo fixtures.",
             f"Title: {product['title']}", f"Category: {product['category']}",
             f"Description: {product['description']}"]
    for key in ("brand", "sku", "stock", "minimum_order_quantity"):
        lines.append(f"{key}: {product.get(key) if product.get(key) is not None else 'unknown'}")
    lines += [f"Source attributes (units not inferred): {canonical(product['source_attributes'])}",
              f"Single sample price observation: {canonical(product['price_observation'])}",
              f"Sample catalog discount, not a coupon: {canonical(product['discount_observation'])}"]
    lines += [f"{key}: {value if value is not None else 'unknown'}" for key, value in product["policies"].items()]
    lines += ["Return window does not establish free return shipping. Shipping wording does not establish delivery date or shipping cost.",
              "No return policy is ambiguous; no restriction or permission is inferred from that phrase.",
              "Unknown: " + ", ".join(product["unknowns"])]
    lines += [f"{review['attribution']} (opinion only): {review['comment']}" for review in product["reviews"]]
    return "\n".join(lines)


class ResearchClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    attribute: str
    value: str | int
    source_field: str
    source_id: str
    source_version: str


class ResearchFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str
    product_id: str
    agent_id: Literal["product-research-parser"]
    run_id: str
    execution_kind: Literal["deterministic_parser"]
    model_called: Literal[False]
    source_version: str
    claims: list[ResearchClaim]
    unknowns: list[str]
    source_ids: list[str]


def research_findings(products, run_id):
    records = []
    for product in products:
        claims = [{"attribute": key, "value": product[key], "source_field": key,
                   "source_id": product["product_id"], "source_version": product["source_version"]}
                  for key in ("title", "description", "category", "brand", "sku", "stock") if product.get(key) is not None]
        claims += [{"attribute": key, "value": value, "source_field": {"return_policy": "returnPolicy", "warranty": "warrantyInformation", "shipping": "shippingInformation"}[key],
                    "source_id": product["product_id"], "source_version": product["source_version"]}
                   for key, value in product["policies"].items() if value is not None]
        records.append(ResearchFinding.model_validate({"id": f"{run_id}:research:{product['source_id']}", "product_id": product["product_id"],
                        "agent_id": "product-research-parser", "run_id": run_id, "execution_kind": "deterministic_parser",
                        "model_called": False, "source_version": product["source_version"], "claims": claims,
                        "unknowns": product["unknowns"], "source_ids": [product["product_id"]]}).model_dump(mode="json"))
    return records


def synthetic_scenarios(products, findings, synthetic_owner, run_id):
    if not synthetic_owner or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", synthetic_owner):
        raise ValueError("An explicit simple synthetic owner is required")
    if not products:
        raise ValueError("Scenarios require grounded source products")
    known = {p["product_id"]: p for p in products}
    source_runs = {r["product_id"]: r["id"] for r in findings if r["product_id"] in known}
    # Each later specialist must consume an existing, source-grounded contribution.
    # An explicitly zero-sized research stage yields no invented collaboration.
    candidates = [product for product in products if product["product_id"] in source_runs]
    if not candidates:
        return []
    preferred = sorted(candidates, key=lambda p: (p["return_window_days"] is None, -(p["return_window_days"] or 0), p["source_id"]))
    records = []
    for index in range(3):
        persona = f"{synthetic_owner}:persona:{chr(65 + index)}"
        session = f"{run_id}:session:{chr(65 + index)}:previous"
        selected = [preferred[index % len(preferred)], preferred[(index + 1) % len(preferred)]]
        selected = list({p["product_id"]: p for p in selected}.values())
        ids = [p["product_id"] for p in selected]
        base = {"synthetic_demo": True, "owner": persona, "product_ids": ids, "source_ids": ids,
                "agent_id": "scenario-memory-parser", "run_id": run_id, "model_called": False,
                "execution_kind": "deterministic_fixture_builder", "read_contribution_ids": [source_runs[p] for p in ids]}
        earlier = f"{persona}:preference:earlier"
        durable = [
            {**base, "id": earlier, "type": "superseded_preference", "status": "superseded",
             "text": f"Synthetic user {persona} previously required a return window of at least 14 days. This requirement was superseded and is not current."},
            {**base, "id": f"{persona}:preference:current", "type": "confirmed_preference", "status": "confirmed",
             "requirement": {"kind": "minimum_return_window_days", "value": 30}, "supersedes": earlier,
             "text": f"Synthetic user {persona} confirmed a durable requirement in session {session}: require an explicitly stated return window of at least 30 days. This correction supersedes preference {earlier}. Free return shipping remains unknown."},
            {**base, "id": f"{persona}:intention:1", "type": "purchase_intention", "urgency": "flexible",
             "demo_budget": {"amount_decimal": str(200 + 100 * index), "currency": "USD", "source": "separate synthetic demo configuration"},
             "text": f"Synthetic intention {persona}:intention:1 considers research products {', '.join(ids)}. Urgency is flexible. Its separately configured demo budget is {200 + 100 * index} USD. Source catalog prices have unknown currency and are not executable quotes."},
            {**base, "id": f"{persona}:decision:wait", "type": "decision_episode", "decision": "Wait",
             "text": f"Synthetic intention {persona}:intention:1 recorded Wait because the purchase is flexible and executable merchant terms are missing. A later fixture event requests a recheck; this is a scheduled demonstration event, not a real policy, price, coupon or purchase change."},
        ]
        for product in selected:
            durable.append({**base, "id": f"{persona}:source:{product['source_id']}", "type": "sourced_product_reference",
                            "product_ids": [product["product_id"]], "source_ids": [product["product_id"]],
                            "text": f"For synthetic intention {persona}:intention:1, Product Research contribution {source_runs[product['product_id']]} records {product['product_id']} ({product['title']}) return policy: {product['policies']['return_policy'] or 'unknown'}. Source version {product['source_version']}. This is DummyJSON sample data, not verified merchant policy."})
        session_entries = [{**base, "id": f"{persona}:exception:session", "session_id": session, "scope": "session_only",
                            "expires_with_session": True, "type": "temporary_exception",
                            "text": f"In this synthetic session only ({session}), user {persona} permits comparison of products with unknown return windows. This exception does not change the durable 30-day return-window requirement and must not be applied in another session."}]
        records.append({"id": persona, "owner": persona, "synthetic_demo": True, "session_id": session,
                        "new_session_id": f"{run_id}:session:{chr(65 + index)}:fresh", "product_ids": ids,
                        "durable_records": durable, "session_entries": session_entries})
    return records
