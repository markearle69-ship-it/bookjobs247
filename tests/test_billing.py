import json

import stripe

from app.models import Account, PoolNumber
from tests.helpers import client, db, fresh_db, make_account, no_side_effects  # noqa: F401


def send_event(client, monkeypatch, event):
    monkeypatch.setattr("app.billing.construct_event", lambda raw, sig: event)
    return client.post("/webhooks/stripe", content=json.dumps(event), headers={"stripe-signature": "x"})


def sub(status="active", customer="cus_1"):
    return {"id": "sub_1", "status": status, "customer": customer,
            "items": {"data": [{"current_period_start": 1767225600, "current_period_end": 1769904000}]}}


def test_bad_signature_rejected(client):
    r = client.post("/webhooks/stripe", content=b"{}", headers={"stripe-signature": "nope"})
    assert r.status_code == 400


def test_checkout_completed_activates_and_assigns_uk_pool_number(client, db, monkeypatch):
    account = make_account(db, country="GB", subscription_status="none", twilio_number=None)
    db.add(PoolNumber(phone_number="+447700900001", twilio_sid="PN1"))
    db.commit()
    monkeypatch.setattr("app.billing.retrieve_subscription", lambda sid: sub())
    updated = []

    class FakeNumber:
        def update(self, **kw):
            updated.append(kw)

    class FakeClient:
        def incoming_phone_numbers(self, sid):
            return FakeNumber()

    monkeypatch.setattr("app.telephony.client", lambda: FakeClient())
    event = {"id": "evt_1", "type": "checkout.session.completed",
             "data": {"object": {"mode": "subscription", "client_reference_id": str(account.id),
                                 "subscription": "sub_1"}}}
    assert send_event(client, monkeypatch, event).status_code == 200
    db.refresh(account)
    assert account.is_active and account.twilio_number == "+447700900001"
    assert account.current_period_start is not None
    assert updated[0]["voice_url"] == "https://bj.example.com/twilio/voice"
    assert updated[0]["status_callback"] == "https://bj.example.com/twilio/status"
    # duplicate delivery is ignored
    assert send_event(client, monkeypatch, event).status_code == 200


def test_empty_pool_records_error(client, db, monkeypatch):
    account = make_account(db, country="GB", subscription_status="none", twilio_number=None)
    event = {"id": "evt_2", "type": "customer.subscription.updated", "data": {"object": sub()}}
    send_event(client, monkeypatch, event)
    db.refresh(account)
    assert account.is_active and account.twilio_number is None
    assert "pool is empty" in account.provisioning_error


def test_subscription_deleted_returns_pool_number(client, db, monkeypatch):
    account = make_account(db, country="GB", twilio_number="+447700900001", twilio_number_sid="PN1")
    db.add(PoolNumber(phone_number="+447700900001", twilio_sid="PN1", account_id=account.id))
    db.commit()
    event = {"id": "evt_3", "type": "customer.subscription.deleted", "data": {"object": sub(status="canceled")}}
    send_event(client, monkeypatch, event)
    db.refresh(account)
    pool = db.query(PoolNumber).one()
    assert account.twilio_number is None and account.subscription_status == "canceled"
    assert pool.account_id is None and pool.released_at is not None


def test_past_due_keeps_number(client, db, monkeypatch):
    account = make_account(db)
    send_event(client, monkeypatch, {"id": "evt_4", "type": "customer.subscription.updated",
                                     "data": {"object": sub(status="past_due")}})
    db.refresh(account)
    assert account.subscription_status == "past_due" and account.twilio_number == "+15557654321"


def test_checkout_uses_country_prices(db, monkeypatch):
    from app import billing
    account = make_account(db, country="GB", stripe_customer_id=None)
    seen = {}
    monkeypatch.setattr(stripe.Customer, "create", lambda **kw: type("C", (), {"id": "cus_new"})())
    monkeypatch.setattr(stripe.checkout.Session, "create",
                        lambda **kw: seen.update(kw) or type("S", (), {"url": "https://checkout"})())
    assert billing.create_checkout_session(account) == "https://checkout"
    assert seen["line_items"] == [{"price": "price_base_gbp", "quantity": 1}, {"price": "price_usage_gbp"}]
    assert account.stripe_customer_id == "cus_new"
