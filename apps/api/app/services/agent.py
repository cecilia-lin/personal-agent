from datetime import datetime, timedelta, timezone
import hashlib
import json
from time import perf_counter
from uuid import uuid4
from app.config import DEMO_USER, ROOT
from app.domain.models import Account, Bill, Product, Preferences, Problem, now, total
from app.integrations.contracts import DemoModelClient, LocalRouting
from app.integrations import amplitude_client, statsig_client
from app.integrations.claim_verification import allowed, evidence_fingerprint, product_fingerprint
from app.integrations.senso import evidence_provider, repairability_claim
from app.integrations.sie import SIERanker
from app.services.skills import FinanceSkill, ShoppingSkill, UtilitiesSkill, PortfolioSkill
from app.services.requirements import supported_requirement, claim_required

def uid(prefix):
    return f"{prefix}_{uuid4().hex}"

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

class AgentService:
    def __init__(self, store, settings):
        self.store, self.settings = store, settings
        self.model = DemoModelClient()
        self.evidence = evidence_provider()
        self.ranker = SIERanker()
        self.router = LocalRouting(settings.routing_policy)
        from app.services.documents import Documents
        from app.services.merchant import DemoMerchant
        self.documents, self.merchant = Documents(self), DemoMerchant()
        from app.services.intent import Intent
        self.intent = Intent(self)

    def require_demo(self):
        if self.settings.mode != "demo":
            raise Problem("Live identity, model, and merchant adapters are not configured. Set APP_MODE=demo for the local fixture journey.", 503)

    def product_evidence(self, product, required, requirement="repairability"):
        """Network boundary: callers must finish their read transaction first."""
        live = bool(getattr(self.evidence, "requires_context", False))
        product = {**product, "_required_feature": requirement}
        passages = []
        try:
            passages = self.evidence.for_product(product)
            if not required:
                result = {"state": "not_required", "reason": "Repairability is not required by the current preference."}
            elif not live:
                result = {"state": "demo", **repairability_claim(product),
                          "reason": "Fixture catalog only; no Senso claim verification.", "sources": passages}
                if requirement != "repairability" and repairability_claim({k: v for k, v in product.items() if k != "_required_feature"})["feature"] != requirement:
                    result.update(state="unsupported", reason="The offline fixture does not assert this exact required feature.")
            elif hasattr(self.evidence, "verify_product"):
                result = self.evidence.verify_product(product, passages)
            else:
                result = {"state": "not_verifiable", "reason": "Product information retrieved; Senso fact-check access is unavailable."}
        except Exception as exc:
            result = {"state": "error", "reason": f"Required claim unresolved: evidence service error ({type(exc).__name__})."}
        result = {"feature": None, "claim": None, "check_id": None, "checked_at": None, "sources": [],
                  "provider": "senso" if live else "fixture", "provenance": "live" if live else "fixture",
                  **result, "requirement": requirement, "required": required,
                  "product_id": product["id"], "product_version": product["version"],
                  "product_fingerprint": product_fingerprint(product),
                  "evidence_fingerprint": evidence_fingerprint(passages), "evaluated_at": now()}
        # A provider cannot waive an essential shopper requirement.
        if required and result["state"] == "not_required":
            result.update(state="not_verifiable", reason="Required repairability claim was not checked.")
        if live and required and result["state"] == "supported":
            expected = repairability_claim(product)
            normalize_claim = lambda value: " ".join(str(value or "").casefold().strip().rstrip(".").split())
            if (not expected["claim"] or result.get("feature") != expected["feature"]
                    or normalize_claim(result.get("claim")) != normalize_claim(expected["claim"])
                    or requirement != "repairability" and expected["feature"] != requirement):
                result.update(state="not_verifiable", reason="The evidence service did not verify this product's exact requested feature and claim.")
        if live and required and result["state"] == "supported" and not allowed(result, True):
            result.update(state="not_verifiable", reason="Fact-check response lacks a check ID or versioned supporting passage.")
        result["support_fingerprint"] = evidence_fingerprint(result["sources"])
        return {"evidence": passages, "verification": result}

    def apply_evidence(self, candidate, evidence):
        candidate.update(evidence)
        verification = evidence["verification"]
        verified = allowed(verification, bool(getattr(self.evidence, "requires_context", False)))
        if not verified:
            candidate["eligible"] = False
            candidate["reasons"].append(f"Required claim {verification['state']}: {verification.get('reason', 'unresolved')}")
        candidate["proposal_allowed"] = candidate["eligible"] and verified
        return candidate

    def proposal_flags(self, task, candidates):
        recommendation = self.intent.decide(task, candidates)
        for candidate in candidates:
            candidate["proposal_allowed"] = bool(candidate["eligible"] and recommendation["decision"] == "Buy"
                and allowed(candidate.get("verification", {}), bool(getattr(self.evidence, "requires_context", False)))
                and (task.get("target_price_minor") is None or candidate["total_minor"] <= task["target_price_minor"]))
        return recommendation

    def refresh_claim(self, user_id, task_id, product_id):
        with self.store.transaction(user_id) as unit:
            task = unit.get("tasks", task_id)
            product = unit.get("products", product_id)
            preferences = unit.get("preferences", "shopping")
            if product["category"] != task["category"]:
                raise Problem("This product is outside the task's selected category.")
        evidence = self.product_evidence(product, claim_required(task, preferences), task.get("requirement", "repairability"))
        with self.store.transaction(user_id, write=True) as unit:
            current = unit.get("products", product_id)
            ctx = self.context(unit)
            if product_fingerprint(current) != product_fingerprint(product) or ctx["preferences"]["version"] != preferences["version"]:
                raise Problem("Product or preference changed during verification. Check again.")
            task = unit.get("tasks", task_id)
            quote = self.merchant.quote(unit, current)
            checks = ShoppingSkill.evaluate(current, ctx, task["max_price_minor"], quote=quote)
            candidate = self.apply_evidence({**current, **checks, "quote": quote,
                                            "price_history": self.intent.history(unit, product_id)}, evidence)
            candidates = [candidate if c["id"] == product_id else c for c in task["checkpoint"].get("candidates", [])]
            checkpoint = {**task["checkpoint"], "candidates": candidates}
            if candidates:
                checkpoint["recommendation"] = self.proposal_flags(task, candidates)
            unit.save("tasks", task_id, {**task, "checkpoint": checkpoint}, task["version"])
            self.event(unit, task, "required_claim_checked", {"product_id": product_id, **evidence})
        return evidence["verification"]

    def claim_reason(self, product, verification, required, original=None, requirement="repairability"):
        if not verification or verification.get("required") != required or verification.get("requirement") != requirement or verification.get("product_fingerprint") != product_fingerprint(product):
            return "Required claim is stale or missing for this product version. Run verification again."
        if not allowed(verification, bool(getattr(self.evidence, "requires_context", False))):
            return f"Required claim {verification.get('state', 'pending')}: {verification.get('reason', 'unresolved')}"
        if original is not None and any(original.get(k) != verification.get(k) for k in (
                "product_fingerprint", "evidence_fingerprint", "support_fingerprint", "claim", "feature", "requirement", "required", "provider")):
            return "Required claim or evidence version changed since this proposal. Review a new proposal."
        return None

    def event(self, unit, task, kind, details, provenance="simulated", latency_ms=None):
        # Writer transactions serialize this sequence, including fixed-clock demos.
        # UUID lexical order does not represent execution order.
        sequence = 1 + max((e.get("sequence", 0) for e in unit.all("audit_events")), default=0)
        event = {"kind": kind, "task_id": task.get("id"), "session_id": task.get("session_id"),
                 "run_id": task.get("run_id"), "timestamp": now(), "details": details,
                 "provenance": provenance, "provider": self.model.provider, "latency_ms": latency_ms,
                 "tokens": None, "cost_minor": None, "sequence": sequence}
        unit.save("audit_events", uid("evt"), event)
        if kind != "budget_calculated":
            metric = unit.save("analytics_events", uid("metric"), {
                **{k: v for k, v in event.items() if k != "details"},
                "routing": task.get("routing"), "delivery": "best_effort_after_commit",
            })
            unit.after_commit.append(lambda: amplitude_client.track_metadata(unit.user_id, metric))

    def seed(self, reset=False):
        self.require_demo()
        fixture = json.loads((ROOT / "fixtures/demo.json").read_text(encoding="utf-8-sig"))
        with self.store.transaction(DEMO_USER, write=True) as unit:
            if reset:
                unit.clear_demo()
            if unit.get("accounts", "cash", False):
                self.documents.seed(unit)
                return {"seeded": False, "reason": "Existing demo data preserved."}
            stamp = now()
            unit.save("accounts", "cash", Account(**fixture["account"], observed_at=stamp).model_dump())
            unit.save("preferences", "shopping", Preferences(updated_at=stamp).model_dump())
            for bill in fixture["bills"]:
                data = dict(bill)
                record_id = data.pop("id")
                days = data.pop("due_in_days")
                data["due_at"] = (datetime.fromisoformat(now()) + timedelta(days=days)).isoformat()
                unit.save("bills", record_id, Bill(**data, observed_at=stamp).model_dump())
            for product in fixture["products"]:
                data = dict(product)
                record_id = data.pop("id")
                unit.save("products", record_id, Product(**data, observed_at=stamp).model_dump())
            for holding in fixture["holdings"]:
                unit.save("holdings", holding["id"], {**holding, "observed_at": stamp, "provenance": "fixture"})
            self.documents.seed(unit)
            return {"seeded": True, "provenance": "fixture"}

    def context(self, unit):
        account = unit.get("accounts", "cash")
        preferences = unit.get("preferences", "shopping")
        bills, actions = unit.all("bills"), unit.all("reservations")
        return {"account": account, "preferences": preferences, "bills": bills,
                "budget": FinanceSkill.calculate(account, bills, actions, unit.all("adjustments")),
                "context_versions": {
                    "account": account["version"], "preferences": preferences["version"],
                    "bills": {b["id"]: b["version"] for b in bills},
                    "actions": {a["id"]: a["version"] for a in actions},
                }}

    def dashboard(self, user_id):
        self.require_demo()
        with self.store.transaction(user_id) as unit:
            ctx = self.context(unit)
            return {**ctx, "user_id": user_id, "mode": self.settings.mode,
                    "tasks": sorted(unit.all("tasks"), key=lambda t: t["created_at"], reverse=True),
                    "actions": unit.all("actions"), "products": unit.all("products"),
                    "offers": unit.all("offers"), "next_actions": unit.all("next_actions"),
                    "sample_bill": self.documents.sample_bill(), "watchlist": unit.all("watch_items"),
                    "categories": sorted({p["category"] for p in unit.all("products")}),
                    "portfolio": PortfolioSkill.summarize(unit.all("holdings")),
                    "utility_checks": UtilitiesSkill.check(ctx["bills"])}

    def _new_task(self, unit, goal, category, max_price_minor=None, skill="shopping"):
        session_id, task_id = uid("session"), uid("task")
        stamp = now()
        unit.save("sessions", session_id, {"goal": goal, "summary": "Task created.", "updated_at": stamp})
        return unit.save("tasks", task_id, {
            "session_id": session_id, "run_id": uid("run"), "skill": skill, "goal": goal,
            "category": category, "max_price_minor": max_price_minor, "status": "queued",
            "checkpoint": {}, "created_at": stamp, "updated_at": stamp,
            "next_check": stamp, "routing": self.router.choose(unit.user_id),
            "provenance": "simulated",
        })

    def create_task(self, user_id, request):
        self.require_demo()
        if request.category != "desk-light":
            raise Problem("The shopping demo supports the desk-light category. Use the Utilities view for bills.", 422)
        requirement = supported_requirement(request.goal, request.requirement)
        essential = bool(request.requirement or "repairable" in request.goal.casefold() or requirement != "repairability")
        with self.store.transaction(user_id, write=True) as unit:
            self.context(unit)
            task = self._new_task(unit, request.goal, request.category, request.max_price_minor)
            return unit.save("tasks", task["id"], {**task, "requirement": requirement, "essential_requirement": essential,
                                                "urgency": request.urgency, "target_price_minor": request.target_price_minor}, task["version"])

    def run_task(self, user_id, task_id):
        self.require_demo()
        started = perf_counter()
        with self.store.transaction(user_id) as unit:
            snapshot = unit.get("tasks", task_id)
            if snapshot["status"] not in {"queued", "failed", "awaiting_selection"}:
                return snapshot
            snapshot_context = self.context(unit)
            products = self.model.retrieve_candidates(unit.all("products"), snapshot["category"]) if snapshot["skill"] == "shopping" else []
            candidates = []
            for product in products:
                quote = self.merchant.quote(unit, product)
                checks = ShoppingSkill.evaluate(product, snapshot_context, snapshot["max_price_minor"], quote=quote)
                candidates.append({**product, **checks, "quote": quote, "price_history": self.intent.history(unit, product["id"])})
        for candidate in candidates:
            self.apply_evidence(candidate, self.product_evidence(candidate, claim_required(snapshot, snapshot_context["preferences"]), snapshot.get("requirement", "repairability")))
        ranking = (self.ranker.score(candidates, snapshot["category"], snapshot_context["preferences"]["repairable"])
                   if snapshot["routing"].get("enabled") and candidates else
                   {"provider": "deterministic-demo", "provenance": "simulated", "reason": "enable_reranker is false"})
        first_run = snapshot["status"] == "queued"
        with self.store.transaction(user_id, write=True) as unit:
            task = unit.get("tasks", task_id)
            if task["version"] != snapshot["version"]:
                return task
            ctx = self.context(unit)
            if ctx["context_versions"] != snapshot_context["context_versions"] or any(
                    product_fingerprint(unit.get("products", p["id"])) != product_fingerprint(p) for p in products):
                raise Problem("Product or spending context changed while checking evidence. Run the task again.")
            if first_run:
                self.event(unit, task, "task_started", {"skill": task["skill"], "routing": task["routing"]})
            self.event(unit, task, "budget_calculated", {
                "calculation": ctx["budget"], "source_versions": ctx["context_versions"],
                "source_ids": [ctx["account"]["source_id"]] + [b["source_id"] for b in ctx["bills"]],
            }, "fixture")
            if task["skill"] == "utilities":
                checks = UtilitiesSkill.check(ctx["bills"])
                task["checkpoint"] = {"checks": checks, "bill_versions": ctx["context_versions"]["bills"]}
                task["status"] = "completed"
                task["next_check"] = (datetime.fromisoformat(now()) + timedelta(days=1)).isoformat()
                self.event(unit, task, "task_completed", {"checks": checks, "execution": "local_scan"},
                           latency_ms=round((perf_counter() - started) * 1000, 3))
            else:
                candidates.sort(key=lambda c: (not c["eligible"], -c.get("relevance_score", 0),
                    c["total_minor"] if c["total_minor"] is not None else 10**12, c["id"]))
                task["checkpoint"] = {"candidates": candidates, "budget": ctx["budget"],
                                      "plan": self.model.plan_task(task["goal"]), "ranking": ranking,
                                      "recommendation": self.proposal_flags(task, candidates)}
                task["status"] = "awaiting_selection" if any(c["eligible"] for c in candidates) else "failed"
                task["next_check"] = None
                self.event(unit, task, "candidates_checked", {"candidates": [
                    {"product_id": c["id"], "eligible": c["eligible"], "reasons": c["reasons"], "evidence": c["evidence"], "verification": c["verification"]}
                    for c in candidates], "ranking": ranking}, "fixture", round((perf_counter() - started) * 1000, 3))
                if task["status"] == "failed":
                    task["error"] = "No candidate meets the current budget, stock, category, preference, and required evidence constraints."
                    self.event(unit, task, "task_failed", {"reason": task["error"]})
            task["updated_at"] = now()
            result = unit.save("tasks", task_id, task, task["version"])
        # Send only after the task transaction commits. Re-running an existing task
        # returns above, so it does not emit another first-run event.
        if first_run:
            statsig_client.track_task_started(user_id)
        return result

    def detail(self, user_id, task_id):
        with self.store.transaction(user_id) as unit:
            task = unit.get("tasks", task_id)
            return {"task": task,
                    "proposals": sorted([p for p in unit.all("proposals") if p["task_id"] == task_id], key=lambda p: p["created_at"], reverse=True),
                    "actions": [a for a in unit.all("actions") if a["task_id"] == task_id],
                    "audit": sorted([e for e in unit.all("audit_events") if e["task_id"] == task_id], key=lambda e: (e.get("sequence", 0), e["timestamp"], e["id"]))}

    def prepare(self, user_id, task_id, request):
        self.require_demo()
        verification = self.refresh_claim(user_id, task_id, request.product_id)
        with self.store.transaction(user_id, write=True) as unit:
            task = unit.get("tasks", task_id)
            product = unit.get("products", request.product_id)
            ctx = self.context(unit)
            claim_error = self.claim_reason(product, verification, claim_required(task, ctx["preferences"]), requirement=task.get("requirement", "repairability"))
            if claim_error:
                raise Problem(claim_error)
            if task["status"] not in {"awaiting_selection", "awaiting_approval", "approved"}:
                raise Problem("Run a shopping task before preparing a proposal.")
            if task["checkpoint"].get("recommendation", {"decision": "Buy"})["decision"] != "Buy":
                raise Problem("Only a Buy decision can become a cart proposal. Save a watch or revise your target/urgency.")
            product = unit.get("products", request.product_id)
            if product["category"] != task["category"]:
                raise Problem("This product is outside the task's selected category.")
            if getattr(self.evidence, "requires_context", False):
                candidate = next((c for c in task["checkpoint"].get("candidates", [])
                                  if c["id"] == product["id"]), None)
                if not candidate or not candidate.get("evidence"):
                    raise Problem("Supporting Senso context is required before preparing this product.")
            ctx = self.context(unit)
            merchant_quote = self.merchant.quote(unit, product, request.quantity)
            checks = ShoppingSkill.evaluate(product, ctx, task["max_price_minor"], request.quantity, merchant_quote)
            if not checks["eligible"]:
                raise Problem(" ".join(checks["reasons"]))
            if task.get("target_price_minor") is not None and checks["total_minor"] > task["target_price_minor"]:
                raise Problem("This quote is above your target. Revise the target or keep watching.")
            for old in unit.all("proposals"):
                if old["task_id"] == task_id and old["status"] in {"pending", "approved"}:
                    unit.save("proposals", old["id"], {**old, "status": "superseded"}, old["version"])
            terms = {
                "operation": "demo_cart.add", "product_id": product["id"], "product_name": product["name"],
                "quantity": request.quantity, "unit_price_minor": product["price_minor"],
                "tax_minor": merchant_quote["tax_minor"], "shipping_minor": merchant_quote["shipping_minor"],
                "discount_minor": merchant_quote["discount_minor"], "applied_code": merchant_quote["applied_code"],
                "merchant_quote": merchant_quote,
                "total_minor": checks["total_minor"], "currency": product["currency"],
                "quote_version": product["version"], "source_id": product["source_id"],
                "source_version": product["source_version"], "context_versions": ctx["context_versions"],
                "task_limit_minor": task["max_price_minor"], "target_price_minor": task.get("target_price_minor"),
                "urgency": task.get("urgency", "soon"), "expires_at": (datetime.fromisoformat(now()) + timedelta(minutes=15)).isoformat(),
                "verification": verification,
            }
            proposal = unit.save("proposals", uid("proposal"), {
                "task_id": task_id, "session_id": task["session_id"], "run_id": task["run_id"],
                "terms": terms, "terms_digest": digest(terms), "status": "pending",
                "created_at": now(), "provenance": "simulated",
            })
            unit.save("tasks", task_id, {**task, "status": "awaiting_approval", "proposal_id": proposal["id"], "updated_at": now()}, task["version"])
            self.event(unit, task, "proposal_prepared", {"proposal_id": proposal["id"], "terms": terms, "terms_digest": proposal["terms_digest"]})
            return proposal

    def stale_reason(self, unit, proposal, verification=None):
        terms = proposal["terms"]
        if datetime.fromisoformat(terms["expires_at"]) <= datetime.fromisoformat(now()):
            return "Proposal expired. Prepare a new proposal."
        product = unit.get("products", terms["product_id"])
        ctx = self.context(unit)
        task = unit.get("tasks", proposal["task_id"])
        claim_error = self.claim_reason(product, verification, claim_required(task, ctx["preferences"]), terms.get("verification") or {}, task.get("requirement", "repairability"))
        if claim_error:
            return claim_error
        if product["version"] != terms["quote_version"] or product["source_version"] != terms["source_version"]:
            return "Quote or stock changed. Review a new proposal."
        if ctx["context_versions"] != terms["context_versions"]:
            return "Budget, bills, reservations, or preferences changed. Review a new proposal."
        fresh_quote = self.merchant.quote(unit, product, terms["quantity"])
        if not fresh_quote["complete"] or fresh_quote["quote_digest"] != terms["merchant_quote"]["quote_digest"]:
            return "Promotion or merchant quote changed. Review a new proposal."
        checks = ShoppingSkill.evaluate(product, ctx, terms["task_limit_minor"], terms["quantity"], fresh_quote)
        if not checks["eligible"]:
            return " ".join(checks["reasons"])
        if checks["total_minor"] != terms["total_minor"] or product["currency"] != terms["currency"]:
            return "The total or currency changed. Review a new proposal."
        return None

    def invalidate(self, unit, proposal, task, reason):
        unit.save("proposals", proposal["id"], {**proposal, "status": "stale", "error": reason}, proposal["version"])
        unit.save("tasks", task["id"], {**task, "status": "awaiting_selection", "updated_at": now()}, task["version"])
        self.event(unit, task, "execution_blocked", {"proposal_id": proposal["id"], "reason": reason})

    def decide(self, user_id, proposal_id, request):
        self.require_demo()
        error = None
        with self.store.transaction(user_id) as unit:
            snapshot = unit.get("proposals", proposal_id)
        verification = (self.refresh_claim(user_id, snapshot["task_id"], snapshot["terms"]["product_id"])
                        if request.decision == "approve" and snapshot["status"] != "executed" else None)
        with self.store.transaction(user_id, write=True) as unit:
            proposal = unit.get("proposals", proposal_id)
            task = unit.get("tasks", proposal["task_id"])
            if request.terms_digest != proposal["terms_digest"]:
                raise Problem("Approval does not match the exact proposal terms.")
            if proposal["status"] == "executed" and request.decision == "approve":
                return proposal
            if proposal["status"] == "rejected" and request.decision == "reject":
                return proposal
            if proposal["status"] not in ({"pending", "approved"} if request.decision == "approve" else {"pending"}):
                raise Problem("This proposal is no longer pending review.")
            if request.decision == "reject":
                proposal = unit.save("proposals", proposal_id, {**proposal, "status": "rejected", "decided_at": now()}, proposal["version"])
                unit.save("tasks", task["id"], {**task, "status": "rejected", "updated_at": now()}, task["version"])
                self.event(unit, task, "proposal_rejected", {"proposal_id": proposal_id})
            else:
                error = self.stale_reason(unit, proposal, verification)
                if error:
                    self.invalidate(unit, proposal, task, error)
                else:
                    if proposal["status"] == "approved":
                        return proposal  # Fresh check succeeded; preserve the original approval identity.
                    proposal = unit.save("proposals", proposal_id, {**proposal, "status": "approved", "approved_by": user_id, "approval_id": uid("approval"), "approved_at": now()}, proposal["version"])
                    unit.save("tasks", task["id"], {**task, "status": "approved", "updated_at": now()}, task["version"])
                    self.event(unit, task, "recommendation_accepted", {"proposal_id": proposal_id, "terms_digest": proposal["terms_digest"]})
        if error:
            raise Problem(error)
        return proposal

    def execute(self, user_id, proposal_id):
        self.require_demo()
        started, error, action = perf_counter(), None, None
        with self.store.transaction(user_id) as unit:
            snapshot = unit.get("proposals", proposal_id)
            existing = unit.get("actions", "action_" + proposal_id.removeprefix("proposal_"), False)
            if existing:
                return existing
        try:
            verification = self.refresh_claim(user_id, snapshot["task_id"], snapshot["terms"]["product_id"])
        except Problem:
            # A concurrent execution may have committed while this request checked evidence.
            with self.store.transaction(user_id) as unit:
                existing = unit.get("actions", "action_" + proposal_id.removeprefix("proposal_"), False)
                if existing:
                    return existing
            raise
        with self.store.transaction(user_id, write=True) as unit:
            proposal = unit.get("proposals", proposal_id)
            task = unit.get("tasks", proposal["task_id"])
            # Deterministic key + unique owned primary key + serialized transaction.
            action_id = "action_" + proposal_id.removeprefix("proposal_")
            existing = unit.get("actions", action_id, False)
            if existing:
                return existing
            if proposal["status"] != "approved" or proposal.get("approved_by") != user_id:
                raise Problem("An exact, owned, approved proposal is required before execution.")
            error = self.stale_reason(unit, proposal, verification)
            if error:
                self.invalidate(unit, proposal, task, error)
            else:
                terms = proposal["terms"]
                task["run_id"] = uid("run")
                unit.save("runs", task["run_id"], {"kind": "cart_execution", "task_id": task["id"], "created_at": now(), "status": "completed"})
                product = unit.get("products", terms["product_id"])
                cart_result = self.merchant.validate_cart(unit, product, terms)
                reservation_id = "reservation_" + action_id.removeprefix("action_")
                unit.save("reservations", reservation_id, {"action_id": action_id, "total_minor": terms["total_minor"],
                    "status": "active", "created_at": now(), "currency": "USD", "provenance": "simulated"})
                unit.save("products", product["id"], {**product, "stock": product["stock"] - terms["quantity"]}, product["version"])
                action = unit.save("actions", action_id, {
                    "proposal_id": proposal_id, "task_id": task["id"], "session_id": task["session_id"],
                    "run_id": task["run_id"], "product_id": terms["product_id"], "product_name": terms["product_name"],
                    "quantity": terms["quantity"], "total_minor": terms["total_minor"], "currency": terms["currency"],
                    "status": "in_demo_cart", "created_at": now(), "provenance": "simulated",
                    "posted_expense": False, "reservation_id": reservation_id, "cart": cart_result,
                })
                unit.save("proposals", proposal_id, {**proposal, "status": "executed", "action_id": action_id}, proposal["version"])
                unit.save("tasks", task["id"], {**task, "status": "completed", "action_id": action_id, "updated_at": now()}, task["version"])
                session = unit.get("sessions", task["session_id"])
                unit.save("sessions", session["id"], {**session, "summary": "Approved item added to the simulated cart.", "updated_at": now()}, session["version"])
                self.event(unit, task, "action_executed", {"action_id": action_id, "proposal_id": proposal_id, "checks": ["exact_approval", "expiry", "quote", "stock", "budget", "preferences"], "posted_expense": False},
                           latency_ms=round((perf_counter() - started) * 1000, 3))
                self.event(unit, task, "task_completed", {"action_id": action_id})
        if error:
            raise Problem(error)
        return action

    def edit(self, user_id, table, record_id, updates):
        self.require_demo()
        with self.store.transaction(user_id, write=True) as unit:
            record = unit.get(table, record_id)
            payload = {**record, **updates, "observed_at": now()}
            if table == "products":
                payload["source_version"] = record["source_version"] + 1
            if table == "preferences":
                payload.pop("observed_at", None)
                payload["updated_at"] = now()
            result = unit.save(table, record_id, payload, record["version"])
            self.event(unit, {}, "user_corrected", {"record_type": table, "record_id": record_id, "version": result["version"]}, "fixture")
            return result


    def remove_cart(self, user_id, action_id):
        self.require_demo()
        with self.store.transaction(user_id, write=True) as unit:
            action = unit.get("actions", action_id)
            if action["status"] == "removed":
                return action
            reservation = unit.get("reservations", action["reservation_id"])
            if reservation["status"] != "active":
                raise Problem("Cart reservation is not active.")
            unit.save("reservations", reservation["id"], {**reservation, "status": "released", "released_at": now()}, reservation["version"])
            product = unit.get("products", action["product_id"])
            unit.save("products", product["id"], {**product, "stock": product["stock"] + action["quantity"]}, product["version"])
            action = unit.save("actions", action_id, {**action, "status": "removed", "removed_at": now()}, action["version"])
            task = unit.get("tasks", action["task_id"])
            self.event(unit, task, "cart_removed", {"action_id": action_id, "reservation_id": reservation["id"], "released_minor": reservation["total_minor"]})
            return action

    def scan(self, user_id, limit=5, guild_run_id=None):
        self.require_demo()
        run_id = "run_guild_" + digest(guild_run_id)[:32] if guild_run_id else uid("run")
        with self.store.transaction(user_id) as unit:
            existing = unit.get("runs", run_id, False)
            if existing:
                return {**existing.get("result", {}), "run_id": run_id, "duplicate": True, "status": existing["status"]}
            watched = [w for w in unit.all("watch_items") if w["status"] == "active"][:limit]
            products = {w["id"]: (unit.get("products", w["product_id"]), unit.get("tasks", w["task_id"])) for w in watched}
            preferences = unit.get("preferences", "shopping")
        watch_evidence = {key: self.product_evidence(product, claim_required(task, preferences), task.get("requirement", "repairability"))
                          for key, (product, task) in products.items()}
        with self.store.transaction(user_id, write=True) as unit:
            existing = unit.get("runs", run_id, False)
            if existing:
                return {**existing.get("result", {}), "run_id": run_id, "duplicate": True, "status": existing["status"]}
            ctx, created = self.context(unit), []
            tasks = unit.all("tasks")
            watches = [t for t in tasks if t["skill"] == "utilities"]
            watch = max(watches, key=lambda t: (t.get("next_check") or "", t["updated_at"]), default=None)
            queued_watch = any(t["skill"] == "utilities" and t["status"] == "queued" for t in tasks)
            if not queued_watch and (not watch or watch.get("next_check", now()) <= now() or
                    watch["checkpoint"].get("bill_versions") != ctx["context_versions"]["bills"]):
                self._new_task(unit, "Check upcoming bills and increases", "utilities", skill="utilities")
            watches_checked, watch_cards = self.intent.check_watches(unit, run_id, limit, watch_evidence)
            created.extend(watch_cards)
            due = [t["id"] for t in unit.all("tasks") if t["status"] == "queued" and (t.get("next_check") or now()) <= now()][:limit]
            for bill in ctx["bills"]:
                if len(created) >= limit:
                    break
                if bill["paid"] or datetime.fromisoformat(bill["due_at"]).date() > (datetime.fromisoformat(now())+timedelta(days=7)).date():
                    continue
                next_id = "next_" + bill["id"]
                if not unit.get("next_actions", next_id, False):
                    unit.save("next_actions", next_id, {"title": "Review upcoming " + bill["name"], "bill_id": bill["id"],
                        "due_at": bill["due_at"], "status": "open", "source_id": bill["source_id"], "run_id": run_id,
                        "updated_at": now(), "provenance": "simulated"})
                    created.append(next_id)
            for task in sorted(tasks, key=lambda t: t["created_at"], reverse=True):
                if len(created) >= limit:
                    break
                if task["skill"] != "shopping" or task["status"] not in {"queued", "awaiting_selection", "awaiting_approval"}:
                    continue
                for product in unit.all("products"):
                    if product["category"] != task["category"]:
                        continue
                    quote = self.merchant.quote(unit, product)
                    if not ShoppingSkill.evaluate(product, ctx, task["max_price_minor"], quote=quote)["eligible"]:
                        continue
                    promotion = quote.get("promotion")
                    if promotion:
                        next_id = "offer_review_" + digest([task["id"], promotion["offer_id"], promotion["offer_version"]])[:30]
                        if not unit.get("next_actions", next_id, False):
                            unit.save("next_actions", next_id, {"title": "Review " + promotion["code"] + " for your saved shopping task",
                                "task_id": task["id"], "source_id": promotion["source_id"], "status": "open",
                                "due_at": now(), "updated_at": now(), "run_id": run_id, "provenance": "simulated"})
                            created.append(next_id)
                    break
            unit.save("runs", run_id, {"kind": "review_due_tasks", "trigger": "guild_authenticated" if guild_run_id else "local_manual",
                "created_at": now(), "status": "running", "task_ids": due, "next_action_ids": created, "guild_run_id": guild_run_id})
        try:
            outcomes = [self.run_task(user_id, task_id) for task_id in due]
        except Exception:
            with self.store.transaction(user_id, write=True) as unit:
                run = unit.get("runs", run_id)
                unit.save("runs", run_id, {**run, "status": "failed", "completed_at": now()}, run["version"])
            raise
        with self.store.transaction(user_id, write=True) as unit:
            run = unit.get("runs", run_id)
            result = {"execution": "authenticated_backend_handler" if guild_run_id else "local_backend_handler",
                      "guild_execution_verified": False, "guild_run_id": guild_run_id, "run_id": run_id,
                      "processed": len(outcomes), "next_actions_created": len(created), "watchlist_checked": watches_checked,
                      "tasks": [{"id": t["id"], "status": t["status"], "skill": t["skill"]} for t in outcomes]}
            unit.save("runs", run_id, {**run, "status": "completed", "completed_at": now(), "result": result}, run["version"])
        return result
