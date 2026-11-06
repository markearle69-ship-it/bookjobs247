"""Stripe: Checkout signup, customer portal, usage metering, subscription sync.

Each subscription has two prices: a flat monthly fee and a metered price
tied to a Billing Meter, with graduated tiers (first 30 minutes free, then
the overage rate). We send one meter event per answered call with its
rounded-up minutes; Stripe works out the bill.
"""

import logging
import math
from datetime import datetime, timezone

import stripe
from sqlalchemy.orm import Session

from .config import settings
from .models import Account, Call, ProcessedStripeEvent
from .plans import stripe_prices_for

log = logging.getLogger(__name__)

# Calls shorter than this are never charged.
FREE_CALL_SECONDS = 20


def _configure() -> None:
    stripe.api_key = settings.stripe_secret_key


def _ts(value) -> datetime | None:
    if not value:
        return None
    return datetime.fromtimestamp(int(value), tz=timezone.utc).replace(tzinfo=None)


def create_checkout_session(account: Account) -> str:
    _configure()
    base_price, usage_price = stripe_prices_for(account.country)
    if not base_price or not usage_price:
        raise RuntimeError(f"Stripe prices for {account.country} not configured")
    if not account.stripe_customer_id:
        customer = stripe.Customer.create(
            email=account.email, name=account.business_name, metadata={"account_id": str(account.id)})
        account.stripe_customer_id = customer.id
    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=account.stripe_customer_id,
        client_reference_id=str(account.id),
        line_items=[{"price": base_price, "quantity": 1}, {"price": usage_price}],
        success_url=settings.url("/billing/success?session_id={CHECKOUT_SESSION_ID}"),
        cancel_url=settings.url("/app/subscribe"),
        subscription_data={"metadata": {"account_id": str(account.id)}},
        allow_promotion_codes=True,
    )
    return session.url


def create_portal_session(account: Account) -> str:
    _configure()
    session = stripe.billing_portal.Session.create(
        customer=account.stripe_customer_id, return_url=settings.url("/app/settings"))
    return session.url


def sync_subscription(account: Account, sub) -> None:
    """Copy status + current period from a Stripe Subscription object."""
    account.stripe_subscription_id = sub["id"]
    account.subscription_status = sub["status"]
    # Newer API versions moved the period onto subscription items.
    start = sub.get("current_period_start")
    end = sub.get("current_period_end")
    items = (sub.get("items") or {}).get("data") or []
    if not start and items:
        start = items[0].get("current_period_start")
        end = items[0].get("current_period_end")
    account.current_period_start = _ts(start)
    account.current_period_end = _ts(end)
    if account.is_active:
        account.cancelled_at = None  # restarted (possibly within the grace period: same number kept)


def retrieve_subscription(subscription_id: str):
    _configure()
    return stripe.Subscription.retrieve(subscription_id)


def confirm_checkout(db: Session, session_id: str, account: Account) -> bool:
    """Called from the success redirect so the owner isn't left waiting on
    the webhook. Safe to run alongside the webhook (both are idempotent)."""
    _configure()
    session = stripe.checkout.Session.retrieve(session_id, expand=["subscription"])
    if session.get("client_reference_id") != str(account.id) or not session.get("subscription"):
        return False
    sync_subscription(account, session["subscription"])
    db.commit()
    return account.is_active


def report_usage(db: Session, call: Call) -> None:
    """Send this call's minutes to the Stripe meter, once."""
    if call.usage_reported or call.kind != "agent" or call.duration_seconds <= 0:
        return
    if call.duration_seconds < FREE_CALL_SECONDS:
        # Robocalls, wrong numbers and instant hang-ups don't use the owner's minutes.
        call.billed_minutes = 0
        call.usage_reported = True
        db.commit()
        return
    account = call.account
    if not account.stripe_customer_id:
        return
    minutes = max(1, math.ceil(call.duration_seconds / 60))
    _configure()
    try:
        stripe.billing.MeterEvent.create(
            event_name=settings.stripe_meter_event_name,
            payload={"stripe_customer_id": account.stripe_customer_id, "value": str(minutes)},
            # Idempotency: Stripe drops a repeat of the same identifier.
            identifier=f"bj-call-{call.id}",
        )
    except stripe.StripeError:
        log.exception("Meter event failed for call %s - retry from /admin", call.id)
        return
    call.billed_minutes = minutes
    call.usage_reported = True
    db.commit()


def construct_event(payload: bytes, signature: str | None):
    _configure()
    return stripe.Webhook.construct_event(payload, signature or "", settings.stripe_webhook_secret)


def already_processed(db: Session, event_id: str) -> bool:
    if db.get(ProcessedStripeEvent, event_id):
        return True
    db.add(ProcessedStripeEvent(id=event_id))
    return False
