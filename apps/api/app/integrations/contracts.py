"""Provider boundaries. Unimplemented capabilities must fail explicitly."""
from typing import Protocol, Any

class ModelClient(Protocol):
    provider: str
    def classify_request(self, goal: str) -> dict: ...
    def retrieve_candidates(self, products: list[dict], category: str) -> list[dict]: ...
    def rerank_candidates(self, products: list[dict], repairable: bool) -> list[dict]: ...
    def plan_task(self, goal: str) -> list[str]: ...
    def read_document(self, document: bytes) -> str: ...
    def extract_fields(self, text: str, schema: dict) -> dict: ...

class EvidenceProvider(Protocol):
    def for_product(self, product: dict) -> list[dict]: ...

class PreferenceMemory(Protocol):
    def remember(self, user_id: str, preference: dict) -> None: ...
    def recall(self, user_id: str, query: str) -> list[dict]: ...

class AnalyticsSink(Protocol):
    def track(self, event: str, metadata: dict[str, Any]) -> None: ...

class RoutingProvider(Protocol):
    def choose(self, user_id: str) -> dict: ...

class BackgroundCoordinator(Protocol):
    def scan(self, user_id: str, limit: int = 5) -> dict: ...

class DemoModelClient:
    provider = "deterministic-demo"
    def classify_request(self, goal):
        return {"skill": "shopping", "provenance": "simulated", "supported_scope": "selected catalog category"}
    def retrieve_candidates(self, products, category):
        return [p for p in products if p["category"] == category]
    def rerank_candidates(self, products, repairable):
        from app.domain.models import total
        return sorted(products, key=lambda p: (
            repairable and not p["repairable"],
            total(p) if total(p) is not None else 10**12, p["id"],
        ))
    def plan_task(self, goal):
        return ["load_context", "calculate_allowance", "retrieve_candidates", "check_constraints", "request_review"]
    def read_document(self, document):
        raise NotImplementedError("Document OCR is not implemented in the demo.")
    def extract_fields(self, text, schema):
        raise NotImplementedError("Field extraction is not implemented in the demo.")

class FixtureEvidenceProvider:
    def for_product(self, product):
        return [{
            "source_id": product["source_id"], "source_version": product["source_version"],
            "observed_at": product["observed_at"], "provenance": product["provenance"],
            "excerpt": product["description"],
        }]

class LocalRouting:
    def __init__(self, policy):
        self.policy = policy
    def choose(self, user_id):
        from app.integrations.statsig_client import choose_reranker
        return choose_reranker(user_id)
