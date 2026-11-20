"""Deterministic, independently validated local merchant quotes. No real checkout."""
from datetime import datetime
from app.domain.models import Problem, now
from app.services.agent import digest

MERCHANT = "demo-home"

class DemoMerchant:
    def quote(self, unit, product, quantity=1):
        if product["tax_minor"] is None or product["shipping_minor"] is None:
            return {"complete": False, "total_minor": None, "rejected_offers": [],
                    "reason": "Tax or shipping is unknown."}
        subtotal = product["price_minor"] * quantity
        baseline_tax = (subtotal * 900 + 5000) // 10000
        shipping = product["shipping_minor"]
        baseline = subtotal + baseline_tax + shipping
        options, rejected = [], []
        current = datetime.fromisoformat(now())
        for offer in unit.all("offers"):
            reasons = []
            canonical = unit.get("merchant_offers", offer.get("code") or "unknown", False)
            if offer.get("merchant_id") != MERCHANT:
                reasons.append("Different merchant.")
            if offer.get("unknowns"):
                reasons.append("Unknown terms: " + ", ".join(offer["unknowns"]))
            if not canonical:
                reasons.append("The demo merchant cannot validate this code.")
            else:
                for key in ("discount_type", "value", "min_spend_minor", "minimum_basis", "starts_at", "expires_at",
                            "restrictions", "excluded_products", "excluded_categories", "max_discount_minor"):
                    if offer.get(key) != canonical.get(key):
                        reasons.append("Extracted terms do not match the merchant's current rules.")
                        break
            try:
                if current < datetime.fromisoformat(offer["starts_at"]):
                    reasons.append("Offer has not started.")
                if current >= datetime.fromisoformat(offer["expires_at"]):
                    reasons.append("Offer expired.")
            except (ValueError, TypeError, KeyError):
                reasons.append("Validity window or timezone is unknown.")
            if offer.get("restrictions") != "none":
                reasons.append("Customer, membership, or payment restriction is not satisfied.")
            if product["id"] in offer.get("excluded_products", []) or product["category"] in offer.get("excluded_categories", []):
                reasons.append("This product or category is excluded.")
            discount = 0
            if not reasons:
                discount = subtotal * offer["value"] // 100 if offer["discount_type"] == "percent" else offer["value"]
                if offer.get("max_discount_minor") is not None:
                    discount = min(discount, offer["max_discount_minor"])
                discount = min(subtotal, discount)
                measured = subtotal if offer["minimum_basis"] == "before_discount" else subtotal - discount
                if measured < offer["min_spend_minor"]:
                    reasons.append("Below the minimum spend. No extra spending suggested.")
            if reasons:
                rejected.append({"offer_id": offer["id"], "code": offer.get("code"), "source_id": offer["source_id"], "reasons": reasons})
                continue
            taxable = subtotal - discount
            tax = (taxable * 900 + 5000) // 10000
            options.append({"offer_id": offer["id"], "code": offer["code"], "discount_minor": discount,
                            "tax_minor": tax, "total_minor": taxable + tax + shipping,
                            "offer_version": offer["version"], "source_id": offer["source_id"],
                            "source_version": offer["source_version"], "merchant_version": canonical["version"],
                            "evidence": offer["supporting_text"]})
        options.sort(key=lambda o: (o["total_minor"], o["code"]))
        best = options[0] if options and options[0]["total_minor"] < baseline else None
        quote = {
            "complete": True, "merchant_id": MERCHANT, "product_id": product["id"], "quantity": quantity,
            "subtotal_minor": subtotal, "unit_price_minor": product["price_minor"], "shipping_minor": shipping,
            "tax_minor": best["tax_minor"] if best else baseline_tax, "discount_minor": best["discount_minor"] if best else 0,
            "total_minor": best["total_minor"] if best else baseline, "baseline_minor": baseline, "currency": "USD",
            "promotion": best, "applied_code": best["code"] if best else None,
            "eligible_offers": options, "rejected_offers": rejected,
            "tax_rule": "9% on discounted merchandise; half-up to cents",
            "shipping_rule": "Stored complete per-order fixture shipping charge",
            "provenance": "simulated",
        }
        # Bind only executable terms; unrelated rejected offers do not change an approval.
        quote["quote_digest"] = digest({k: quote[k] for k in
            ("merchant_id", "product_id", "quantity", "subtotal_minor", "shipping_minor", "tax_minor", "discount_minor", "total_minor", "promotion")})
        return quote

    def validate_cart(self, unit, product, terms):
        quote = self.quote(unit, product, terms["quantity"])
        if not quote["complete"] or quote["quote_digest"] != terms["merchant_quote"]["quote_digest"]:
            raise Problem("Merchant quote or promotion conditions changed. Prepare a fresh proposal.")
        if quote["applied_code"]:
            # The independent merchant rule must still exist when the cart is created.
            unit.get("merchant_offers", quote["applied_code"])
        return {**quote, "code_validation": "confirmed_by_demo_merchant" if quote["applied_code"] else "no_code",
                "cart_verified_at": now()}
