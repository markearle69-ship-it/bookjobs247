from app import retell
from app.models import Call
from tests.helpers import client, db, fresh_db, make_account, no_side_effects  # noqa: F401


def post_voice(client, to="+15557654321", sid="CA1"):
    return client.post("/twilio/voice", data={"To": to, "From": "+15551112222", "CallSid": sid})


def test_unknown_number_not_in_service(client, db):
    r = post_voice(client, to="+19999999999")
    assert "not in service" in r.text


def test_agent_on_dials_retell_with_business_details(client, db, monkeypatch):
    account = make_account(db)
    captured = {}

    def fake_register(acct, from_number, to_number, row_id, sid):
        captured.update(vars=retell.dynamic_variables(acct), row_id=row_id, sid=sid)
        return "call_abc"

    monkeypatch.setattr(retell, "register_phone_call", fake_register)
    r = post_voice(client)
    assert "<Sip>sip:call_abc@sip.retellai.com</Sip>" in r.text
    assert 'action="https://bj.example.com/twilio/dial-done"' in r.text
    assert captured["vars"]["business_name"] == "Joe's Plumbing"
    call = db.query(Call).one()
    assert call.kind == "agent" and call.retell_call_id == "call_abc" and call.from_number == "+15551112222"
    db.refresh(account)
    assert account.first_call_at is not None


def test_agent_off_goes_to_voicemail(client, db, monkeypatch):
    make_account(db, agent_enabled=False)
    monkeypatch.setattr(retell, "register_phone_call", lambda *a: (_ for _ in ()).throw(AssertionError("no")))
    r = post_voice(client)
    assert "<Record" in r.text and "Joe's Plumbing" in r.text
    assert db.query(Call).one().kind == "voicemail"


def test_past_due_goes_to_voicemail(client, db, monkeypatch):
    make_account(db, subscription_status="past_due")
    r = post_voice(client)
    assert "<Record" in r.text


def test_retell_failure_falls_back_to_voicemail(client, db, monkeypatch):
    make_account(db)

    def boom(*a):
        raise retell.RetellError("down")

    monkeypatch.setattr(retell, "register_phone_call", boom)
    r = post_voice(client)
    assert "<Record" in r.text
    assert db.query(Call).one().kind == "voicemail"


def test_failed_dial_falls_back_to_voicemail(client, db, monkeypatch):
    make_account(db)
    monkeypatch.setattr(retell, "register_phone_call", lambda *a: "call_x")
    post_voice(client)
    r = client.post("/twilio/dial-done", data={"CallSid": "CA1", "DialCallStatus": "failed"})
    assert "<Record" in r.text
    r = client.post("/twilio/dial-done", data={"CallSid": "CA1", "DialCallStatus": "completed"})
    assert "<Hangup" in r.text


def test_voicemail_recording_and_transcription(client, db, no_side_effects):
    make_account(db, agent_enabled=False)
    post_voice(client)
    client.post("/twilio/recording", data={"CallSid": "CA1", "RecordingUrl": "https://api.twilio.com/rec/RE1",
                                           "RecordingDuration": "12"})
    call = db.query(Call).one()
    assert call.status == "complete" and call.recording_url.endswith("RE1") and call.notified
    assert no_side_effects["push"][0][1].startswith("Voicemail from")
    client.post("/twilio/transcription", data={"CallSid": "CA1", "TranscriptionStatus": "completed",
                                               "TranscriptionText": "Hi it's Ann, my tap is leaking"})
    db.refresh(call)
    assert call.summary == "Hi it's Ann, my tap is leaking"


def test_hangup_before_message_is_marked_missed(client, db, no_side_effects):
    make_account(db, agent_enabled=False)
    post_voice(client)
    client.post("/twilio/status", data={"CallSid": "CA1", "CallStatus": "completed"})
    assert no_side_effects["scheduled"]
    from app.followups import MISSED_SUMMARY, finalize
    finalize(no_side_effects["scheduled"][0][0])
    call = db.query(Call).one()
    db.refresh(call)
    assert call.summary == MISSED_SUMMARY and call.notified


def test_twilio_signature_enforced(client, db, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "twilio_validate_signatures", True)
    make_account(db)
    assert post_voice(client).status_code == 403
