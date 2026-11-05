"""Phone number normalising/formatting without a heavy dependency."""

import re


def normalize(number: str, country: str = "US") -> str:
    """Best-effort E.164. Accepts '07700 900123', '+44 7700 900123',
    '(555) 123-4567', '5551234567', '+15551234567'."""
    raw = (number or "").strip()
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return ""
    if raw.startswith("+"):
        return "+" + digits
    if raw.startswith("00"):
        return "+" + digits[2:]
    if country == "GB":
        if digits.startswith("44"):
            return "+" + digits
        if digits.startswith("0"):
            return "+44" + digits[1:]
        return "+44" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    if len(digits) == 10:
        return "+1" + digits
    return "+" + digits


def pretty(number: str) -> str:
    """Human formatting for display; falls back to the input."""
    n = number or ""
    if n.startswith("+1") and len(n) == 12:
        return f"({n[2:5]}) {n[5:8]}-{n[8:]}"
    if n.startswith("+44") and len(n) == 13:
        national = "0" + n[3:]
        return f"{national[:5]} {national[5:]}"
    return n
