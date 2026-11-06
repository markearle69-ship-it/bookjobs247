"""Retell AI: register an inbound call (custom telephony) and verify webhooks.

Flow: Twilio receives the forwarded call -> our /twilio/voice handler calls
register-phone-call with the business's details as dynamic variables ->
Retell returns a call_id -> TwiML dials sip:{call_id}@sip.retellai.com.
This needs no SIP trunk and lets us decide per call whether the agent
answers at all (the ON/OFF switch).
"""

import hashlib
import hmac
import re
import time

import httpx

from .config import settings
from .models import Account

API_BASE = "https://api.retellai.com"
_SIG_RE = re.compile(r"v=(\d+),d=(.+)")
_MAX_SKEW_MS = 5 * 60 * 1000


class RetellError(Exception):
    pass


SAFETY = {
    "GB": {"emergency_number": "999",
           "gas_emergency": "the National Gas Emergency line on 0800 111 999"},
    "US": {"emergency_number": "911",
           "gas_emergency": "911 or their gas company's emergency line, from outside the building"},
}


def agent_id_for(country: str, voice_gender: str = "female") -> str:
    male = voice_gender == "male"
    if country == "GB":
        return (settings.retell_agent_id_gb_male if male else "") or settings.retell_agent_id_gb_female
    return (settings.retell_agent_id_us_male if male else "") or settings.retell_agent_id_us_female


def build_greeting(account: Account) -> str:
    owner = account.owner_name or "the owner"
    intro = f"Hi, thanks for calling {account.greeting_name}"
    if account.assistant_name:
        intro += f", this is {account.assistant_name}"
    return f"{intro}. {owner} is out on a job right now, so I'm taking messages. What can we help you with?"


def _fill_safety(text: str, safety: dict) -> str:
    for k, v in safety.items():
        text = text.replace("{{" + k + "}}", v)
    return text


CALLER_KNOWN = "If they say to use the number they're calling from, that's fine."
CALLER_UNKNOWN = ("Their number did NOT come through on this call, so you must get a callback number and read it "
                  "back digit by digit. Do not accept 'this number'.")


def dynamic_variables(account: Account, trade=None, caller_known: bool = True) -> dict[str, str]:
    """`trade` is the account's TradeTemplate row, or None for "other"."""
    from .trades import OTHER_EMERGENCY, OTHER_QUESTIONS

    safety = SAFETY.get(account.country, SAFETY["US"])
    questions = (trade.questions if trade else "") or OTHER_QUESTIONS
    emergency = (trade.emergency if trade else "") or OTHER_EMERGENCY
    return {
        "greeting": build_greeting(account),
        "answer_as": account.greeting_name,
        "assistant_name": f" Your name is {account.assistant_name}." if account.assistant_name else "",
        "owner_name": account.owner_name or "the owner",
        "trade": account.trade or (trade.label if trade else "trades"),
        "services": account.services or "general work",
        "service_area": account.service_area or "the local area",
        "business_hours": account.business_hours or "not specified",
        "callback_rule": CALLER_KNOWN if caller_known else CALLER_UNKNOWN,
        "trade_questions": _fill_safety(questions, safety),
        "emergency_signs": _fill_safety(emergency, safety),
        **safety,
    }


def register_phone_call(account: Account, from_number: str, to_number: str, call_row_id: int,
                        twilio_call_sid: str, trade=None, caller_known: bool = True) -> str:
    """Returns the Retell call_id to dial. Raises RetellError on any failure
    so the caller can fall back to voicemail instead of dropping the call."""
    agent_id = agent_id_for(account.country, account.voice_gender)
    if not settings.retell_api_key or not agent_id:
        raise RetellError("Retell API key or agent id not configured")
    payload = {
        "agent_id": agent_id,
        "from_number": from_number,
        "to_number": to_number,
        "direction": "inbound",
        "metadata": {"account_id": account.id, "call_row_id": call_row_id, "twilio_call_sid": twilio_call_sid},
        "retell_llm_dynamic_variables": dynamic_variables(account, trade, caller_known),
    }
    try:
        # Short timeout: the caller is listening to silence while this runs.
        resp = httpx.post(
            f"{API_BASE}/v2/register-phone-call",
            headers={"Authorization": f"Bearer {settings.retell_api_key}"},
            json=payload,
            timeout=6,
        )
        resp.raise_for_status()
        return resp.json()["call_id"]
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise RetellError(str(exc)) from exc


def sip_uri(call_id: str) -> str:
    return f"sip:{call_id}@sip.retellai.com"


def verify_signature(raw_body: bytes, header: str | None, api_key: str) -> bool:
    """x-retell-signature is 'v=<ts_ms>,d=<hex hmac-sha256(body + ts)>' keyed
    with the Retell API key."""
    if not header or not api_key:
        return False
    m = _SIG_RE.match(header)
    if not m:
        return False
    ts, digest = m.group(1), m.group(2)
    if abs(int(time.time() * 1000) - int(ts)) > _MAX_SKEW_MS:
        return False
    expected = hmac.new(api_key.encode(), raw_body + ts.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, digest)


def format_transcript(call: dict) -> str:
    """Prefer transcript_object (has roles) for a readable 'Agent:/Caller:' layout."""
    turns = call.get("transcript_object") or []
    if turns:
        lines = []
        for t in turns:
            who = "Assistant" if t.get("role") == "agent" else "Caller"
            lines.append(f"{who}: {t.get('content', '').strip()}")
        return "\n".join(lines)
    return call.get("transcript") or ""
