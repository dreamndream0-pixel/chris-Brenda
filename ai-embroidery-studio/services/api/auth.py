"""Request authentication.

dev:      `X-Dev-User: <name>` header (local development only).
supabase: `Authorization: Bearer <Supabase access token>`, verified with the
          project's JWT secret (HS256) or its JWKS endpoint (asymmetric keys).
"""
from __future__ import annotations

import re
import uuid
from functools import lru_cache

import jwt
from fastapi import Header, HTTPException

from services.core.settings import get_settings

_DEV_NAME = re.compile(r"^[A-Za-z0-9_.@-]{1,64}$")
_DEV_NS = uuid.UUID("6f1c6c2e-8f2a-4c43-9d55-2b7b0c7e5a10")


@lru_cache
def _jwks_client(url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(url, cache_keys=True)


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
