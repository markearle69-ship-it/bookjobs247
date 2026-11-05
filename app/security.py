"""Passwords, login sessions and password-reset tokens."""

import hashlib
import hmac
import os

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .config import settings

SESSION_COOKIE = "bj_session"
SESSION_MAX_AGE = 90 * 24 * 3600  # owners stay logged in on their phone
ADMIN_COOKIE = "bj_admin"
ADMIN_MAX_AGE = 7 * 24 * 3600
RESET_MAX_AGE = 3600

_N, _R, _P, _DKLEN = 2**14, 8, 1, 32


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split("$", 1)
        salt, expected = bytes.fromhex(salt_hex), bytes.fromhex(digest_hex)
    except (ValueError, AttributeError):
        return False
    actual = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN)
    return hmac.compare_digest(actual, expected)


def _serializer(salt: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key, salt=salt)


def make_session(account_id: int) -> str:
    return _serializer("session").dumps({"a": account_id})


def read_session(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(_serializer("session").loads(value, max_age=SESSION_MAX_AGE)["a"])
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
        return None


def make_admin_session() -> str:
    return _serializer("admin").dumps({"ok": True})


def read_admin_session(value: str | None) -> bool:
    if not value or not settings.admin_password:
        return False
    try:
        _serializer("admin").loads(value, max_age=ADMIN_MAX_AGE)
        return True
    except (BadSignature, SignatureExpired):
        return False


def make_reset_token(account_id: int, password_hash: str) -> str:
    # Includes a fingerprint of the current password hash, so the link stops
    # working as soon as it has been used to set a new password.
    return _serializer("reset").dumps({"a": account_id, "h": password_hash[-12:]})


def read_reset_token(token: str) -> tuple[int, str] | None:
    try:
        data = _serializer("reset").loads(token, max_age=RESET_MAX_AGE)
        return int(data["a"]), str(data["h"])
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
        return None
