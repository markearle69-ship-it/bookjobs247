"""Web Push notifications to the owner's installed PWA (Android, desktop, and
iPhone/iPad on iOS 16.4+ once added to the home screen)."""

import json
import logging

from pywebpush import WebPushException, webpush
from sqlalchemy.orm import Session

from .config import settings
from .emails import send_email
from .models import Account, Call, PushSubscription, utcnow
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


# Emergency calls are re-sent after these many seconds (from the first
# alert) until the owner opens them. Driven by followups.run_due_jobs.
EMERGENCY_REPEATS = (5 * 60, 15 * 60)


def _caller(call: Call) -> str:
    return call.caller_name or pretty(call.from_number) or "Unknown caller"


def _call_email_body(call: Call) -> str:
    lines = [f"Caller: {_caller(call)}"]
    if call.best_number:
        lines.append(f"Call back on: {pretty(call.best_number)}")
    if call.caller_address:
        lines.append(f"Address / area: {call.caller_address}")
    if call.job_description:
        lines.append(f"Job: {call.job_description}")
    if call.preferred_callback_time:
        lines.append(f"Best time: {call.preferred_callback_time}")
    if call.summary and call.summary != call.job_description:
        lines.append(f"\n{call.summary}")
    return "\n".join(lines)


def notify_call(db: Session, call: Call) -> None:
    """Tell the owner about a finished call: push to their phone, plus email
    if they have no push set up or it's an emergency. Cancelled accounts in
    their grace period get a win-back email instead."""
    if call.notified:
        return
    account = call.account
    call.notified = True
    call.notified_at = utcnow()
    db.commit()

    if not account.is_active and account.cancelled_at:
        _winback_email(account, call)
        return

    urgent = call.urgency == "emergency"
    if call.kind == "voicemail":
        title = f"Voicemail from {_caller(call)}"
    elif urgent:
        title = f"🚨 EMERGENCY: {_caller(call)}"
    else:
        title = f"New call: {_caller(call)}"
    body = call.job_description or call.summary or "Tap to see the details."
    pushed = send_to_account(db, account, title, body[:180], url=f"/app/calls/{call.id}", urgent=urgent)
    if urgent or not pushed:
        send_email(account.email, title,
                   _call_email_body(call) + f"\n\nOpen the call: {settings.url(f'/app/calls/{call.id}')}\n"
                   + ("" if pushed else "\nTip: add the app to your home screen and turn on notifications "
                                        "to get these instantly on your phone.\n"))


def _winback_email(account: Account, call: Call) -> None:
    from .forwarding import off_code_hint
    send_email(
        account.email, f"You missed a call from {_caller(call)}",
        f"Hi {account.owner_name or 'there'},\n\n"
        f"Someone just called and your phone forwarded them to your old {settings.app_name} number.\n"
        f"Because your plan has ended, they only reached voicemail:\n\n{_call_email_body(call)}\n\n"
        f"Never miss a call again: restart {settings.app_name} in one tap and your assistant picks up "
        f"straight away, same number, no setup: {settings.url('/app/subscribe')}\n\n"
        f"Or, if you don't want this any more, turn off forwarding on your phone: "
        f"{off_code_hint(account.country)}\n"
        f"Your {settings.app_name} number will be switched off a few days after your plan ended.\n")


def remind_emergency(db: Session, call: Call) -> bool:
    """Re-send an emergency alert if the owner still hasn't opened the call."""
    if call.is_read or call.handled:
        return False
    body = call.job_description or call.summary or "Tap to see the details."
    send_to_account(db, call.account, f"🚨 STILL WAITING: {_caller(call)}", body[:180],
                    url=f"/app/calls/{call.id}", urgent=True)
    return True
