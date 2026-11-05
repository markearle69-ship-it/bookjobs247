"""Transactional email: password resets, welcome, operator alerts.
Postmark API if POSTMARK_API_TOKEN is set, otherwise plain SMTP."""

import logging
import smtplib
from email.message import EmailMessage

import httpx

from .config import settings

log = logging.getLogger(__name__)


def send_email(to: str, subject: str, body: str) -> bool:
    if not to or not settings.email_from:
        log.warning("Email not configured; would have sent %r to %s", subject, to)
        return False
    try:
        if settings.postmark_api_token:
            resp = httpx.post(
                "https://api.postmarkapp.com/email",
                headers={"X-Postmark-Server-Token": settings.postmark_api_token, "Accept": "application/json"},
                json={"From": settings.email_from, "To": to, "Subject": subject, "TextBody": body},
                timeout=10,
            )
            resp.raise_for_status()
            return True
        if settings.smtp_host:
            msg = EmailMessage()
            msg["From"], msg["To"], msg["Subject"] = settings.email_from, to, subject
            msg.set_content(body)
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as s:
                s.starttls()
                if settings.smtp_user:
                    s.login(settings.smtp_user, settings.smtp_password)
                s.send_message(msg)
            return True
    except Exception:
        log.exception("Failed to send email %r to %s", subject, to)
        return False
    log.warning("No email transport configured; would have sent %r to %s", subject, to)
    return False


def alert_admin(subject: str, body: str) -> None:
    if settings.admin_email:
        send_email(settings.admin_email, f"[BookJobs247 admin] {subject}", body)
