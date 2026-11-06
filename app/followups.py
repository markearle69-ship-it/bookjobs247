"""Background jobs, stored in the database so they survive restarts/deploys.

A small loop (started in main.py) calls run_due_jobs() every 30 seconds:

- Wrap up calls whose webhooks never arrived (caller hung up before the
  beep, Retell analysis failed...) so the owner still hears about them.
- Re-send emergency alerts at 5 and 15 minutes until the call is opened.
- Email owners whose number has had no calls for 3 days (forwarding not set up).
- Release numbers whose cancellation grace period has ended.
"""

import asyncio
import logging
from datetime import timedelta

from sqlalchemy.orm import Session

from .config import settings
from .db import SessionLocal
from .emails import send_email
from .models import ACTIVE_STATUSES, Account, Call, utcnow
from .push import EMERGENCY_REPEATS, notify_call, remind_emergency

log = logging.getLogger(__name__)

MISSED_SUMMARY = "Caller hung up without leaving a message."
FORWARDING_NUDGE_AFTER = timedelta(days=3)
CANCEL_GRACE = timedelta(days=7)
TICK_SECONDS = 30


def schedule(db: Session, call: Call, delay_seconds: float) -> None:
    """Make sure `call` is wrapped up and notified within `delay_seconds`."""
    due = utcnow() + timedelta(seconds=delay_seconds)
    if call.followup_due_at is None or due < call.followup_due_at:
        call.followup_due_at = due
        db.commit()


def finalize(db: Session, call: Call) -> None:
    if call.notified:
        return
    if call.kind == "voicemail" and not call.recording_url:
        call.summary = call.summary or MISSED_SUMMARY
    elif call.kind == "agent" and call.status == "in_progress" and not call.transcript:
        call.summary = call.summary or MISSED_SUMMARY
    call.status = "complete"
    call.followup_due_at = None
    db.commit()
    notify_call(db, call)


def _due_followups(db: Session, now) -> int:
    calls = (db.query(Call).filter(Call.notified.is_(False), Call.followup_due_at.is_not(None),
                                   Call.followup_due_at <= now).limit(100).all())
    for call in calls:
        finalize(db, call)
    return len(calls)


def _due_emergency_reminders(db: Session, now) -> int:
    calls = (db.query(Call).filter(Call.urgency == "emergency", Call.notified.is_(True),
                                   Call.is_read.is_(False), Call.handled.is_(False),
                                   Call.reminders_sent < len(EMERGENCY_REPEATS),
                                   Call.notified_at.is_not(None)).limit(100).all())
    sent = 0
    for call in calls:
        if now >= call.notified_at + timedelta(seconds=EMERGENCY_REPEATS[call.reminders_sent]):
            remind_emergency(db, call)
            call.reminders_sent += 1
            db.commit()
            sent += 1
    return sent


def _forwarding_nudges(db: Session, now) -> int:
    accounts = (db.query(Account).filter(Account.subscription_status.in_(ACTIVE_STATUSES),
                                         Account.twilio_number.is_not(None), Account.first_call_at.is_(None),
                                         Account.forwarding_nudge_sent_at.is_(None),
                                         Account.number_assigned_at.is_not(None),
                                         Account.number_assigned_at <= now - FORWARDING_NUDGE_AFTER).all())
    from .phone import pretty
    for a in accounts:
        send_email(
            a.email, f"Is {settings.app_name} set up? We haven't had any calls yet",
            f"Hi {a.owner_name or 'there'},\n\n"
            f"Your {settings.app_name} number {pretty(a.twilio_number)} hasn't received any calls yet. That usually\n"
            f"means missed-call forwarding isn't switched on on your phone.\n\n"
            f"It takes 30 seconds, with one-tap buttons here: {settings.url('/app/setup')}\n\n"
            f"Then test it: ring your own number from another phone and don't answer.\n")
        a.forwarding_nudge_sent_at = now
        db.commit()
    return len(accounts)


def _expired_grace_periods(db: Session, now) -> int:
    from .telephony import release_number
    accounts = (db.query(Account).filter(Account.cancelled_at.is_not(None), Account.twilio_number.is_not(None),
                                         Account.cancelled_at <= now - CANCEL_GRACE,
                                         Account.subscription_status.not_in(ACTIVE_STATUSES)).all())
    from .forwarding import off_code_hint
    for a in accounts:
        release_number(db, a)
        send_email(
            a.email, f"Your {settings.app_name} number has been switched off",
            f"Hi {a.owner_name or 'there'},\n\n"
            f"Your {settings.app_name} number has now been released. If your phone still forwards missed calls to it,\n"
            f"those callers will hear 'number not in service', so please turn forwarding off: {off_code_hint(a.country)}\n\n"
            f"Want to stop missing calls again? Restart any time: {settings.url('/app/subscribe')}\n")
    return len(accounts)


def run_due_jobs(db: Session | None = None) -> dict:
    own = db is None
    db = db or SessionLocal()
    now = utcnow()
    done = {}
    try:
        for name, job in (("followups", _due_followups), ("reminders", _due_emergency_reminders),
                          ("nudges", _forwarding_nudges), ("releases", _expired_grace_periods)):
            try:
                done[name] = job(db, now)
            except Exception:
                db.rollback()
                log.exception("Background job %s failed", name)
    finally:
        if own:
            db.close()
    return done


async def run_forever() -> None:
    while True:
        await asyncio.sleep(TICK_SECONDS)
        await asyncio.to_thread(run_due_jobs)
