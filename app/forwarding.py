"""Carrier call-forwarding codes shown on the setup page.

The owner sets this up ONCE: "forward calls I don't answer / when I'm busy
/ when I'm unreachable" to their Call Keeper number. Their phone still rings
first; only missed calls reach the agent. The ON/OFF switch in the app then
decides what happens to those missed calls (AI agent vs voicemail), so they
never need to dial codes again.

GSM codes (**004*) work on every UK mobile network and on AT&T / T-Mobile in
the US. Verizon uses its own *71 code.
"""

from dataclasses import dataclass
from urllib.parse import quote


@dataclass(frozen=True)
class Carrier:
    key: str
    label: str
    on_template: str  # {number} is substituted
    off_code: str
    note: str = ""


_GSM = dict(on_template="**004*{number}#", off_code="##004#")

CARRIERS = {
    "GB": [
        Carrier("ee", "EE", **_GSM),
        Carrier("o2", "O2", **_GSM),
        Carrier("vodafone", "Vodafone", **_GSM),
        Carrier("three", "Three", **_GSM),
        Carrier("giffgaff", "giffgaff / Tesco / Sky / other", **_GSM,
                note="Most UK networks use these codes. If it doesn't work, your network's help pages will list "
                     "'conditional call divert' settings."),
    ],
    "US": [
        Carrier("att", "AT&T", **_GSM),
        Carrier("tmobile", "T-Mobile / Mint / Metro", **_GSM),
        Carrier("verizon", "Verizon", on_template="*71{number}", off_code="*73",
                note="Verizon forwards calls you don't answer or are busy for."),
        Carrier("other", "Other / landline / VoIP", **_GSM,
                note="Landlines and VoIP providers (RingCentral, Google Voice, etc.) set forwarding in their app or "
                     "website: look for 'forward when busy / no answer' and enter your Call Keeper number."),
    ],
}


def _dial_number(number: str, carrier_key: str) -> str:
    # Verizon's *71 wants the 10-digit national number.
    if carrier_key == "verizon" and number.startswith("+1"):
        return number[2:]
    return number


def codes_for(country: str, number: str) -> list[dict]:
    out = []
    for c in CARRIERS.get(country, CARRIERS["US"]):
        on = c.on_template.format(number=_dial_number(number, c.key))
        out.append({
            "key": c.key,
            "label": c.label,
            "on_code": on,
            "off_code": c.off_code,
            # '#' and '*' must be percent-encoded inside tel: links or the
            # dialer truncates at the '#'.
            "on_href": "tel:" + quote(on, safe="+"),
            "off_href": "tel:" + quote(c.off_code, safe="+"),
            "note": c.note,
        })
    return out
