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


def send_to_account(db: Session, account: Account, title: str, body: str, url: str = "/app") -> int:
    if not settings.vapid_private_key:
        return 0
    sent = 0
    for sub in list(account.push_subscriptions):
        try:
            webpush(
                subscription_info={"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
                data=json.dumps({"title": title, "body": body, "url": url}),
                vapid_private_key=settings.vapid_private_key,
                vapid_claims={"sub": settings.vapid_subject},
                ttl=24 * 3600,
                timeout=10,
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


def notify_call(db: Session, call: Call) -> None:
    if call.notified:
        return
    who = call.caller_name or pretty(call.from_number) or "Unknown caller"
    if call.kind == "voicemail":
        title = f"Voicemail from {who}"
    else:
        title = f"{'🚨 URGENT: ' if call.urgency == 'emergency' else ''}New call: {who}"
    body = call.job_description or call.summary or "Tap to see the details."
    send_to_account(db, call.account, title, body[:180], url=f"/app/calls/{call.id}")
    call.notified = True
    db.commit()
