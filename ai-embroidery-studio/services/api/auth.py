"""Request authentication.

dev:      `X-Dev-User: <name>` header (local development only).
supabase: `Authorization: Bearer <Supabase access token>`, verified with the
          project's JWT secret (HS256) or its JWKS endpoint (asymmetric keys).
"""
from __future__ import annotations

import hashlib
import re
import threading
import time
import uuid
from functools import lru_cache

import httpx

import jwt
from fastapi import Header, HTTPException

from services.core.settings import get_settings

_DEV_NAME = re.compile(r"^[A-Za-z0-9_.@-]{1,64}$")
_DEV_NS = uuid.UUID("6f1c6c2e-8f2a-4c43-9d55-2b7b0c7e5a10")


@lru_cache
def _jwks_client(url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(url, cache_keys=True)


_USER_CACHE: dict[str, tuple[float, str]] = {}
_USER_CACHE_LOCK = threading.Lock()
USER_CACHE_TTL_S = 60


def _verify_with_supabase(token: str) -> str:
    """Ask Supabase Auth who the token belongs to. Works whatever the project's signing method
    (used for HS256 tokens when no shared secret is configured). Results are cached briefly."""
    settings = get_settings()
    digest = hashlib.sha256(token.encode()).hexdigest()
    now = time.time()
    with _USER_CACHE_LOCK:
        hit = _USER_CACHE.get(digest)
        if hit and hit[0] > now:
            return hit[1]
    try:
        res = httpx.get(f"{settings.supabase_url}/auth/v1/user", timeout=10.0,
                        headers={"apikey": settings.supabase_service_key, "Authorization": f"Bearer {token}"})
    except httpx.HTTPError as exc:
        raise HTTPException(503, "auth_unavailable") from exc
    if res.status_code != 200:
        raise _unauthorized("invalid_token")
    sub = res.json().get("id")
    if not sub:
        raise _unauthorized("invalid_token")
    with _USER_CACHE_LOCK:
        if len(_USER_CACHE) > 5000:
            _USER_CACHE.clear()
        _USER_CACHE[digest] = (now + USER_CACHE_TTL_S, str(sub))
    return str(sub)


def _unauthorized(detail: str = "not_authenticated") -> HTTPException:
    return HTTPException(status_code=401, detail=detail)


def current_user(authorization: str | None = Header(default=None),
                 x_dev_user: str | None = Header(default=None)) -> str:
    settings = get_settings()
    if settings.auth_mode == "dev":
        if not x_dev_user or not _DEV_NAME.match(x_dev_user):
            raise _unauthorized()
        return str(uuid.uuid5(_DEV_NS, x_dev_user.lower()))

    if not authorization or not authorization.lower().startswith("bearer "):
        raise _unauthorized()
    token = authorization[7:].strip()
    try:
        # Supabase projects sign with either asymmetric keys (published at the JWKS URL) or the
        # legacy shared HS256 secret; pick by the token's own header, never accept "none".
        alg = jwt.get_unverified_header(token).get("alg")
        if alg == "HS256" and not settings.supabase_jwt_secret and settings.supabase_url and settings.supabase_service_key:
            return _verify_with_supabase(token)
        if alg == "HS256" and settings.supabase_jwt_secret:
            claims = jwt.decode(token, settings.supabase_jwt_secret, algorithms=["HS256"], audience="authenticated")
        elif alg in ("ES256", "RS256") and settings.supabase_jwks_url:
            key = _jwks_client(settings.supabase_jwks_url).get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=[alg], audience="authenticated")
        else:
            raise jwt.InvalidAlgorithmError(f"unsupported token algorithm {alg!r}")
    except jwt.PyJWTError as exc:
        raise _unauthorized("invalid_token") from exc
    sub = claims.get("sub")
    if not sub or claims.get("role") not in (None, "authenticated"):
        raise _unauthorized("invalid_token")
    return str(sub)
