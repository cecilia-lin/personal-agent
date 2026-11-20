from datetime import datetime, timezone
from app.domain.models import total, now

class FinanceSkill:
    @staticmethod
    def calculate(account, bills, actions, adjustments=()):
        committed = sum(b["amount_minor"] for b in bills if not b["paid"])
        reservations = sum(a["total_minor"] for a in actions if a["status"] == "active")
        adjustment_total = sum(a["amount_minor"] for a in adjustments if a["effective_at"] > account["observed_at"])
        cash = account["spendable_minor"] + adjustment_total
        remaining_cap = max(0, account.get("spending_cap_minor", 30000) - account.get("cap_used_minor", 0) - reservations)
        allowance = max(0, min(cash - account["protected_minor"] - committed - reservations, remaining_cap))
        return {"spendable_minor": account["spendable_minor"], "protected_minor": account["protected_minor"],
                "bills_minor": committed, "reservations_minor": reservations, "available_minor": allowance,
                "currency": account["currency"], "posted_purchase_expenses_minor": 0,
                "post_snapshot_adjustments_minor": adjustment_total, "cash_available_minor": cash,
                "spending_cap_minor": account.get("spending_cap_minor", 30000), "remaining_cap_minor": remaining_cap,
                "formula": "max(0, min(cash snapshot + subsequent adjustments - buffer - unpaid bills - active reservations, cap - cap used - active reservations))"}

class ShoppingSkill:
    @staticmethod
    def evaluate(product, context, max_price_minor=None, quantity=1, quote=None):
        amount = quote["total_minor"] if quote is not None else (None if total(product) is None else total(product)*quantity)
        ceiling = context["budget"]["available_minor"]
        if max_price_minor is not None:
            ceiling = min(ceiling, max_price_minor)
        reasons = []
        if amount is None:
            reasons.append("Tax or shipping is unknown.")
        elif amount > ceiling:
            reasons.append("Total exceeds the current purchase allowance or task limit.")
        if product["stock"] < quantity:
            reasons.append("Insufficient stock.")
        if context["preferences"]["repairable"] and not product["repairable"]:
            reasons.append("Does not meet your repairability preference.")
        return {"eligible": not reasons, "reasons": reasons, "total_minor": amount}

class UtilitiesSkill:
    @staticmethod
    def check(bills):
        today = datetime.fromisoformat(now()).date()
        return [{"bill_id": b["id"], "name": b["name"], "source_id": b["source_id"],
                 "due_in_days": (datetime.fromisoformat(b["due_at"]).date() - today).days,
                 "increase_minor": max(0, b["amount_minor"] - b["previous_minor"]),
                 "provenance": b["provenance"]} for b in bills if not b["paid"]]

class PortfolioSkill:
    @staticmethod
    def summarize(holdings):
        value = sum(h["value_minor"] for h in holdings)
        return {"total_minor": value, "currency": "USD", "read_only": True, "provenance": "fixture",
                "observed_at": holdings[0]["observed_at"] if holdings else None,
                "holdings": [{**h, "allocation_pct": round(100 * h["value_minor"] / value, 1) if value else 0} for h in holdings]}
