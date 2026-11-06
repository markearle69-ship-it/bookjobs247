from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


ACTIVE_STATUSES = {"active", "trialing"}


class Account(Base):
    """One business owner = one account = one forwarding number."""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    # "US" or "GB" - decides currency, agent voice, and where the number comes from.
    country: Mapped[str] = mapped_column(String(2), default="US")

    # Business details, fed to the voice agent on every call.
    business_name: Mapped[str] = mapped_column(String(200))
    owner_name: Mapped[str] = mapped_column(String(120), default="")
    # What the phone is answered as ("Smith Plumbing") - defaults to business_name.
    answer_as: Mapped[str] = mapped_column(String(200), default="")
    # Optional first name the assistant introduces itself with ("this is Sarah").
    assistant_name: Mapped[str] = mapped_column(String(60), default="")
    voice_gender: Mapped[str] = mapped_column(String(8), default="female")  # female | male
    # Key into the trade library (TradeTemplate), or "other".
    trade_key: Mapped[str] = mapped_column(String(40), default="other")
    # Human description of the trade (the dropdown label, or what they typed for "other").
    trade: Mapped[str] = mapped_column(String(120), default="")
    services: Mapped[str] = mapped_column(Text, default="")
    service_area: Mapped[str] = mapped_column(String(255), default="")
    business_hours: Mapped[str] = mapped_column(String(255), default="")
    # The phone the owner forwards FROM (their mobile/business number).
    owner_phone: Mapped[str] = mapped_column(String(32), default="")
    # US only: preferred area code for their new number.
    area_code: Mapped[str] = mapped_column(String(3), default="")
    onboarding_complete: Mapped[bool] = mapped_column(Boolean, default=False)

    # The ON/OFF switch. ON = AI agent answers, OFF = plain voicemail.
    agent_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # Their Call Capturer number, which their phone forwards missed calls to.
    twilio_number: Mapped[str | None] = mapped_column(String(32), unique=True, index=True, nullable=True)
    twilio_number_sid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provisioning_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    number_assigned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Set the first time a call reaches their number, i.e. forwarding works.
    first_call_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # "You haven't set up forwarding yet" email, sent once if no calls arrive.
    forwarding_nudge_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # When the subscription ended. The number stays connected for a short
    # grace period (calls go to voicemail and the owner is emailed a
    # win-back), then it is released.
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Billing.
    stripe_customer_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    subscription_status: Mapped[str] = mapped_column(String(32), default="none")
    current_period_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    calls: Mapped[list["Call"]] = relationship(back_populates="account", order_by="Call.created_at.desc()")
    push_subscriptions: Mapped[list["PushSubscription"]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )

    @property
    def is_active(self) -> bool:
        return self.subscription_status in ACTIVE_STATUSES

    @property
    def greeting_name(self) -> str:
        return self.answer_as or self.business_name

    @property
    def currency(self) -> str:
        return "gbp" if self.country == "GB" else "usd"


class Call(Base):
    """A call that reached the owner's Call Capturer number - answered by the
    AI agent (kind="agent") or by voicemail (kind="voicemail")."""

    __tablename__ = "calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    kind: Mapped[str] = mapped_column(String(16))  # "agent" | "voicemail"
    status: Mapped[str] = mapped_column(String(16), default="in_progress")  # "in_progress" | "complete"

    twilio_call_sid: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    retell_call_id: Mapped[str | None] = mapped_column(String(128), unique=True, index=True, nullable=True)
    from_number: Mapped[str] = mapped_column(String(32), default="")

    # Details collected by the agent (or the voicemail transcript).
    caller_name: Mapped[str] = mapped_column(String(200), default="")
    callback_number: Mapped[str] = mapped_column(String(32), default="")
    caller_address: Mapped[str] = mapped_column(String(500), default="")
    job_description: Mapped[str] = mapped_column(Text, default="")
    urgency: Mapped[str] = mapped_column(String(32), default="")  # emergency | soon | flexible
    preferred_callback_time: Mapped[str] = mapped_column(String(200), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    transcript: Mapped[str] = mapped_column(Text, default="")
    recording_url: Mapped[str] = mapped_column(String(1000), default="")
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)

    # Billing: whole minutes reported to Stripe's meter for this call.
    billed_minutes: Mapped[int] = mapped_column(Integer, default=0)
    usage_reported: Mapped[bool] = mapped_column(Boolean, default=False)
    notified: Mapped[bool] = mapped_column(Boolean, default=False)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Background jobs (stored, so they survive restarts/deploys):
    # when to make sure this call is wrapped up and notified even if a
    # webhook never arrives, and how many emergency re-alerts were sent.
    followup_due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    reminders_sent: Mapped[int] = mapped_column(Integer, default=0)

    # Owner workflow.
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    handled: Mapped[bool] = mapped_column(Boolean, default=False)

    account: Mapped[Account] = relationship(back_populates="calls")

    @property
    def display_name(self) -> str:
        return self.caller_name or self.from_number or "Unknown caller"

    @property
    def best_number(self) -> str:
        return self.callback_number or self.from_number


class PushSubscription(Base):
    """A browser/phone that asked for push notifications (one per device)."""

    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    endpoint: Mapped[str] = mapped_column(String(1000), unique=True)
    p256dh: Mapped[str] = mapped_column(String(255))
    auth: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    account: Mapped[Account] = relationship(back_populates="push_subscriptions")


class PoolNumber(Base):
    """A UK number you bought in advance under your own Twilio regulatory
    bundle. UK signups are assigned one instantly instead of waiting days
    for per-customer bundle approval."""

    __tablename__ = "pool_numbers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    phone_number: Mapped[str] = mapped_column(String(32), unique=True)
    twilio_sid: Mapped[str] = mapped_column(String(64))
    country: Mapped[str] = mapped_column(String(2), default="GB")
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    # When a cancelled customer's number came back. It isn't handed out
    # again until a cooldown passes, so old forwarding doesn't reach a new
    # business.
    released_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TradeTemplate(Base):
    """Per-trade questions + emergency rules fed to the voice agent on each
    call. Seeded from app/trades.py, editable in /admin/trades."""

    __tablename__ = "trade_templates"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    label: Mapped[str] = mapped_column(String(120))
    group: Mapped[str] = mapped_column(String(120), default="")
    questions: Mapped[str] = mapped_column(Text, default="")
    emergency: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class WaitlistSignup(Base):
    """Someone asking to hear when a "coming soon" tool launches."""

    __tablename__ = "waitlist_signups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    product: Mapped[str] = mapped_column(String(40), index=True)
    trade: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ProcessedStripeEvent(Base):
    """Stripe retries webhooks, so each event id is processed once."""

    __tablename__ = "processed_stripe_events"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
