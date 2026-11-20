"""Retrieve product evidence from Senso's runtime API without exporting shopper data."""
import os

import httpx

from app.domain.models import now
from app.integrations.contracts import FixtureEvidenceProvider

BASE_URL = "https://apiv2.senso.ai/api/v1"


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
            self.last_error = f"Senso retrieval failed ({type(exc).__name__}); no live evidence is available."
            return []

    def close(self):
        self.http.close()

    def status(self):
        return {
            "name": "Senso", "status": "error" if self.last_error else "healthy" if self.connected else "configured",
            "detail": self.last_error or "Runtime context retrieval enabled; source and version identifiers are retained in the audit trail.",
            "verified": self.connected,
            "retrieval_verified": self.retrieval_verified,
        }


def evidence_provider():
    if os.getenv("INTEGRATIONS_ENABLED", "true").lower() == "false" or os.getenv("EVIDENCE_PROVIDER") == "fixture":
        return FixtureEvidenceProvider()
    key = os.getenv("SENSO_API_KEY", "").strip()
    return SensoEvidenceProvider(key) if key else FixtureEvidenceProvider()
