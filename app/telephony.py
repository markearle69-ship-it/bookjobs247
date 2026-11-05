"""Twilio: number provisioning (US buy / UK pool), TwiML, signature checks."""

from datetime import timedelta

from sqlalchemy.orm import Session
from twilio.base.exceptions import TwilioRestException
from twilio.request_validator import RequestValidator
from twilio.rest import Client
from twilio.twiml.voice_response import Dial, VoiceResponse

from .config import settings
from .models import Account, PoolNumber, utcnow

# A cancelled customer's UK number isn't re-issued for this long, so callers
# still forwarded by the old owner's phone don't reach a new business.
POOL_COOLDOWN = timedelta(days=30)

VOICES = {"GB": ("Polly.Amy", "en-GB"), "US": ("Polly.Joanna", "en-US")}


class ProvisioningError(Exception):
    pass


def client() -> Client:
    return Client(settings.twilio_account_sid, settings.twilio_auth_token)


def voice_webhook_url() -> str:
    return settings.url("/twilio/voice")


# ---------- signature validation ----------

def valid_twilio_request(url: str, params: dict, signature: str | None) -> bool:
    if not settings.twilio_validate_signatures:
        return True
    if not signature or not settings.twilio_auth_token:
        return False
    return RequestValidator(settings.twilio_auth_token).validate(url, params, signature)


# ---------- provisioning ----------

def provision_number(db: Session, account: Account) -> str:
    """Give the account a number pointed at our voice webhook. Idempotent."""
    if account.twilio_number:
        return account.twilio_number
    if account.country == "GB":
        number, sid = _assign_from_pool(db, account)
    else:
        number, sid = _buy_us_number(account)
    account.twilio_number = number
    account.twilio_number_sid = sid
    account.provisioning_error = None
    db.commit()
    return number


def _buy_us_number(account: Account) -> tuple[str, str]:
    c = client()
    try:
        candidates = []
        if account.area_code:
            candidates = c.available_phone_numbers("US").local.list(
                area_code=account.area_code, voice_enabled=True, limit=1)
        if not candidates:
            candidates = c.available_phone_numbers("US").local.list(voice_enabled=True, limit=1)
        if not candidates:
            raise ProvisioningError("Twilio has no US numbers available right now")
        bought = c.incoming_phone_numbers.create(
            phone_number=candidates[0].phone_number,
            voice_url=voice_webhook_url(),
            voice_method="POST",
            status_callback=settings.url("/twilio/status"),
            status_callback_method="POST",
            friendly_name=f"{settings.app_name} #{account.id} {account.business_name}"[:64],
        )
        return bought.phone_number, bought.sid
    except TwilioRestException as exc:
        raise ProvisioningError(f"Twilio number purchase failed: {exc.msg}") from exc


def _assign_from_pool(db: Session, account: Account) -> tuple[str, str]:
    cutoff = utcnow() - POOL_COOLDOWN
    candidates = (
        db.query(PoolNumber)
        .filter(PoolNumber.country == account.country, PoolNumber.account_id.is_(None))
        .order_by(PoolNumber.released_at.is_not(None), PoolNumber.id)
        .all()
    )
    pool = next((p for p in candidates if p.released_at is None or p.released_at <= cutoff), None)
    if pool is None:
        raise ProvisioningError("The UK number pool is empty - add numbers in /admin")
    try:
        client().incoming_phone_numbers(pool.twilio_sid).update(
            voice_url=voice_webhook_url(), voice_method="POST",
            status_callback=settings.url("/twilio/status"), status_callback_method="POST",
            friendly_name=f"{settings.app_name} #{account.id} {account.business_name}"[:64],
        )
    except TwilioRestException as exc:
        raise ProvisioningError(f"Couldn't point pool number {pool.phone_number} at {settings.app_name}: {exc.msg}") from exc
    pool.account_id = account.id
    pool.released_at = None
    return pool.phone_number, pool.twilio_sid


def release_number(db: Session, account: Account) -> None:
    """On cancellation: US numbers are released back to Twilio (stops the
    monthly fee); UK pool numbers return to the pool after a cooldown."""
    if not account.twilio_number:
        return
    pool = db.query(PoolNumber).filter(PoolNumber.account_id == account.id).first()
    if pool:
        pool.account_id = None
        pool.released_at = utcnow()
    elif account.twilio_number_sid:
        try:
            client().incoming_phone_numbers(account.twilio_number_sid).delete()
        except TwilioRestException as exc:
            if exc.status != 404:
                raise
    account.twilio_number = None
    account.twilio_number_sid = None
    db.commit()


def lookup_owned_number(phone_number: str) -> str:
    """For adding pool numbers: find the SID of a number already in your Twilio account."""
    found = client().incoming_phone_numbers.list(phone_number=phone_number, limit=1)
    if not found:
        raise ProvisioningError(f"{phone_number} isn't in your Twilio account - buy it there first")
    return found[0].sid


# ---------- TwiML ----------

def twiml_dial_agent(sip: str) -> str:
    """Connect the caller to the Retell agent. The action URL tells us how
    the dial went, so a failed connection can fall back to voicemail."""
    r = VoiceResponse()
    d = Dial(action=settings.url("/twilio/dial-done"))
    d.sip(sip)
    r.append(d)
    return str(r)


def twiml_voicemail(account: Account) -> str:
    voice, lang = VOICES.get(account.country, VOICES["US"])
    r = VoiceResponse()
    r.say(
        f"Hi, you've reached {account.business_name}. We can't get to the phone right now. "
        "Please leave your name, number, and what you need after the tone, and we'll call you back.",
        voice=voice, language=lang,
    )
    r.record(
        max_length=120,
        play_beep=True,
        timeout=5,
        action=settings.url("/twilio/voicemail-done"),
        recording_status_callback=settings.url("/twilio/recording"),
        recording_status_callback_event="completed",
        transcribe=True,
        transcribe_callback=settings.url("/twilio/transcription"),
    )
    return str(r)


def twiml_not_in_service() -> str:
    r = VoiceResponse()
    r.say("Sorry, this number is not in service.")
    r.hangup()
    return str(r)


def twiml_hangup() -> str:
    r = VoiceResponse()
    r.hangup()
    return str(r)
