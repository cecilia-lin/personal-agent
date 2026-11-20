"""Stable server-side bindings for product claims and versioned evidence."""
import hashlib
import json


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def product_fingerprint(product):
    return fingerprint({k: product.get(k) for k in (
        "id", "version", "name", "description", "repairable", "source_id", "source_version")})


def evidence_fingerprint(passages):
    records = []
    for passage in passages:
        if passage.get("source_body_hash") and passage.get("source_version_num") is not None:
            # A fresh evaluation may quote another passage from the identical
            # approved document. Bind approvals to the body/version, not wording
            # selected by the evaluator or its new run identifier.
            record = {k: passage.get(k) for k in ("content_id", "version_id", "source_body_hash", "source_version_num")}
        else:
            record = {k: passage.get(k) for k in ("content_id", "source_id", "version_id", "source_version",
                                                  "content_chunk_id", "excerpt", "chunk_text")}
        if record not in records:
            records.append(record)
    return fingerprint(sorted(records, key=lambda p: json.dumps(p, sort_keys=True)))


def allowed(verification, live):
    if verification.get("state") == "not_required":
        return True
    if not live:
        return verification.get("state") == "demo"
    sources = verification.get("sources") or []
    return bool(verification.get("state") == "supported" and verification.get("check_id")
                and verification.get("claim") and verification.get("feature") and sources
                and all((p.get("content_id") or p.get("source_id"))
                        and (p.get("version_id") or p.get("source_version"))
                        and (p.get("excerpt") or p.get("chunk_text")) for p in sources))
