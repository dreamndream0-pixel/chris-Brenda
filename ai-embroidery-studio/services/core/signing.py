"""HMAC-signed, short-lived tokens for upload and download URLs."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from .settings import get_settings


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign(purpose: str, subject: str, ttl_s: int, extra: dict | None = None) -> tuple[str, int]:
    exp = int(time.time()) + ttl_s
    body = _b64(json.dumps({"p": purpose, "s": subject, "e": exp, **(extra or {})}, separators=(",", ":")).encode())
    mac = hmac.new(get_settings().signing_secret.encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(mac)}", exp


def verify(token: str, purpose: str) -> dict | None:
    try:
        body, mac = token.split(".", 1)
        expected = hmac.new(get_settings().signing_secret.encode(), body.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _unb64(mac)):
            return None
        claims = json.loads(_unb64(body))
    except (ValueError, json.JSONDecodeError):
        return None
    if claims.get("p") != purpose or claims.get("e", 0) < time.time():
        return None
    return claims
