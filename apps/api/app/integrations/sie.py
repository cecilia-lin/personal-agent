"""Optional live relevance scoring; financial constraints stay in application code."""
import math
import os

from sie_sdk import SIEClient
from sie_sdk.types import Item


class SIERanker:
    def __init__(self, client=None):
        key = os.getenv("SIE_API_KEY", "").strip() if os.getenv("INTEGRATIONS_ENABLED", "true").lower() != "false" else ""
        self.client = client or (SIEClient(
            api_key=key, base_url=os.getenv("SIE_BASE_URL", "https://api.superlinked.com"),
            timeout_s=30,
        ) if key else None)
        self.model = os.getenv("SIE_RERANK_MODEL", "Qwen/Qwen3-Reranker-0.6B")
        self.verified = False
        self.last_error = None

    def score(self, candidates, category, repairable):
        eligible = [candidate for candidate in candidates if candidate["eligible"]]
        if self.client is None or not eligible:
            return {"provider": "deterministic-demo", "provenance": "simulated",
                    "fallback_reason": "No ranking client configured." if self.client is None else "No eligible candidates."}
        query = f"Find a {'repairable ' if repairable else ''}{category} with useful product features."
        try:
            response = self.client.score(
                self.model, query=Item(text=query),
                items=[Item(id=p["id"], text=f"{p['name']}. {p['description']}") for p in eligible],
                wait_for_capacity=True, provision_timeout_s=45, max_oom_retries=0,
            )
            scores = {entry["item_id"]: float(entry["score"]) for entry in response["scores"]}
            if set(scores) != {p["id"] for p in eligible} or not all(math.isfinite(v) for v in scores.values()):
                raise ValueError("Incomplete or non-finite model scores")
            for candidate in eligible:
                candidate["relevance_score"] = scores[candidate["id"]]
            self.verified, self.last_error = True, None
            return {"provider": "superlinked-sie", "model": self.model, "provenance": "live"}
        except Exception as exc:
            self.last_error = f"SIE scoring failed ({type(exc).__name__}); using local price ordering."
            return {"provider": "deterministic-demo", "provenance": "simulated", "fallback_reason": self.last_error}

    def close(self):
        if self.client is not None:
            self.client.close()

    def status(self):
        return {
            "name": "Superlinked SIE",
            "status": "error" if self.last_error else "healthy" if self.verified else "configured" if self.client else "not_configured",
            "verified": self.verified,
            "detail": self.last_error or (
                f"Catalog relevance scoring uses {self.model}; budget and approval checks remain local."
                if self.client else "Set SIE_API_KEY in .env and restart for live relevance scoring."
            ),
        }
