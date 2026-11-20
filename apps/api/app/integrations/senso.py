"""Retrieve product evidence from Senso's runtime API without exporting shopper data."""
import os

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
    expected = known.get(product.get("id"))
    if not expected or product.get("description", "").strip() != expected[0]:
        return {"feature": None, "claim": None}
    return {"feature": expected[1], "claim": f"{product['name']} {expected[2]}."}


class SensoEvidenceProvider:
    requires_context = True

    def __init__(self, api_key: str, transport=None):
        self.http = httpx.Client(
            base_url=BASE_URL, headers={"X-API-Key": api_key},
            timeout=httpx.Timeout(15, connect=5), transport=transport,
        )
        self.connected = False
        self.last_error = None
        self.retrieval_verified = False
        self.retrieval_error = False

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
            response = self.http.post("/org/search/context", json={"query": query, "max_results": 3})
            response.raise_for_status()
            payload = response.json()
            passages = []
            for result in payload.get("results", []):
                if not isinstance(result, dict):
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
        """Fail closed until a real fact-check contract and response are verified.

        Retrieval is usable independently, but does not establish a claim verdict.
        No guessed fact-check endpoint or local keyword match may authorize a cart.
        """
        claim = repairability_claim(product)
        return {
            **claim, "requirement": "repairability", "provider": "senso",
            "state": "error" if self.retrieval_error else "not_verifiable",
            "reason": (
                "Senso retrieval is unavailable; no required claim can be verified. Check the service and retry."
                if self.retrieval_error else
                "Product information was retrieved, but Senso fact-check access has not been verified. "
                "The required claim is unresolved; a live purchase proposal is blocked."
                if claim["claim"] and passages else
                "Senso fact-check access has not been verified and no product information was retrieved. "
                "The required claim is unresolved; a live purchase proposal is blocked."
                if claim["claim"] else
                "No precise replaceable-bulb, replaceable-module, or serviceable-component claim "
                "is defined for this catalog description. A repairable flag alone is insufficient."
            ),
            "check_id": None, "sources": [], "retrieved_sources": passages,
            "checked_at": None, "provenance": "unverified",
            "fact_check_verified": False,
        }

    def status(self):
        return {
            "name": "Senso", "status": "error" if self.last_error else "healthy" if self.connected else "configured",
            "detail": self.last_error or "Product information retrieval enabled; source and version identifiers are retained. Required claim fact-checking is not connected.",
            "verified": self.connected,
            "retrieval_verified": self.retrieval_verified,
            "fact_check_verified": False,
            "fact_check_available": False,
        }


def evidence_provider():
    if os.getenv("INTEGRATIONS_ENABLED", "true").lower() == "false" or os.getenv("EVIDENCE_PROVIDER") == "fixture":
        return FixtureEvidenceProvider()
    key = os.getenv("SENSO_API_KEY", "").strip()
    return SensoEvidenceProvider(key) if key else FixtureEvidenceProvider()
