from datetime import datetime, timezone
import os
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field

Money = Annotated[int, Field(ge=0, le=1_000_000_000, strict=True)]
Provenance = Literal["fixture", "simulated", "cached", "live"]

def now() -> str:
    fixed = os.getenv("DEMO_NOW", "")
    if fixed:
        stamp = datetime.fromisoformat(fixed.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError("DEMO_NOW must include a timezone offset.")
        return stamp.astimezone(timezone.utc).isoformat()
    return datetime.now(timezone.utc).isoformat()

class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")

class Account(Contract):
    spending_cap_minor: Money = 30000
    cap_used_minor: Money = 0
    spendable_minor: Money
    protected_minor: Money
    currency: Literal["USD"] = "USD"
    source_id: str
    provenance: Provenance = "fixture"
    observed_at: str

class Bill(Contract):
    name: str
    amount_minor: Money
    previous_minor: Money
    due_at: str
    paid: bool = False
    currency: Literal["USD"] = "USD"
    source_id: str
    provenance: Provenance = "fixture"
    observed_at: str

class Preferences(Contract):
    repairable: bool = True
    source_id: str = "explicit-demo-preference"
    provenance: Provenance = "fixture"
    updated_at: str

class Product(Contract):
    name: str
    category: str
    description: str
    price_minor: Money
    tax_minor: Money | None
    shipping_minor: Money | None
    stock: Annotated[int, Field(ge=0, strict=True)]
    repairable: bool
    currency: Literal["USD"] = "USD"
    source_id: str
    source_version: int = 1
    provenance: Provenance = "fixture"
    observed_at: str

class CreateTask(Contract):
    urgency: Literal["now", "soon", "flexible"] = "soon"
    target_price_minor: Money | None = None
    goal: str = Field(min_length=3, max_length=500)
    category: str = Field(default="desk-light", min_length=1, max_length=80)
    max_price_minor: Money | None = None

class PrepareProposal(Contract):
    product_id: str
    quantity: Annotated[int, Field(ge=1, le=5, strict=True)] = 1

class Decision(Contract):
    decision: Literal["approve", "reject"]
    terms_digest: str = Field(min_length=64, max_length=64)

class BudgetEdit(Contract):
    spending_cap_minor: Money = 30000
    spendable_minor: Money
    protected_minor: Money

class BillEdit(Contract):
    amount_minor: Money

class QuoteEdit(Contract):
    price_minor: Money
    stock: Annotated[int, Field(ge=0, strict=True)]

class PreferenceEdit(Contract):
    repairable: bool

class Problem(Exception):
    def __init__(self, message: str, status: int = 409):
        self.message = message
        self.status = status

def total(product: dict) -> int | None:
    if product["tax_minor"] is None or product["shipping_minor"] is None:
        return None
    return product["price_minor"] + product["tax_minor"] + product["shipping_minor"]


class SourceImport(Contract):
    text: str = Field(min_length=3, max_length=50000)
    filename: str = Field(default="pasted.txt", max_length=200)
    subject: str = Field(default="", max_length=300)
    sender: str = Field(default="", max_length=300)

class BillConfirmation(Contract):
    provider: str = Field(min_length=1, max_length=150)
    account_ref: str = Field(min_length=1, max_length=100)
    invoice_id: str = Field(min_length=1, max_length=100)
    period_start: str
    period_end: str
    amount_minor: Money
    currency: Literal["USD"]
    due_at: str
    status: Literal["unpaid", "autopay_scheduled"]

class SaveWatch(Contract):
    product_id: str | None = None
