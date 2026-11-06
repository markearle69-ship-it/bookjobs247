import json
import logging
import math

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from . import billing, followups, retell, telephony
from .activation import ensure_number
from .emails import send_email
from .config import settings
from .db import get_db
from .models import Account, Call, TradeTemplate, utcnow
from .phone import normalize
from .push import notify_call

log = logging.getLogger(__name__)
router = APIRouter()

XML = "application/xml"


async def _twilio_form(request: Request) -> dict:
    form = dict(await request.form())
    url = settings.url(request.url.path)
    if request.url.query:
        url += "?" + request.url.query
    if not telephony.valid_twilio_request(url, form, request.headers.get("X-Twilio-Signature")):
        raise HTTPException(status_code=403, detail="Bad Twilio signature")
    return form


def _twiml(body: str) -> Response:
    return Response(content=body, media_type=XML)


def _start_voicemail(db: Session, call: Call, account: Account) -> Response:
    call.kind = "voicemail"
    db.commit()
    return _twiml(telephony.twiml_voicemail(account))


# ---------------------------------------------------------------- Twilio

@router.post("/twilio/voice")
async def twilio_voice(request: Request, db: Session = Depends(get_db)):
    """A forwarded call has reached a Call Keeper number."""
    form = await _twilio_form(request)
    to_number, from_number, call_sid = form.get("To", ""), form.get("From", ""), form.get("CallSid", "")

    account = db.query(Account).filter(Account.twilio_number == to_number).first()
    if account is None:
        return _twiml(telephony.twiml_not_in_service())

    if account.first_call_at is None:
        account.first_call_at = utcnow()

    # Some networks pass the owner's own number (or "anonymous") as the
    # caller ID on forwarded calls. Then we don't know who called, so the
    # assistant is told to get and confirm a callback number.
    caller_known = _real_caller_id(from_number, account)
    call = db.query(Call).filter(Call.twilio_call_sid == call_sid).first() if call_sid else None
    if call is None:
        call = Call(account_id=account.id, kind="agent", twilio_call_sid=call_sid,
                    from_number=from_number if caller_known else "")
        db.add(call)
        db.commit()

    # Switched OFF, or not paying (past due etc.): plain voicemail. We still
    # take the message so the owner never loses a lead.
    if not account.agent_enabled or not account.is_active:
        return _start_voicemail(db, call, account)

    try:
        trade = db.get(TradeTemplate, account.trade_key) if account.trade_key else None
        retell_call_id = retell.register_phone_call(account, from_number, to_number, call.id, call_sid, trade,
                                                    caller_known=caller_known)
    except retell.RetellError as exc:
        log.error("Retell register failed for account %s, falling back to voicemail: %s", account.id, exc)
        return _start_voicemail(db, call, account)

    call.retell_call_id = retell_call_id
    db.commit()
    return _twiml(telephony.twiml_dial_agent(retell.sip_uri(retell_call_id)))


def _real_caller_id(from_number: str, account: Account) -> bool:
    if not from_number or not from_number.startswith("+"):
        return False  # "anonymous", "Restricted", etc.
    digits = from_number.lstrip("+")
    if len(digits) < 8 or len(set(digits)) <= 2:
        return False  # placeholder numbers some carriers use for withheld IDs
    return normalize(from_number, account.country) not in (account.owner_phone, account.twilio_number)


@router.post("/twilio/dial-done")
async def twilio_dial_done(request: Request, db: Session = Depends(get_db)):
    form = await _twilio_form(request)
    status = form.get("DialCallStatus", "")
    call = db.query(Call).filter(Call.twilio_call_sid == form.get("CallSid", "")).first()
    if call and status in ("failed", "busy", "no-answer", "canceled"):
        log.error("Dial to Retell ended with %s for call %s; falling back to voicemail", status, call.id)
        return _start_voicemail(db, call, call.account)
    return _twiml(telephony.twiml_hangup())


@router.post("/twilio/voicemail-done")
async def twilio_voicemail_done(request: Request, db: Session = Depends(get_db)):
    form = await _twilio_form(request)
    call = db.query(Call).filter(Call.twilio_call_sid == form.get("CallSid", "")).first()
    if call and form.get("RecordingUrl") and int(form.get("RecordingDuration") or 0) > 0:
        call.recording_url = form["RecordingUrl"]
        call.duration_seconds = int(form.get("RecordingDuration") or 0)
        db.commit()
    return _twiml(telephony.twiml_hangup())


@router.post("/twilio/recording")
async def twilio_recording(request: Request, db: Session = Depends(get_db)):
    form = await _twilio_form(request)
    call = db.query(Call).filter(Call.twilio_call_sid == form.get("CallSid", "")).first()
    if call is None:
        return Response(status_code=204)
    duration = int(form.get("RecordingDuration") or 0)
    if duration > 0 and form.get("RecordingUrl"):
        call.recording_url = form["RecordingUrl"]
        call.duration_seconds = duration
        call.summary = call.summary or "Voicemail - transcript on its way."
    call.status = "complete"
    db.commit()
    if duration <= 0:
        followups.finalize(db, call)
    else:
        notify_call(db, call)
    return Response(status_code=204)


@router.post("/twilio/transcription")
async def twilio_transcription(request: Request, db: Session = Depends(get_db)):
    form = await _twilio_form(request)
    call = db.query(Call).filter(Call.twilio_call_sid == form.get("CallSid", "")).first()
    if call and form.get("TranscriptionStatus") == "completed":
        text = (form.get("TranscriptionText") or "").strip()
        call.transcript = text
        call.summary = text or "Voicemail (couldn't be transcribed - play the recording)."
        db.commit()
    elif call and call.summary.startswith("Voicemail - transcript"):
        call.summary = "Voicemail (couldn't be transcribed - play the recording)."
        db.commit()
    return Response(status_code=204)


@router.post("/twilio/status")
async def twilio_status(request: Request, db: Session = Depends(get_db)):
    """Number-level status callback: the whole call has ended. Give other
    webhooks a minute to land, then make sure the owner hears about it."""
    form = await _twilio_form(request)
    if form.get("CallStatus") in ("completed", "busy", "failed", "no-answer", "canceled"):
        call = db.query(Call).filter(Call.twilio_call_sid == form.get("CallSid", "")).first()
        if call and not call.notified:
            followups.schedule(db, call, 90)
    return Response(status_code=204)


# ---------------------------------------------------------------- Retell

@router.post("/webhooks/retell")
async def retell_webhook(request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    if not retell.verify_signature(raw, request.headers.get("x-retell-signature"), settings.retell_api_key):
        raise HTTPException(status_code=401, detail="Bad signature")
    try:
        payload = json.loads(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event = payload.get("event")
    data = payload.get("call") or {}
    call = db.query(Call).filter(Call.retell_call_id == data.get("call_id")).first()
    if call is None:
        row_id = (data.get("metadata") or {}).get("call_row_id")
        call = db.get(Call, int(row_id)) if row_id else None
    if call is None:
        log.warning("Retell %s for unknown call %s", event, data.get("call_id"))
        return Response(status_code=204)

    if event in ("call_ended", "call_analyzed"):
        duration_ms = data.get("duration_ms")
        if not duration_ms and data.get("start_timestamp") and data.get("end_timestamp"):
            duration_ms = data["end_timestamp"] - data["start_timestamp"]
        if duration_ms:
            call.duration_seconds = math.ceil(duration_ms / 1000)
        call.transcript = retell.format_transcript(data) or call.transcript
        call.recording_url = data.get("recording_url") or call.recording_url
        call.status = "connected" if event == "call_ended" else "complete"

    if event == "call_analyzed":
        analysis = data.get("call_analysis") or {}
        custom = analysis.get("custom_analysis_data") or {}
        call.summary = analysis.get("call_summary") or call.summary
        call.caller_name = str(custom.get("caller_name") or "")[:200]
        call.callback_number = str(custom.get("callback_number") or "")[:32]
        call.caller_address = str(custom.get("caller_address") or "")[:500]
        call.job_description = str(custom.get("job_description") or "")
        urgency = str(custom.get("urgency") or "")
        call.urgency = "" if urgency == "unknown" else urgency[:32]
        call.preferred_callback_time = str(custom.get("preferred_callback_time") or "")[:200]

    db.commit()

    if event in ("call_ended", "call_analyzed"):
        billing.report_usage(db, call)
    if event == "call_analyzed":
        notify_call(db, call)
    elif event == "call_ended":
        # Fallback in case analysis never arrives.
        followups.schedule(db, call, 120)
    return Response(status_code=204)


# ---------------------------------------------------------------- Stripe

@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    try:
        event = billing.construct_event(raw, request.headers.get("stripe-signature"))
    except Exception:
        raise HTTPException(status_code=400, detail="Bad signature")

    if billing.already_processed(db, event["id"]):
        return {"ok": True}

    etype = event["type"]
    obj = event["data"]["object"]

    if etype == "checkout.session.completed" and obj.get("mode") == "subscription":
        account = db.get(Account, int(obj.get("client_reference_id") or 0))
        if account:
            billing.sync_subscription(account, billing.retrieve_subscription(obj["subscription"]))
            db.commit()
            ensure_number(db, account)

    elif etype in ("customer.subscription.created", "customer.subscription.updated",
                   "customer.subscription.deleted"):
        account = db.query(Account).filter(Account.stripe_customer_id == obj.get("customer")).first()
        ended = etype == "customer.subscription.deleted" or obj.get("status") in ("canceled", "incomplete_expired")
        # A late event about an old subscription must not override a newer, active one.
        stale = (account is not None and account.is_active and account.stripe_subscription_id
                 and obj.get("id") != account.stripe_subscription_id and ended)
        if account and not stale:
            was_active = account.is_active
            billing.sync_subscription(account, obj)
            if ended:
                # Keep the number for a grace period: missed calls still reach
                # voicemail and the owner gets a win-back email for each one.
                # followups.run_due_jobs releases it afterwards.
                if account.cancelled_at is None and account.twilio_number:
                    account.cancelled_at = utcnow()
                    db.commit()
                    if was_active:
                        _cancellation_email(account)
            else:
                # Past-due/unpaid accounts keep their number (calls go to voicemail until they pay).
                db.commit()
                ensure_number(db, account)

    db.commit()
    return {"ok": True}


def _cancellation_email(account: Account) -> None:
    from .forwarding import off_code_hint
    send_email(
        account.email, f"Your {settings.app_name} plan has ended",
        f"Hi {account.owner_name or 'there'},\n\n"
        f"Your {settings.app_name} plan has ended. Your phone may still be forwarding missed calls to your\n"
        f"{settings.app_name} number, so for the next 7 days those callers will reach a voicemail and we'll email\n"
        f"you about each one, so you don't lose them.\n\n"
        f"Changed your mind? Restart in one tap, same number, no setup: {settings.url('/app/subscribe')}\n\n"
        f"Otherwise, please turn off call forwarding on your phone: {off_code_hint(account.country)}\n"
        f"After 7 days the number is switched off.\n")
