"""Intent's explicit decision rules and durable price watches. No price forecasts."""
from datetime import datetime, timedelta
from app.domain.models import Problem, now
from app.services.skills import ShoppingSkill

class Intent:
    def __init__(self, agent):
        self.agent, self.store = agent, agent.store

    def decide(self, task, candidates):
        eligible = [c for c in candidates if c["eligible"]]
        if not eligible:
            unresolved = next((c for c in candidates if c.get("verification", {}).get("state") in
                               {"conflict", "unsupported", "not_verifiable", "pending", "error"}), None)
            detail = (" Required claim unresolved for " + unresolved["name"] + ": " + unresolved["verification"].get("reason", "check pending")) if unresolved else ""
            return {"decision": "Skip", "reason": "No complete quote meets the current constraints." + detail,
                    "prediction": None, "basis": "current verified constraints"}
        best = min(eligible, key=lambda c: c["total_minor"])
        target, urgency = task.get("target_price_minor"), task.get("urgency", "soon")
        if target is not None and best["total_minor"] > target:
            return {"decision": "Wait", "reason": "The current complete quote is above your target. Save a watch to recheck actual quotes.",
                    "product_id": best["id"], "total_minor": best["total_minor"], "prediction": None,
                    "basis": "current quote versus your target"}
        if urgency == "flexible" and target is None:
            return {"decision": "Wait", "reason": "You marked this purchase as flexible. A watch can record later observations; it does not predict a lower price.",
                    "product_id": best["id"], "total_minor": best["total_minor"], "prediction": None,
                    "basis": "your stated urgency"}
        return {"decision": "Buy", "reason": "A complete quote fits your current constraints" + (" and target." if target is not None else ".") + " Purchase urgency: " + urgency + ". Your approval is still required.",
                "product_id": best["id"], "total_minor": best["total_minor"], "prediction": None,
                "basis": "current constraints, target, and urgency"}

    def seed_history(self, unit):
        stamp = datetime.fromisoformat(now())
        for product in unit.all("products"):
            for offset, increase in ((28, 1500), (14, 700), (7, 200), (0, 0)):
                record_id = "price_" + product["id"] + "_" + str(offset)
                if unit.get("price_history", record_id, False):
                    continue
                unit.save("price_history", record_id, {
                    "product_id": product["id"], "price_minor": product["price_minor"] + increase,
                    "observed_at": (stamp-timedelta(days=offset)).isoformat(), "currency": "USD",
                    "price_basis": "item price before tax, shipping, and promotions", "provenance": "fixture",
                    "source_id": "fixture:sample-price-history:v1",
                })

    def history(self, unit, product_id):
        return sorted([r for r in unit.all("price_history") if r["product_id"] == product_id], key=lambda r: r["observed_at"])

    def save_watch(self, user_id, task_id, product_id=None):
        self.agent.require_demo()
        with self.store.transaction(user_id, write=True) as unit:
            task = unit.get("tasks", task_id)
            decision = task["checkpoint"].get("recommendation", {})
            if decision.get("decision") not in {"Buy", "Wait"}:
                raise Problem("Run a task with an eligible quote before saving a watch.")
            record_id = "watch_" + task_id.removeprefix("task_")
            old = unit.get("watch_items", record_id, False)
            if old and old["status"] == "active":
                return old
            chosen = product_id or decision["product_id"]
            if chosen not in {c["id"] for c in task["checkpoint"]["candidates"] if c["eligible"]}:
                raise Problem("Only an eligible product from this task can be watched.")
            product = unit.get("products", chosen)
            decision = self.decide(task, [c for c in task["checkpoint"]["candidates"] if c["id"] == chosen])
            watch = unit.save("watch_items", record_id, {
                "task_id": task_id, "product_id": chosen, "product_name": product["name"],
                "target_price_minor": task.get("target_price_minor"), "urgency": task.get("urgency", "soon"),
                "max_price_minor": task["max_price_minor"], "status": "active", "created_at": now(),
                "last_checked_at": None, "next_check": now(), "recommendation": decision,
                "last_versions": None, "provenance": "simulated",
            }, old["version"] if old else None)
            self.agent.event(unit, task, "watch_saved", {"watch_id": record_id, "product_id": chosen, "decision": decision})
            return watch

    def check_watches(self, unit, run_id, limit, prepared_evidence):
        checked, created = 0, []
        for watch in unit.all("watch_items"):
            if checked >= limit:
                break
            if watch["status"] != "active":
                continue
            product = unit.get("products", watch["product_id"])
            evidence = prepared_evidence.get(product["id"])
            if evidence is None:
                continue  # A watch added during retrieval is checked on the next bounded scan.
            ctx = self.agent.context(unit)
            quote = self.agent.merchant.quote(unit, product)
            versions = {"product": product["version"], "budget": ctx["context_versions"],
                        "quote": quote.get("quote_digest"),
                        "evidence": evidence["verification"].get("evidence_fingerprint"),
                        "support": evidence["verification"].get("support_fingerprint"),
                        "verification_state": evidence["verification"]["state"]}
            if watch["last_versions"] == versions and watch["next_check"] > now():
                continue
            task = unit.get("tasks", watch["task_id"])
            checks = ShoppingSkill.evaluate(product, ctx, watch["max_price_minor"], quote=quote)
            candidate = {**product, **checks, "quote": quote, "price_history": self.history(unit, product["id"]),
                         **evidence}
            self.agent.apply_evidence(candidate, evidence)
            stale = self.agent.claim_reason(product, evidence["verification"], ctx["preferences"]["repairable"])
            if stale:
                candidate["eligible"] = candidate["proposal_allowed"] = False
                candidate["reasons"].append(stale)
            decision = self.agent.proposal_flags(watch, [candidate])
            next_payload = {**watch, "last_checked_at": now(), "last_versions": versions,
                "next_check": (datetime.fromisoformat(now())+timedelta(hours=1)).isoformat(),
                "recommendation": decision, "verification": candidate["verification"], "run_id": run_id}
            unit.save("watch_items", watch["id"], next_payload, watch["version"])
            if task["status"] not in {"completed", "rejected", "approved", "awaiting_approval"}:
                unit.save("tasks", task["id"], {**task, "status": "awaiting_selection" if candidate["eligible"] else "failed",
                    "checkpoint": {**task["checkpoint"], "candidates": [candidate], "recommendation": decision},
                    "error": None if candidate["eligible"] else "Current watch constraints are not met.",
                    "updated_at": now()}, task["version"])
            if decision["decision"] != watch["recommendation"]["decision"] or watch["last_checked_at"] is None:
                next_id = "next_" + watch["id"]
                created.append(next_id)
                old = unit.get("next_actions", next_id, False)
                unit.save("next_actions", next_id, {"title": decision["decision"] + ": " + watch["product_name"],
                    "task_id": task["id"], "watch_id": watch["id"], "due_at": now(), "status": "open",
                    "source_id": product["source_id"], "updated_at": now(), "run_id": run_id,
                    "reason": decision["reason"], "provenance": "simulated"}, old["version"] if old else None)
            self.agent.event(unit, {**task, "run_id": run_id}, "watch_checked", {
                "watch_id": watch["id"], "recommendation": decision, "quote_digest": quote.get("quote_digest"),
                "evidence": candidate["evidence"], "verification": candidate["verification"], "sample_price_history": True,
            })
            checked += 1
        return checked, created
