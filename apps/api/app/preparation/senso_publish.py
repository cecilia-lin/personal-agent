"""Bounded, job-owned Senso publication and source-grounded policy parsing.

This module performs retrieval, not a separate Senso fact-check operation. It
never modifies/deletes existing sources and never retries an ambiguous upload.
"""
from datetime import datetime, timezone
import hashlib
import json
import re
import time
from typing import Callable, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.integrations.senso import BASE_URL


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class SensoJobError(RuntimeError):
    """Safe diagnostic text: no credentials or remote response bodies."""


class SourceDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=1, max_length=20000)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    schema_version: str = Field(min_length=1, max_length=80)
    source_version: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def check_digest(self):
        if hashlib.sha256(self.text.encode("utf-8")).hexdigest() != self.content_hash:
            raise ValueError("Document content_hash does not match the supplied text")
        if len(self.text.encode("utf-8")) > 40000:
            raise ValueError("Senso preparation document exceeds 40 KB")
        return self


class Passage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str
    content_id: str
    content_chunk_id: str
    version_id: str
    kb_node_id: str
    passage: str
    checked_at: str
    source_hash: str
    source_schema_version: str
    provider: Literal["senso"] = "senso"
    operation: Literal["context_retrieval"] = "context_retrieval"


class PolicyFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: str
    requirement: str
    state: Literal["supported", "contradicted", "unknown"]
    extracted_value: str | int | None
    source_field: str
    source_value: str | None
    sources: list[Passage]
    reason: str
    checked_at: str
    source_version: str
    run_id: str = Field(min_length=1)
    agent_id: Literal["offer-policy-parser"] = "offer-policy-parser"
    execution_kind: Literal["deterministic_parser"] = "deterministic_parser"
    synthetic_demo: Literal[True] = True


class SensoPublisher:
    def __init__(self, api_key: str, namespace: str, *, transport=None, timeout_seconds=20,
                 max_response_bytes=1_000_000, sleep=time.sleep, clock=time.monotonic):
        if not api_key or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", namespace):
            raise ValueError("Senso key and a simple job-owned namespace are required")
        self.namespace = namespace
        self.max_response_bytes = min(max(1, max_response_bytes), 2_000_000)
        self.sleep, self.clock = sleep, clock
        self.http = httpx.Client(base_url=BASE_URL, headers={"X-API-Key": api_key},
                                 timeout=httpx.Timeout(min(timeout_seconds, 30), connect=5),
                                 follow_redirects=False, transport=transport)

    def close(self):
        self.http.close()

    def _request(self, method, path, **kwargs):
        # Retry at most once for a read-only transient response; upload retries
        # are resolved through the persisted ledger, never automatic replay.
        for attempt in range(2 if method == "GET" else 1):
            try:
                with self.http.stream(method, path, **kwargs) as response:
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        data.extend(chunk)
                        if len(data) > self.max_response_bytes:
                            raise SensoJobError("Senso response exceeded the configured size limit")
                    status = response.status_code
                if method == "GET" and attempt == 0 and status in {429, 502, 503, 504}:
                    self.sleep(1)
                    continue
                try:
                    payload = json.loads(data)
                except (ValueError, UnicodeError):
                    raise SensoJobError(f"Senso returned invalid JSON (HTTP {status})") from None
                return status, payload
            except httpx.HTTPError as exc:
                raise SensoJobError(f"Senso request failed ({type(exc).__name__})") from None
        raise SensoJobError("Senso read retries exhausted")

    @staticmethod
    def _save(entry, checkpoint):
        entry["updated_at"] = timestamp()
        if checkpoint:
            checkpoint(dict(entry))
        return entry

    def publish(self, document: dict, ledger_entry: dict | None = None,
                checkpoint: Callable[[dict], None] | None = None) -> dict:
        doc = SourceDocument.model_validate(document)
        key = (doc.source_id, doc.content_hash, doc.schema_version)
        if ledger_entry:
            if tuple(ledger_entry.get(k) for k in ("source_id", "content_hash", "schema_version")) != key:
                raise ValueError("Ledger entry does not match document identity/hash/schema")
            if ledger_entry.get("namespace") != self.namespace:
                raise ValueError("Refusing a source from another job namespace")
            if doc.source_version and ledger_entry.get("source_version") != doc.source_version:
                raise ValueError("Ledger entry does not match the normalized source version")
            # Acceptance, timeout or process interruption may have produced a
            # source. A matching ledger entry is never posted again.
            return dict(ledger_entry)
        entry = {"source_id": doc.source_id, "content_hash": doc.content_hash,
                 "source_version": doc.source_version,
                 "schema_version": doc.schema_version, "namespace": self.namespace,
                 "title": f"{self.namespace} | {doc.title}", "status": "inflight",
                 "created_at": timestamp(), "content_id": None, "kb_node_id": None,
                 "version_id": None}
        self._save(entry, checkpoint)  # Durable before the external mutation.
        try:
            status, payload = self._request("POST", "/org/kb/raw", json={
                "title": entry["title"], "text": doc.text})
        except SensoJobError as exc:
            entry.update(status="ambiguous", error=str(exc),
                         next_action="Reconcile upload status before any retry; do not change text to avoid a duplicate.")
            return self._save(entry, checkpoint)
        if status == 409:
            entry.update(status="duplicate", error="Senso already has this exact content; it was not changed or reuploaded.")
            if isinstance(payload, dict) and payload.get("kb_node_id"):
                entry.update(content_id=payload.get("content_id") or payload.get("id"),
                             kb_node_id=payload["kb_node_id"], version_id=payload.get("latest_content_version_id"))
            return self._save(entry, checkpoint)
        if status not in {200, 201, 202} or not isinstance(payload, dict):
            entry.update(status="ambiguous" if status >= 500 else "failed", error=f"Senso upload returned HTTP {status}")
            return self._save(entry, checkpoint)
        entry.update(content_id=payload.get("id") or payload.get("content_id"), kb_node_id=payload.get("kb_node_id"),
                     version_id=payload.get("latest_content_version_id"), status="processing",
                     accepted_at=timestamp())
        if not entry["content_id"] or not entry["kb_node_id"]:
            entry.update(status="ambiguous", error="Senso accepted upload without both content and node identifiers")
        return self._save(entry, checkpoint)

    def wait_ready(self, entry: dict, *, max_wait_seconds=90, poll_seconds=5, checkpoint=None) -> dict:
        entry = dict(entry)
        if entry.get("namespace") != self.namespace:
            raise ValueError("Refusing a source from another job namespace")
        if not entry.get("kb_node_id") or not entry.get("content_id"):
            return entry
        deadline = self.clock() + min(max_wait_seconds, 180)
        while True:
            try:
                status, payload = self._request("GET", "/org/kb/nodes/" + entry["kb_node_id"])
            except SensoJobError as exc:
                entry.update(status="pending", error=str(exc))
                return self._save(entry, checkpoint)
            if status != 200 or not isinstance(payload, dict):
                entry.update(status="pending", error=f"Senso readiness returned HTTP {status}")
                return self._save(entry, checkpoint)
            if payload.get("content_id", entry["content_id"]) != entry["content_id"]:
                raise SensoJobError("Senso node identity changed from the source ledger")
            content = payload.get("content") or {}
            if not isinstance(content, dict):
                entry.update(status="pending", error="Senso readiness content was malformed")
                return self._save(entry, checkpoint)
            state = content.get("processing_status")
            if state == "complete":
                entry.update(status="ready", ready_at=timestamp())
                entry.pop("error", None)
                return self._save(entry, checkpoint)
            if state == "failed":
                entry.update(status="failed", error="Senso document processing failed")
                return self._save(entry, checkpoint)
            if self.clock() >= deadline:
                entry.update(status="pending", error="Senso document is not ready within the bounded wait")
                return self._save(entry, checkpoint)
            self.sleep(min(max(0.1, poll_seconds), 5, max(0, deadline - self.clock())))

    def retrieve(self, entry: dict, query: str, *, max_results=3) -> list[dict]:
        if (entry.get("namespace") != self.namespace or entry.get("status") != "ready"
                or not all(entry.get(k) for k in ("content_id", "kb_node_id", "version_id"))):
            raise SensoJobError("Only a ready, versioned source in this job's ledger may be queried")
        status, payload = self._request("POST", "/org/search/context", json={
            "query": query[:2000], "content_ids": [entry["content_id"]],
            "require_scoped_ids": True, "max_results": min(max(1, max_results), 5)})
        if status != 200 or not isinstance(payload, dict):
            raise SensoJobError(f"Senso retrieval returned HTTP {status}")
        results = payload.get("results", [])
        if not isinstance(results, list):
            raise SensoJobError("Senso retrieval results were malformed")
        passages = []
        for result in results[:10]:
            if not isinstance(result, dict) or result.get("content_id") != entry["content_id"]:
                continue
            if (not result.get("content_chunk_id") or not result.get("version_id")
                    or not isinstance(result.get("chunk_text"), str)):
                continue
            if entry.get("version_id") and result["version_id"] != entry["version_id"]:
                continue
            if result.get("kb_node_id", entry["kb_node_id"]) != entry["kb_node_id"]:
                continue
            passages.append(Passage(
                source_id=entry["source_id"], content_id=result["content_id"],
                content_chunk_id=result["content_chunk_id"], version_id=result["version_id"],
                kb_node_id=result.get("kb_node_id") or entry["kb_node_id"], passage=result["chunk_text"][:40000],
                checked_at=timestamp(), source_hash=entry["content_hash"],
                source_schema_version=entry["schema_version"],
            ).model_dump())
        return passages


def _normalized_text(text):
    return " ".join(text.casefold().split())


def _contains_statement(passage, statement):
    # A numeric/string substring is not an exact policy statement: e.g. a
    # "130 days" passage cannot support the source's "30 days" claim.
    pattern = r"(?<!\w)" + re.escape(_normalized_text(statement)) + r"(?!\w)"
    return re.search(pattern, _normalized_text(passage)) is not None


def policy_findings(product: dict, entry: dict, passages: list[dict], *, minimum_return_days=30,
                    run_id="offer-policy-parser") -> list[dict]:
    """Interpret exact, sourced sample policy fields; never infer fees/delivery."""
    product_id = product["product_id"]
    if entry["source_id"] != product_id:
        raise ValueError("Product and source ledger identity do not match")
    if entry.get("source_version") and entry["source_version"] != product["source_version"]:
        raise ValueError("Product and source ledger version do not match")
    approved = []
    for raw in passages:
        passage = Passage.model_validate(raw)
        if (passage.content_id != entry.get("content_id") or passage.source_id != product_id
                or passage.source_hash != entry["content_hash"]
                or passage.source_schema_version != entry["schema_version"]
                or passage.kb_node_id != entry.get("kb_node_id")
                or (entry.get("version_id") and passage.version_id != entry["version_id"])):
            raise ValueError("Policy citation is absent from the approved source ledger")
        approved.append(passage)
    policies = product.get("policies", {})
    output = []
    for field, requirement in (("return_policy", f"return_window_at_least_{minimum_return_days}_days"),
                               ("shipping", "recorded_shipping_statement"),
                               ("warranty", "recorded_warranty_statement")):
        value = policies.get(field)
        cited = [p for p in approved if isinstance(value, str) and value.strip()
                 and _contains_statement(p.passage, value)]
        extracted, state = None, "unknown"
        reason = "No approved, versioned passage contains the exact source policy statement."
        if cited:
            if field == "return_policy":
                match = re.fullmatch(r"(\d+)\s*(?:-|\s)\s*days?\s+return\s+policy", value.strip(), re.I)
                if match:
                    extracted = int(match[1])
                    state = "supported" if extracted >= minimum_return_days else "contradicted"
                    reason = f"The sample source explicitly states a {extracted}-day return window; return shipping costs remain unknown."
                else:
                    reason = "The source does not establish a numeric return window; 'No return policy' remains ambiguous."
            else:
                extracted, state = value, "supported"
                reason = ("Verbatim sample shipping/dispatch wording only; no delivery date or fee is established."
                          if field == "shipping" else "Verbatim sample warranty wording only; no additional coverage is inferred.")
        output.append(PolicyFinding(product_id=product_id, requirement=requirement, state=state,
                                    extracted_value=extracted, source_field="policies." + field, source_value=value,
                                    sources=cited, reason=reason, checked_at=timestamp(),
                                    source_version=product["source_version"], run_id=run_id).model_dump())
    return output
