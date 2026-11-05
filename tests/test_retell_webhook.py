import hashlib
import hmac
import json
import time

from app import billing
from app.models import Call
from tests.helpers import client, db, fresh_db, make_account, no_side_effects  # noqa: F401


def signed(body: dict):
    raw = json.dumps(body).encode()
    ts = str(int(time.time() * 1000))
    d = hmac.new(b"retell-key", raw + ts.encode(), hashlib.sha256).hexdigest()
    return raw, {"x-retell-signature": f"v={ts},d={d}", "content-type": "application/json"}


def test_rejects_bad_signature(client):
    r = client.post("/webhooks/retell", content=b"{}", headers={"x-retell-signature": "v=1,d=bad"})
    assert r.status_code == 401


def test_call_analyzed_fills_details_notifies_and_bills_once(client, db, no_side_effects, monkeypatch):
    account = make_account(db)
    call = Call(account_id=account.id, kind="agent", retell_call_id="call_1", twilio_call_sid="CA1",
                from_number="+15551112222")
    db.add(call)
    db.commit()
    meter_events = []
    monkeypatch.setattr("stripe.billing.MeterEvent.create", lambda **kw: meter_events.append(kw))

    payload = {"event": "call_analyzed", "call": {
        "call_id": "call_1", "duration_ms": 95_000, "recording_url": "https://retell/rec.wav",
        "transcript_object": [{"role": "agent", "content": "Hi"}, {"role": "user", "content": "Leak"}],
        "call_analysis": {"call_summary": "Ann has a leak.", "custom_analysis_data": {
            "caller_name": "Ann", "callback_number": "", "caller_address": "12 High St",
            "job_description": "Leaking pipe under sink", "urgency": "emergency",
            "preferred_callback_time": "ASAP"}}}}
    raw, headers = signed(payload)
    assert client.post("/webhooks/retell", content=raw, headers=headers).status_code == 204
    raw, headers = signed(payload)  # Retell retry
    client.post("/webhooks/retell", content=raw, headers=headers)

    db.refresh(call)
    assert call.caller_name == "Ann" and call.urgency == "emergency" and call.status == "complete"
    assert call.transcript == "Assistant: Hi\nCaller: Leak"
    assert call.duration_seconds == 95 and call.billed_minutes == 2 and call.usage_reported
    assert len(meter_events) == 1
    assert meter_events[0]["payload"] == {"stripe_customer_id": "cus_1", "value": "2"}
    assert meter_events[0]["identifier"] == f"bj-call-{call.id}"
    assert len(no_side_effects["push"]) == 1
    assert "URGENT" in no_side_effects["push"][0][1]


def test_meter_failure_left_for_retry(client, db, monkeypatch):
    import stripe
    account = make_account(db)
    call = Call(account_id=account.id, kind="agent", retell_call_id="call_2", duration_seconds=30)
    db.add(call)
    db.commit()

    def fail(**kw):
        raise stripe.APIConnectionError("down")

    monkeypatch.setattr("stripe.billing.MeterEvent.create", fail)
    billing.report_usage(db, call)
    assert not call.usage_reported
