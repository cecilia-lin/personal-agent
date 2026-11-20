"""Regression cases found while reviewing the shared foundation."""
from itertools import count

import pytest

from test_journey import client, settings


def test_audit_keeps_execution_order_when_demo_clock_is_fixed(client, monkeypatch):
    from app.services import agent

    monkeypatch.setenv("DEMO_NOW", "2026-11-20T12:00:00+00:00")
    original_uid = agent.uid
    ids = count(999, -1)
    # Reverse lexical IDs make timestamp + random UUID sorting fail deterministically.
    monkeypatch.setattr(agent, "uid", lambda prefix: f"evt_{next(ids)}" if prefix == "evt" else original_uid(prefix))
    task = client.post("/api/tasks", json={"goal": "Find a repairable desk light"}).json()
    assert client.post(f"/api/tasks/{task['id']}/run").status_code == 200
    audit = client.get(f"/api/tasks/{task['id']}/audit").json()["audit"]
    assert [event["kind"] for event in audit] == ["task_started", "budget_calculated", "candidates_checked"]
    assert [event["sequence"] for event in audit] == sorted(event["sequence"] for event in audit)


@pytest.mark.parametrize("content_type,body", [
    ("text/html", "<html><body>Code: HOME15</body></html>"),
    ("application/octet-stream", "binary payload"),
    ("image/png", "not a plain-text email"),
])
def test_non_plain_email_bodies_are_rejected_without_saving_offers(client, content_type, body):
    before = len(client.get("/api/dashboard").json()["offers"])
    text = f"From: offers@example.invalid\nSubject: Offer\nMIME-Version: 1.0\nContent-Type: {content_type}\n\n{body}"
    response = client.post("/api/imports/email", json={"text": text, "filename": "offer.eml"})
    assert response.status_code == 422
    assert "plain-text" in response.json()["detail"]
    assert len(client.get("/api/dashboard").json()["offers"]) == before


@pytest.mark.parametrize("body", [
    {"goal": "   "},
    {"goal": "A desk light", "category": "   "},
])
def test_blank_intention_fields_are_rejected(client, body):
    assert client.post("/api/tasks", json=body).status_code == 422


def test_blank_source_is_rejected_and_valid_source_text_is_preserved(client):
    assert client.post("/api/imports/email", json={"text": "   "}).status_code == 422
    text = "\nMerchant: demo-home\nCode: UNKNOWN\n\n"
    response = client.post("/api/imports/email", json={"text": text})
    assert response.status_code == 200
    assert response.json()["source"]["raw_text"] == text


def test_bill_identity_cannot_be_whitespace_only(client):
    sample = client.get("/api/dashboard").json()["sample_bill"]
    imported = client.post("/api/imports/bill", json={"text": sample}).json()
    response = client.post(f"/api/imports/bill/{imported['id']}/confirm", json={**imported["fields"], "provider": "   "})
    assert response.status_code == 422


def test_email_content_type_is_checked_without_from_header(client):
    response = client.post("/api/imports/email", json={
        "text": "Content-Type: text/html\n\n<b>Code: HOME15</b>", "filename": "offer.eml",
    })
    assert response.status_code == 422


def test_unknown_email_charset_returns_validation_error(client):
    response = client.post("/api/imports/email", json={
        "text": 'Content-Type: text/plain; charset="unsupported-intent-charset"\n\nCode: HOME15',
        "filename": "offer.eml",
    })
    assert response.status_code == 422


def test_plain_text_email_still_imports(client):
    response = client.post("/api/imports/email", json={
        "text": "From: offers@example.invalid\nSubject: Example\nContent-Type: text/plain\n\nMerchant: demo-home\nCode: NEWCODE",
        "filename": "offer.eml",
    })
    assert response.status_code == 200
    assert response.json()["offer"]["code"] == "NEWCODE"
    assert response.json()["offer"]["unknowns"]


def test_multipart_email_uses_only_its_plain_text_body(client):
    from email.message import EmailMessage

    message = EmailMessage()
    message["From"] = "offers@example.invalid"
    message.set_content("Merchant: demo-home\nCode: PLAINCODE")
    message.add_alternative("<b>Code: HTMLCODE</b>", subtype="html")
    response = client.post("/api/imports/email", json={"text": message.as_string(), "filename": "offer.eml"})
    assert response.status_code == 200
    assert response.json()["offer"]["code"] == "PLAINCODE"
