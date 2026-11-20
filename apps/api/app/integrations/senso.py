"""Retrieve product evidence from Senso's runtime API without exporting shopper data."""
import os
import hashlib
import json
from pathlib import Path
import re
import time

import httpx

from app.domain.models import now
from app.integrations.contracts import FixtureEvidenceProvider

BASE_URL = "https://apiv2.senso.ai/api/v1"


def repairability_claim(product: dict) -> dict:
    """Identify one asserted catalog fact, without treating it as verified evidence."""
    known = {
        "arc-light": ("Adjustable arm, replaceable bulb, and a two-year fixture warranty.",
                      "replaceable_bulb", "has a replaceable bulb"),
        "fold-light": ("Compact metal task light with a replaceable light module.",
                       "replaceable_light_module", "has a replaceable light module"),
        "halo-light": ("Wide studio illumination with serviceable components.",
                       "serviceable_components", "has serviceable components"),
    }
    requested = product.get("_required_feature")
    explicit = {"replaceable_bulb": "a replaceable bulb", "replaceable_light_module": "a replaceable light module",
                "serviceable_components": "serviceable components"}
    if requested in explicit and product.get("id") in {*known, "mini-light"}:
        return {"feature": requested, "claim": f"{product['name']} has {explicit[requested]}."}
    expected = known.get(product.get("id"))
    if not expected or product.get("description", "").strip() != expected[0]:
        return {"feature": None, "claim": None}
    return {"feature": expected[1], "claim": f"{product['name']} {expected[2]}."}


class SensoEvidenceProvider:
    requires_context = True

    def __init__(self, api_key: str, transport=None, *, ledger_path=None, ledger=None,
                 max_wait_seconds=20, sleep=time.sleep, clock=time.monotonic):
        self.http = httpx.Client(
            base_url=BASE_URL, headers={"X-API-Key": api_key},
            timeout=httpx.Timeout(15, connect=5), transport=transport,
        )
        self.connected = False
        self.last_error = None
        self.retrieval_verified = False
        self.retrieval_error = False
        self.ledger_path = Path(ledger_path or Path(__file__).resolve().parents[4] / ".local/senso-corpus-ledger.json")
        self._ledger = ledger
        self.max_wait_seconds = min(max(0, max_wait_seconds), 60)
        self.sleep, self.clock = sleep, clock
        self.fact_check_available = False
        self.fact_check_verified = False

    def _source(self, product):
        ledger = self._ledger
        if ledger is None:
            if not self.ledger_path.exists() or self.ledger_path.stat().st_size > 1_000_000:
                return None
            ledger = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        if ledger.get("schema_version") != "intent-senso-corpus-v1":
            return None
        source = ledger.get("products", {}).get(product["id"])
        if not source or source.get("status") != "ready" or not all(source.get(k) for k in
                ("content_id", "kb_node_id", "version_id", "content_hash")):
            return None
        return source

    def _body(self, source):
        response = self.http.get("/org/kb/nodes/" + source["kb_node_id"] + "/content")
        response.raise_for_status()
        body = response.json()
        if (body.get("id") != source["content_id"] or body.get("processing_status") != "complete"
                or not isinstance(body.get("text"), str) or not isinstance(body.get("version_num"), int)
                or hashlib.sha256(body["text"].encode()).hexdigest() != source["content_hash"]):
            raise ValueError("Approved source body/version no longer matches the corpus ledger")
        return body

    def check_connection(self):
        try:
            response = self.http.get("/org/me")
            response.raise_for_status()
            self.connected = bool(response.json().get("org_id"))
            self.last_error = None if self.connected else "Senso did not return an organization."
        except (httpx.HTTPError, ValueError, AttributeError) as exc:
            self.last_error = f"Senso connection failed ({type(exc).__name__})."

    def for_product(self, product: dict) -> list[dict]:
        # Only the catalog identity leaves the app, never goals, budgets or account data.
        query = f"Product {product['id']}: {product['name']}. Product details and policies."
        self.retrieval_error = False
        try:
            source = self._source(product)
            if not source:
                self.last_error = "The approved product source is missing or not ready; claim verification is blocked."
                return []
            body = self._body(source)
            response = self.http.post("/org/search/context", json={"query": query, "max_results": 3,
                "content_ids": [source["content_id"]], "require_scoped_ids": True})
            response.raise_for_status()
            payload = response.json()
            passages = []
            for result in payload.get("results", []):
                if not isinstance(result, dict):
                    continue
                if result.get("content_id") != source["content_id"] or result.get("version_id") != source["version_id"]:
                    continue
                excerpt = result.get("chunk_text")
                if not isinstance(excerpt, str) or not result.get("content_id"):
                    continue
                searchable = (str(result.get("title", "")) + " " + excerpt).casefold()
                if product["name"].casefold() not in searchable and product["id"].casefold() not in searchable:
                    continue
                passages.append({
                    **{key: result.get(key) for key in (
                        "content_id", "kb_node_id", "version_id", "chunk_text", "score", "rank",
                        "retrieval", "content_chunk_id", "title", "inclusion_reason",
                    )},
                    "search_type": payload.get("search_type"), "source_id": result["content_id"],
                    "source_version": result.get("version_id"), "excerpt": excerpt,
                    "observed_at": now(), "provider": "senso", "provenance": "live",
                    "source_body_hash": source["content_hash"], "source_version_num": body["version_num"],
                })
            self.retrieval_verified = True
            self.last_error = None if passages else "Senso returned no supporting passage for this product."
            return passages
        except (httpx.HTTPError, ValueError, AttributeError, TypeError) as exc:
            self.retrieval_error = True
            self.last_error = f"Senso retrieval failed ({type(exc).__name__}); no live evidence is available."
            return []

    def close(self):
        self.http.close()

    def verify_product(self, product: dict, passages: list[dict]) -> dict:
        claim = repairability_claim(product)
        return self.verify_claim(product, claim["claim"], claim["feature"], passages)

    def verify_claim(self, product: dict, claim: str | None, feature: str | None, passages=None) -> dict:
        """Real kb_accuracy evaluation, bound to an approved unchanged source body.

        Evals search the whole organization. There is no documented content_ids
        eval option: citations outside the product ledger never authorize a cart.
        """
        if passages is None:
            passages = self.for_product(product)
        result = {
            "claim": claim, "feature": feature, "requirement": "repairability", "provider": "senso",
            "state": "error" if self.retrieval_error else "not_verifiable",
            "reason": "Senso retrieval is unavailable; no required claim can be verified." if self.retrieval_error else
                      "This product has no precise required claim or approved versioned specification; the required capability is unresolved.",
            "check_id": None, "sources": [], "retrieved_sources": passages,
            "checked_at": None, "provenance": "unverified",
            "fact_check_verified": False,
        }
        if not claim or not feature or self.retrieval_error:
            return result
        try:
            source = self._source(product)
            approved = [p for p in passages if source and p.get("content_id") == source["content_id"]
                        and p.get("version_id") == source["version_id"]]
            if not source or not approved:
                return result
            before = self._body(source)
            question = f"For product {product['id']} ({product['name']}), evaluate this capability against its product-specific document '{source.get('title', '')}'."
            identity = json.dumps([product["id"], claim, feature, source["content_id"], source["version_id"],
                                   source["content_hash"], before["version_num"], question], sort_keys=True)
            response = self.http.post("/org/evals/text", json={"text": claim, "question": question,
                "evaluator": "kb_accuracy", "wait": False, "label": "intent-required-claim-" + product["id"],
                "idempotency_key": "intent-claim-" + hashlib.sha256(identity.encode()).hexdigest()})
            response.raise_for_status()
            run = response.json()
            result["check_id"] = run.get("eval_run_id")
            if run.get("status") == "completed" and ("subject" not in run or "claims" not in run):
                response = self.http.get("/org/evals/runs/" + run["eval_run_id"])
                response.raise_for_status()
                run = response.json()
            deadline = self.clock() + self.max_wait_seconds
            while run.get("status") in {"queued", "running"} and self.clock() < deadline:
                self.sleep(min(2, max(0, deadline - self.clock())))
                response = self.http.get("/org/evals/runs/" + run["eval_run_id"])
                response.raise_for_status()
                run = response.json()
            self.fact_check_available = True
            result.update(check_id=run.get("eval_run_id"), checked_at=run.get("finished_at") or now(),
                          evaluator_version=run.get("evaluator_version"), evaluation_status=run.get("status"))
            if run.get("status") != "completed":
                result.update(state="error" if run.get("status") == "failed" else "not_verifiable" if run.get("status") == "gated" else "pending",
                              reason="Senso required-claim evaluation is " + str(run.get("status", "unresolved")) + "; a proposal is blocked.")
                return result
            if run.get("evaluator_key") != "kb_accuracy" or run.get("subject", {}).get("text") != claim:
                raise ValueError("Evaluation identity did not match the requested claim")
            claims = run.get("claims") or []
            if len(claims) != 1 or not isinstance(claims[0], dict):
                result["reason"] = "Senso did not return one unambiguous required-claim verdict."
                return result
            checked = claims[0]
            normalize_claim = lambda value: re.sub(r"\s+", " ", str(value or "")).strip().rstrip(".?!").casefold()
            if normalize_claim(checked.get("source_text")) != normalize_claim(claim):
                result["reason"] = "The extracted Senso claim does not match the exact required product capability."
                return result
            result.update(verdict=checked.get("verdict"), eval_claim_id=checked.get("eval_claim_id"),
                          quote=checked.get("quote"), grounding_failed=checked.get("grounding_failed"),
                          reasoning=checked.get("reasoning"), confidence=checked.get("confidence"))
            after = self._body(source)
            if after["version_num"] != before["version_num"]:
                raise ValueError("Source version changed during evaluation")
            current_source = self._source(product)
            if not current_source or any(current_source.get(key) != source.get(key) for key in
                                         ("content_id", "kb_node_id", "version_id", "content_hash")):
                raise ValueError("Approved source ledger changed during evaluation")
            result.update(version_binding="scoped_context_uuid_and_unchanged_body_before_after_evaluation",
                          source_body_hash=source["content_hash"], source_version_num=after["version_num"])
            evidence = checked.get("evidence") or []
            if any(e.get("content_id") == source["content_id"] and e.get("content_version_id") not in {None, source["version_id"]}
                   for e in evidence):
                result["reason"] = "Senso cited an unapproved product source or different version; the required claim remains unresolved."
                return result
            ignored = [e for e in evidence if e.get("content_id") != source["content_id"]]
            result["ignored_evidence"] = ignored
            if checked.get("verdict") == "verified" and any(e.get("relation") == "contradicts" for e in ignored):
                result["reason"] = "Senso returned conflicting evidence outside the approved source; the required claim remains unresolved."
                return result
            evidence = [e for e in evidence if e.get("content_id") == source["content_id"]]
            sources = []
            for evidence_item in evidence:
                chunks = [c for c in run.get("evidence_chunks", []) if c.get("content_id") == source["content_id"]
                          and c.get("chunk_index") == evidence_item.get("chunk_index")]
                quote = checked.get("quote")
                excerpt = quote if isinstance(quote, str) and quote else next((c.get("text") for c in chunks if c.get("text")), None)
                if checked.get("verdict") != "verified" and (not isinstance(excerpt, str) or excerpt not in before["text"]):
                    excerpt = next((p.get("excerpt") for p in approved if p.get("excerpt") and p["excerpt"] in before["text"]), None)
                if not isinstance(excerpt, str) or excerpt not in before["text"]:
                    continue
                matched = next((p for p in approved if excerpt in (p.get("excerpt") or "")), {})
                sources.append({"content_id": source["content_id"], "source_id": source["content_id"],
                    "version_id": source["version_id"], "source_version": source["version_id"],
                    "kb_node_id": source["kb_node_id"], "content_chunk_id": matched.get("content_chunk_id"),
                    "eval_chunk_index": evidence_item.get("chunk_index"), "relation": evidence_item.get("relation"),
                    "evaluator_content_version_id": evidence_item.get("content_version_id"),
                    "source_body_hash": source["content_hash"], "source_version_num": after["version_num"],
                    "excerpt": excerpt, "chunk_text": excerpt, "observed_at": now(), "provider": "senso", "provenance": "live"})
            verdict = checked.get("verdict")
            result.update(sources=sources, provenance="live", fact_check_verified=True)
            self.fact_check_verified = True
            if checked.get("grounding_failed") or (verdict == "verified" and
                    (not sources or not any(s.get("relation") == "entails" for s in sources)
                     or not checked.get("quote") or checked.get("passed") is not True)):
                result.update(state="unsupported", reason="Senso's support could not be grounded in the approved unchanged product source.")
            else:
                state = {"verified": "supported", "conflict": "conflict", "unsupported": "unsupported", "not_verifiable": "not_verifiable"}.get(verdict, "not_verifiable")
                result.update(state=state, reason=checked.get("reasoning") or f"Senso required claim is {state}.")
            self.last_error = None
            return result
        except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError) as exc:
            result.update(state="error", reason=f"Senso required-claim check failed ({type(exc).__name__}); no proposal is allowed.")
            self.last_error = result["reason"]
            return result

    def status(self):
        return {
            "name": "Senso", "status": "error" if self.last_error else "healthy" if self.connected else "configured",
            "detail": self.last_error or "Scoped product retrieval and documented kb_accuracy fact-checking are enabled; product source versions are checked before and after evaluation.",
            "verified": self.connected,
            "retrieval_verified": self.retrieval_verified,
            "fact_check_verified": self.fact_check_verified,
            "fact_check_available": self.fact_check_available,
        }


def evidence_provider():
    if os.getenv("INTEGRATIONS_ENABLED", "true").lower() == "false" or os.getenv("EVIDENCE_PROVIDER") in {"fixture", "offline"}:
        return FixtureEvidenceProvider()
    key = os.getenv("SENSO_API_KEY", "").strip()
    return SensoEvidenceProvider(key)
