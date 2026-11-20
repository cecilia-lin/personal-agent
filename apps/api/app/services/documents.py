"""Text imports are untrusted evidence. Demo extraction parses explicit field labels only."""
from datetime import datetime, timedelta
from email import policy
from email.parser import Parser
from hashlib import sha256
import re
from app.domain.models import Problem, now, BillConfirmation

def fingerprint(value):
    return sha256(value.encode()).hexdigest()

def fields(text):
    return {m.group(1).strip().lower().replace(" ", "_"): m.group(2).strip()
            for m in re.finditer(r"(?m)^([A-Za-z_ ]+):[ \t]*([^\r\n]*)$", text)}

def cents(value):
    value = value.strip().removeprefix("$")
    if not re.fullmatch(r"\d+(\.\d{1,2})?", value):
        raise ValueError("Invalid amount")
    whole, _, fraction = value.partition(".")
    return int(whole) * 100 + int(fraction.ljust(2, "0"))

def iso(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timezone required")
    return parsed.isoformat()

class Documents:
    def __init__(self, agent):
        self.agent = agent
        self.store = agent.store

    def source(self, unit, kind, text, subject="", sender=""):
        content_hash = fingerprint(text.replace("\r\n", "\n").strip())
        source_id = "source_" + fingerprint(kind + content_hash)[:32]
        existing = unit.get("sources", source_id, False)
        if existing:
            return existing
        record = {"kind": kind, "raw_text": text, "content_hash": content_hash, "source_version": 1,
                  "subject": subject, "sender": sender, "received_at": fields(text).get("received_at"),
                  "ingested_at": now(), "provenance": "simulated", "extraction": "deterministic labeled-text parser",
                  "authenticity": "unverified; sender text is not authentication"}
        source = unit.save("sources", source_id, record)
        unit.save("source_versions", source_id + "_v1", {**record, "source_id": source_id})
        return source

    def email(self, unit, text, subject="", sender=""):
        if text.lstrip().lower().startswith(("from:", "subject:", "mime-version:")):
            message = Parser(policy=policy.default).parsestr(text)
            subject, sender = subject or str(message.get("Subject", "")), sender or str(message.get("From", ""))
            if message.is_multipart():
                part = message.get_body(preferencelist=("plain",))
                if part is None:
                    raise Problem("Only plain-text email bodies are supported.", 422)
                body = part.get_content()
            else:
                body = message.get_content()
        else:
            body = text
        source = self.source(unit, "email", text, subject, sender)
        offer_id = "offer_" + source["id"].removeprefix("source_")
        existing = unit.get("offers", offer_id, False)
        if existing:
            return {"source": source, "offer": existing, "duplicate": True}
        values = fields(body)
        unknowns = []
        def required(key, convert=lambda x: x):
            try:
                value = values[key]
                if value.lower() in {"unknown", ""}:
                    raise ValueError()
                return convert(value)
            except (KeyError, ValueError, TypeError):
                unknowns.append(key)
                return None
        terms = {
            "merchant_id": required("merchant"), "code": required("code"),
            "discount_type": required("discount_type"), "value": required("value", int),
            "min_spend_minor": required("minimum_spend", cents),
            "minimum_basis": required("minimum_basis"),
            "starts_at": required("starts_at", iso), "expires_at": required("expires_at", iso),
            "max_discount_minor": required("maximum_discount", lambda v: None if v.lower() == "none" else cents(v)),
            "restrictions": required("restrictions"), "stackability": required("stackability"),
            "excluded_products": required("excluded_products", lambda v: [] if v == "none" else [x.strip() for x in v.split(",")]),
            "excluded_categories": required("excluded_categories", lambda v: [] if v == "none" else [x.strip() for x in v.split(",")]),
        }
        for key, allowed in {"discount_type": {"percent", "amount"}, "minimum_basis": {"before_discount", "after_discount"},
                             "stackability": {"allowed", "disallowed"}, "restrictions": {"none", "first_purchase", "membership", "payment_card"}}.items():
            if terms[key] not in allowed and key not in unknowns:
                unknowns.append(key)
        if terms["value"] is not None and (terms["value"] < 0 or (terms["discount_type"] == "percent" and terms["value"] > 100)):
            unknowns.append("discount_value")
        if values.get("currency") != "USD":
            unknowns.append("unsupported_or_unknown_currency")
        offer = unit.save("offers", offer_id, {
            **terms, "source_id": source["id"], "source_version": source["source_version"],
            "unknowns": sorted(set(unknowns)), "state": "discovered_unverified", "timezone": "explicit UTC offset" if terms["expires_at"] else "unknown",
            "supporting_text": body[:4000], "extraction_confidence": 1.0 if not unknowns else 0.4,
            "confidence_meaning": "Field coverage by deterministic parser, not a probability of authenticity.",
            "last_checked_at": now(), "provenance": "simulated",
        })
        return {"source": source, "offer": offer, "duplicate": False}

    def import_email(self, user_id, request):
        self.agent.require_demo()
        if not request.filename.lower().endswith((".txt", ".eml")):
            raise Problem("Use pasted text, .txt, or plain-text .eml. HTML and binary attachments are unsupported.", 422)
        with self.store.transaction(user_id, write=True) as unit:
            result = self.email(unit, request.text, request.subject, request.sender)
            self.agent.event(unit, {}, "promotion_discovered", {"source_id": result["source"]["id"], "offer_id": result["offer"]["id"], "duplicate": result["duplicate"]})
            return result

    def import_bill(self, user_id, request):
        self.agent.require_demo()
        if not request.filename.lower().endswith(".txt"):
            raise Problem("Bill imports currently support plain text only. PDF/image OCR is not configured.", 422)
        with self.store.transaction(user_id, write=True) as unit:
            source = self.source(unit, "bill", request.text)
            import_id = "import_" + source["id"].removeprefix("source_")
            existing = unit.get("bill_imports", import_id, False)
            if existing:
                return existing
            data = fields(request.text)
            extracted = {key: data.get(key) for key in ("provider", "account_ref", "invoice_id", "period_start", "period_end", "currency", "due_at", "status")}
            try:
                extracted["amount_minor"] = cents(data["amount"])
            except (KeyError, ValueError):
                extracted["amount_minor"] = None
            missing = [key for key, value in extracted.items() if value is None]
            return unit.save("bill_imports", import_id, {
                "source_id": source["id"], "fields": extracted, "missing_fields": missing,
                "status": "awaiting_confirmation", "provenance": "simulated",
                "extraction": "deterministic labeled-text parser", "created_at": now(),
            })

    def confirm_bill(self, user_id, import_id, request: BillConfirmation):
        self.agent.require_demo()
        confirmed = request.model_dump()
        try:
            start, end, due = [datetime.fromisoformat(confirmed[key]).date() for key in ("period_start", "period_end", "due_at")]
            if end < start:
                raise ValueError()
        except ValueError:
            raise Problem("Use valid ISO dates and a service period whose end follows its start.", 422)
        # A stable invoice/provider/account key prevents duplicate obligations across new sources.
        identity = "|".join(confirmed[key].strip().lower() for key in ("provider", "account_ref", "invoice_id"))
        bill_id = "bill_" + fingerprint(identity)[:24]
        with self.store.transaction(user_id, write=True) as unit:
            imported = unit.get("bill_imports", import_id)
            before = self.agent.context(unit)["budget"]["available_minor"]
            candidates = [b for b in unit.all("bills") if all(b.get(k, "").strip().lower() == confirmed[k].strip().lower() for k in ("provider", "account_ref", "invoice_id"))]
            existing = candidates[0] if candidates else unit.get("bills", bill_id, False)
            if existing:
                bill_id = existing["id"]
                if all(existing.get(k) == v for k, v in confirmed.items()):
                    return {"bill": existing, "duplicate": True, "allowance_before": before, "allowance_after": before, "comparison": existing.get("comparison")}
            previous = [b for b in unit.all("bills") if b["id"] != bill_id and b.get("provider") == request.provider
                        and b.get("account_ref") == request.account_ref and b.get("period_end", "9999") < request.period_start]
            prior = max(previous, key=lambda b: b["period_end"], default=None)
            comparable = bool(prior and abs((end-start).days - (datetime.fromisoformat(prior["period_end"]).date()-datetime.fromisoformat(prior["period_start"]).date()).days) <= 3)
            comparison = {"comparable": comparable, "previous_minor": prior["amount_minor"] if prior else None,
                          "change_minor": request.amount_minor-prior["amount_minor"] if comparable else None,
                          "change_percent_bps": (request.amount_minor-prior["amount_minor"])*10000//prior["amount_minor"] if comparable and prior["amount_minor"] else None,
                          "reason": "Comparable service periods." if comparable else "No comparable previous service period."}
            payload = {**confirmed, "name": request.provider, "paid": False, "source_id": imported["source_id"],
                       "source_version": 1, "provenance": "simulated", "observed_at": now(),
                       "previous_minor": prior["amount_minor"] if prior else request.amount_minor, "comparison": comparison}
            if existing:
                unit.save("bill_history", bill_id + "_v" + str(existing["version"]), existing)
            task = unit.get("tasks", existing["task_id"], False) if existing and existing.get("task_id") else None
            if not task:
                task = self.agent._new_task(unit, "Review " + request.provider + " bill", "utilities", skill="utility_import")
            payload["task_id"] = task["id"]
            bill = unit.save("bills", bill_id, payload, existing["version"] if existing else None)
            account = unit.get("accounts", "cash")
            unit.save("accounts", "cash", account, account["version"])  # Budget revision; cash never changes.
            next_id = "next_" + bill_id
            next_action = unit.get("next_actions", next_id, False)
            next_payload = {"title": "Review bill increase" if comparable and comparison["change_minor"] > 0 else "Review upcoming utility bill",
                            "bill_id": bill_id, "task_id": task["id"], "due_at": request.due_at, "status": "open",
                            "source_id": imported["source_id"], "updated_at": now(), "provenance": "simulated"}
            unit.save("next_actions", next_id, next_payload, next_action["version"] if next_action else None)
            after = self.agent.context(unit)["budget"]["available_minor"]
            result = {"bill": bill, "duplicate": False, "allowance_before": before, "allowance_after": after, "comparison": comparison, "next_action_id": next_id}
            unit.save("bill_imports", import_id, {**imported, "status": "confirmed", "bill_id": bill_id}, imported["version"])
            task = unit.save("tasks", task["id"], {**task, "status": "completed", "updated_at": now(),
                "checkpoint": {"bill_id": bill_id, "source_id": imported["source_id"], "allowance_before": before, "allowance_after": after, "comparison": comparison}}, task["version"])
            self.agent.event(unit, task, "bill_revised" if existing else "bill_imported", {**result, "bill": {"bill_id": bill_id, "source_id": imported["source_id"], "version": bill["version"]}})
            self.agent.event(unit, task, "commitment_updated", {"bill_id": bill_id, "amount_minor": request.amount_minor, "allowance_before": before, "allowance_after": after})
            self.agent.event(unit, task, "next_action_created", {"next_action_id": next_id, "deduplicated": bool(next_action)})
            self.agent.event(unit, task, "task_completed", {"bill_id": bill_id})
            return result

    def seed(self, unit):
        self.agent.intent.seed_history(unit)
        if unit.all("merchant_offers"):
            return
        stamp = datetime.fromisoformat(now())
        start, end = (stamp-timedelta(days=1)).isoformat(), (stamp+timedelta(days=14)).isoformat()
        base = {"merchant_id": "demo-home", "discount_type": "percent", "value": 15, "min_spend_minor": 5000,
                "minimum_basis": "before_discount", "starts_at": start, "expires_at": end, "max_discount_minor": None,
                "restrictions": "none", "stackability": "disallowed", "excluded_products": [], "excluded_categories": []}
        variants = [
            ("HOME15", {}, "A useful offer for your workspace"),
            ("OLD20", {"value": 20, "expires_at": (stamp-timedelta(days=1)).isoformat(), "starts_at": (stamp-timedelta(days=8)).isoformat()}, "Last week's offer"),
            ("BIG25", {"value": 25, "min_spend_minor": 50000}, "A larger minimum spend"),
            ("NOARC20", {"value": 20, "excluded_products": ["arc-light"]}, "Selected products only"),
            ("FIRST30", {"value": 30, "restrictions": "first_purchase"}, "First purchase only"),
            ("MYSTERY", {}, "An incomplete offer"),
            ("SAVE10", {"value": 10}, "A separate non-stackable offer"),
            ("ELSE15", {"merchant_id": "another-merchant"}, "An unrelated merchant"),
        ]
        for code, changes, subject in variants:
            terms = {**base, **changes, "code": code}
            unit.save("merchant_offers", code, terms)
            text = "\n".join([
                "Merchant: " + terms["merchant_id"], "Code: " + code, "Currency: USD",
                "Discount_type: " + terms["discount_type"], "Value: " + str(terms["value"]),
                "Minimum_spend: " + str(terms["min_spend_minor"]//100) + ".00",
                "Minimum_basis: " + terms["minimum_basis"], "Starts_at: " + terms["starts_at"], "Expires_at: " + terms["expires_at"],
                "Maximum_discount: none", "Restrictions: " + ("unknown" if code == "MYSTERY" else terms["restrictions"]),
                "Stackability: disallowed", "Excluded_products: " + (",".join(terms["excluded_products"]) or "none"),
                "Excluded_categories: none",
            ])
            self.email(unit, text, subject, "offers@example.invalid")
        for key in ("electricity", "internet"):
            bill = unit.get("bills", key)
            provider = "Northstar Energy" if key == "electricity" else "Demo Internet"
            unit.save("bills", key, {**bill, "provider": provider, "account_ref": "demo-account",
                "invoice_id": "current-" + key, "period_start": (stamp-timedelta(days=30)).date().isoformat(),
                "period_end": stamp.date().isoformat(), "status": "unpaid"}, bill["version"])
        previous = unit.get("bills", "electricity")
        unit.save("bills", "electricity-previous", {**previous, "invoice_id": "previous-electricity",
            "amount_minor": 9400, "paid": True, "status": "paid",
            "period_start": (stamp-timedelta(days=61)).date().isoformat(), "period_end": (stamp-timedelta(days=31)).date().isoformat()})
        for index in range(8):
            unit.save("products", "sample-light-" + str(index+1), {
                **unit.get("products", "fold-light"), "name": ["Beam", "Pivot", "Line", "Pebble", "Studio", "Orbit", "Rise", "Slate"][index] + " desk light",
                "price_minor": 10500+index*1200, "tax_minor": (10500+index*1200)*9//100,
                "source_id": "fixture:catalog-" + str(index+1), "stock": 0 if index == 6 else 4,
            })

        self.agent.intent.seed_history(unit)

    def sample_bill(self):
        stamp = datetime.fromisoformat(now())
        return "\n".join(["Provider: Northstar Energy", "Account_ref: demo-account", "Invoice_id: current-electricity",
            "Period_start: " + (stamp-timedelta(days=30)).date().isoformat(), "Period_end: " + stamp.date().isoformat(),
            "Amount: 148.00", "Currency: USD", "Due_at: " + (stamp+timedelta(days=3)).date().isoformat(),
            "Status: autopay_scheduled"])
