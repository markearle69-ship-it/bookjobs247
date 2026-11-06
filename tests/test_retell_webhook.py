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
    assert "EMERGENCY" in no_side_effects["push"][0][1] and no_side_effects["push"][0][3] is True
    # Emergencies are always emailed too.
    assert any("EMERGENCY" in subj for _, subj, _ in no_side_effects["emails"])


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


def test_emergency_reminders_at_5_and_15_minutes_until_opened(db, no_side_effects):
    from datetime import timedelta

    from app.followups import run_due_jobs
    from app.models import utcnow
    account = make_account(db)
    now = utcnow()
    call = Call(account_id=account.id, kind="agent", urgency="emergency", caller_name="Ann", notified=True,
                notified_at=now - timedelta(minutes=6), status="complete")
    db.add(call)
    db.commit()
    run_due_jobs(db)
    assert call.reminders_sent == 1 and no_side_effects["push"][-1][1].startswith("🚨 STILL WAITING")
    run_due_jobs(db)
    assert call.reminders_sent == 1  # 15-minute one not due yet
    call.notified_at = now - timedelta(minutes=16)
    call.is_read = True  # owner opened it
    db.commit()
    before = len(no_side_effects["push"])
    run_due_jobs(db)
    assert len(no_side_effects["push"]) == before


def test_short_calls_are_free(db, monkeypatch):
    account = make_account(db)
    call = Call(account_id=account.id, kind="agent", duration_seconds=12)
    db.add(call)
    db.commit()
    monkeypatch.setattr("stripe.billing.MeterEvent.create", lambda **kw: (_ for _ in ()).throw(AssertionError))
    billing.report_usage(db, call)
    assert call.usage_reported and call.billed_minutes == 0


def test_email_backup_when_no_push(db, no_side_effects):
    from app.push import notify_call
    account = make_account(db)
    call = Call(account_id=account.id, kind="agent", caller_name="Bob", job_description="Fix gate", status="complete")
    db.add(call)
    db.commit()
    notify_call(db, call)
    assert no_side_effects["emails"][-1][1] == "New call: Bob" and "Fix gate" in no_side_effects["emails"][-1][2]
