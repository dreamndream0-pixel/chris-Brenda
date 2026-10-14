"""Environment-driven settings shared by the API and the worker."""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    database_url: str
    redis_url: str
    queue_mode: str            # "rq" (Redis worker) or "inline" (tests / single process)
    auth_mode: str             # "dev" (X-Dev-User header) or "supabase" (JWT)
    supabase_jwt_secret: str
    supabase_jwks_url: str
    signing_secret: str
    public_api_url: str
    cors_origins: list[str] = field(default_factory=list)
    storage_backend: str = "local"   # "local" (filesystem) or "supabase" (Supabase Storage)
    supabase_url: str = ""
    supabase_service_key: str = ""
    storage_bucket: str = "embroidery"
    max_upload_bytes: int = 8 * 1024 * 1024
    max_active_jobs_per_user: int = 3
    signed_url_ttl_s: int = 300


@lru_cache
def get_settings() -> Settings:
    data_dir = Path(_env("EMB_DATA_DIR", "data")).resolve()
    auth_mode = _env("EMB_AUTH_MODE", "dev")
    signing_secret = _env("EMB_SIGNING_SECRET")
    if not signing_secret:
        if auth_mode != "dev":
            raise RuntimeError("EMB_SIGNING_SECRET is required outside dev mode")
        signing_secret = secrets.token_hex(32)
    if auth_mode == "supabase" and not (_env("SUPABASE_JWT_SECRET") or _env("SUPABASE_JWKS_URL")):
        raise RuntimeError("supabase auth needs SUPABASE_JWT_SECRET or SUPABASE_JWKS_URL")
    if auth_mode not in ("dev", "supabase"):
        raise RuntimeError(f"unknown EMB_AUTH_MODE {auth_mode!r}")
    storage_backend = _env("EMB_STORAGE", "local")
    if storage_backend not in ("local", "supabase"):
        raise RuntimeError(f"unknown EMB_STORAGE {storage_backend!r}")
    if storage_backend == "supabase" and not (_env("SUPABASE_URL") and _env("SUPABASE_SERVICE_ROLE_KEY")):
        raise RuntimeError("EMB_STORAGE=supabase needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY")
    return Settings(
        data_dir=data_dir,
        database_url=_env("EMB_DATABASE_URL", f"sqlite:///{data_dir / 'emb.db'}"),
        redis_url=_env("EMB_REDIS_URL", "redis://localhost:6379/0"),
        queue_mode=_env("EMB_QUEUE_MODE", "rq"),
        auth_mode=auth_mode,
        supabase_jwt_secret=_env("SUPABASE_JWT_SECRET"),
        supabase_jwks_url=_env("SUPABASE_JWKS_URL"),
        signing_secret=signing_secret,
        public_api_url=_env("EMB_PUBLIC_API_URL", "http://localhost:8000").rstrip("/"),
        cors_origins=[o for o in _env("EMB_CORS_ORIGINS", "http://localhost:3000").split(",") if o],
        storage_backend=storage_backend,
        supabase_url=_env("SUPABASE_URL").rstrip("/"),
        supabase_service_key=_env("SUPABASE_SERVICE_ROLE_KEY"),
        storage_bucket=_env("EMB_STORAGE_BUCKET", "embroidery"),
    )
