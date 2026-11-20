"""Read-only synthetic research comparison; never produces an executable offer."""
import os

from app.integrations.prepared_memory import PreparedMemoryError, PreparedPreferenceMemory
from app.preparation.senso_publish import SensoPublisher, policy_findings


def get_research_memory(outputpath, persona_key="A", *, memory=None, publisher=None):
    result = {"state": "pending", "reason": "Prepared research memory is not available yet.",
              "synthetic_demo": True, "research_only": True, "proposal_allowed": False,
              "persona_id": None, "session_id": None, "requirement": None, "candidates": []}
    own_publisher = publisher is None
    try:
        memory = memory or PreparedPreferenceMemory(outputpath, persona_key)
        result["persona_id"] = memory.user_id
        recalls = memory.recall(memory.user_id, "Recall the current confirmed shopping requirement.")
        result["session_id"] = memory.session_id
        if len(recalls) != 1:
            raise PreparedMemoryError("The current confirmed requirement could not be resolved.", state="pending")
        result["requirement"] = recalls[0]
        products = memory.artifacts["normalized.json"]["products"]
        if (not products or len(products) > 24 or any(not p.get("research_only") or p.get("executable_quote")
                or p.get("application_product_id") is not None for p in products)):
            raise PreparedMemoryError("The prepared products are not isolated research records.")
        positive = next((p for p in products if (p.get("return_window_days") or 0) >= 30), None)
        negative = next((p for p in products if p.get("return_window_days") == 7), None)
        negative = negative or next((p for p in products if p.get("return_window_days") is not None and p["return_window_days"] < 30), None)
        selected = [p for p in (positive, negative) if p]
        if not selected:
            selected = products[:2]
        if publisher is None:
            if not os.getenv("SENSO_API_KEY"):
                raise PreparedMemoryError("Senso is not configured for a fresh evidence check.", state="pending")
            publisher = SensoPublisher(os.environ["SENSO_API_KEY"], memory.manifest["job_id"])
        documents = {d["source_id"]: d for d in memory.artifacts["documents.json"]}
        pending = False
        for product in selected:
            candidate = {"product_id": product["product_id"], "title": product["title"],
                         "return_policy": product["policies"].get("return_policy"),
                         "requirement_state": "unknown", "policy_eligible": False, "decision": "Wait",
                         "proposal_allowed": False, "research_only": True, "passages": []}
            try:
                document = documents[product["product_id"]]
                entries = [e for e in memory.manifest["senso_ledger"].values()
                           if e.get("source_id") == product["product_id"]
                           and e.get("content_hash") == document["content_hash"]
                           and e.get("schema_version") == document["schema_version"]
                           and e.get("source_version") == product["source_version"]
                           and e.get("namespace") == memory.manifest["job_id"]]
                if len(entries) != 1:
                    raise PreparedMemoryError("A unique matching Senso source version is unavailable.", state="pending")
                entry = publisher.wait_ready(entries[0], max_wait_seconds=0)
                if entry.get("status") != "ready":
                    raise PreparedMemoryError("The Senso source is not ready for a fresh check.", state="pending")
                passages = publisher.retrieve(entry, f"What is the exact return policy statement for {product['title']}?")
                finding = policy_findings(product, entry, passages, minimum_return_days=recalls[0]["value"],
                                          run_id=memory.session_id)[0]
                candidate.update(requirement_state=finding["state"], policy_eligible=finding["state"] == "supported",
                                 passages=finding["sources"], reason=finding["reason"] +
                                 " Wait: this research product has no executable merchant quote or application product mapping.")
            except Exception:
                pending = True
                candidate["reason"] = "Fresh Senso evidence is unavailable or does not match the prepared source version. Wait; no proposal is allowed."
            result["candidates"].append(candidate)
        result.update(state="pending" if pending else "ready",
                      reason=("Some fresh evidence checks are unresolved; every product remains research-only."
                              if pending else "The remembered requirement was applied to fresh sample evidence. Purchase remains Wait because executable merchant terms are unavailable."))
    except PreparedMemoryError as exc:
        result.update(state=exc.state, reason=str(exc))
    except Exception:
        result.update(state="blocked", reason="Prepared memory could not be validated. No proposal is allowed.")
    finally:
        if own_publisher and publisher is not None:
            publisher.close()
    return result
