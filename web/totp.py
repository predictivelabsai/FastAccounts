"""RFC 6238 TOTP with six digits, SHA-1 and a 30-second time step."""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import re
import secrets
import time
from urllib.parse import quote, urlencode


def secret_new() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii")


def code(secret: str, step: int | None = None) -> str:
    key = base64.b32decode(secret, casefold=True)
    if not key:
        raise ValueError("Empty TOTP secret")
    counter = int(time.time()) // 30 if step is None else step
    digest = hmac.new(key, counter.to_bytes(8, "big"), hashlib.sha1).digest()
    offset = digest[-1] & 15
    number = int.from_bytes(digest[offset:offset + 4], "big") & 0x7fffffff
    return f"{number % 1000000:06d}"


def verify(secret: str, submitted: str, last_step: int | None = None,
           now: int | float | None = None) -> int | None:
    if not isinstance(submitted, str) or not re.fullmatch(r"[0-9]{6}", submitted):
        return None
    current = int(time.time() if now is None else now) // 30
    try:
        for step in (current, current - 1, current + 1):
            if step >= 0 and (last_step is None or step > last_step):
                if hmac.compare_digest(code(secret, step), submitted):
                    return step
    except (ValueError, TypeError, binascii.Error, OverflowError):
        return None
    return None


def uri(secret: str, email: str) -> str:
    return "otpauth://totp/" + quote(f"FastAccounts:{email}", safe=":") + "?" + urlencode(
        {"secret": secret, "issuer": "FastAccounts"})
