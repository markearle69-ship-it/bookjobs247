"""Web Push notifications to the owner's installed PWA (Android, desktop, and
iPhone/iPad on iOS 16.4+ once added to the home screen)."""

import json
import logging

from pywebpush import WebPushException, webpush
from sqlalchemy.orm import Session

from .config import settings
from .models import Account, Call, PushSubscription
from .phone import pretty

log = logging.getLogger(__name__)


def send_to_account(db: Session, account: Account, title: str, body: str, url: str = "/app",
                    urgent: bool = False) -> int:
    if not settings.vapid_private_key:
        return 0
    sent = 0
    for sub in list(account.push_subscriptions):
        try:
            webpush(
                subscription_info={"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
                data=json.dumps({"title": title, "body": body, "url": url, "urgent": urgent}),
                vapid_private_key=settings.vapid_private_key,
                vapid_claims={"sub": settings.vapid_subject},
                ttl=24 * 3600,
                timeout=10,
                # Ask push services to deliver immediately, even to a sleeping phone.
                headers={"Urgency": "high"},
            )
            sent += 1
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            if status in (404, 410):  # device unsubscribed / app removed
                db.delete(sub)
            else:
                log.warning("Push failed for subscription %s: %s", sub.id, exc)
    db.commit()
    return sent


# Emergency calls are re-sent after these many seconds until the owner opens them.
EMERGENCY_REPEATS = (5 * 60, 15 * 60)


def _caller(call: Call) -> str:
    return call.caller_name or pretty(call.from_number) or "Unknown caller"


def notify_call(db: Session, call: Call) -> None:
    if call.notified:
        return
    urgent = call.urgency == "emergency"
    if call.kind == "voicemail":
        title = f"Voicemail from {_caller(call)}"
    elif urgent:
        title = f"🚨 EMERGENCY: {_caller(call)}"
    else:
        title = f"New call: {_caller(call)}"
    body = call.job_description or call.summary or "Tap to see the details."
    send_to_account(db, call.account, title, body[:180], url=f"/app/calls/{call.id}", urgent=urgent)
    call.notified = True
    db.commit()
    if urgent:
        from .followups import schedule_emergency_reminder
        for delay in EMERGENCY_REPEATS:
            schedule_emergency_reminder(call.id, delay)


def remind_emergency(db: Session, call: Call) -> bool:
    """Re-send an emergency alert if the owner still hasn't opened the call."""
    if call.is_read or call.handled:
        return False
    body = call.job_description or call.summary or "Tap to see the details."
    send_to_account(db, call.account, f"🚨 STILL WAITING: {_caller(call)}", body[:180],
                    url=f"/app/calls/{call.id}", urgent=True)
    return True
