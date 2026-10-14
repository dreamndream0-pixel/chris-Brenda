"""Private object storage: local filesystem (development) or a private Supabase Storage bucket.

Keys: embroidery/private/{userId}/{projectId}/{revision|uploads}/{file}. In Supabase the first
segment is the bucket. Files are only ever handed out through short-lived signed URLs -
Supabase's own, or the API's HMAC tokens (signing.py) for local storage.
"""
from __future__ import annotations

import hashlib
import os
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

import httpx

from .settings import get_settings

_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def object_key(user_id: str, project_id: str, part: str | int, filename: str) -> str:
    key = f"embroidery/private/{user_id}/{project_id}/{part}/{filename}"
    validate_key(key)
    return key


def validate_key(key: str) -> None:
    parts = key.split("/")
    if len(parts) < 3 or any(not _SEGMENT.match(p) or p in (".", "..") for p in parts):
        raise ValueError(f"invalid storage key: {key!r}")


class LocalStorage:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def _path(self, key: str) -> Path:
        validate_key(key)
        path = (self.root / key).resolve()
        if self.root not in path.parents:
            raise ValueError("key escapes storage root")
        return path

    def put(self, key: str, data: bytes) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
        return hashlib.sha256(data).hexdigest()

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    # Local storage has no signed URLs of its own; the API serves files with HMAC tokens.
    def signed_download_url(self, key: str, filename: str | None, ttl_s: int) -> str | None:
        return None

    def signed_upload(self, key: str, content_type: str) -> dict | None:
        return None


class StorageError(Exception):
    pass


class SupabaseStorage:
    """Supabase Storage REST API with the service-role key (server side only)."""

    def __init__(self, url: str, service_key: str, bucket: str, client: httpx.Client | None = None):
        self.base = f"{url.rstrip('/')}/storage/v1"
        self.bucket = bucket
        self.http = client or httpx.Client(timeout=60.0)
        self.headers = {"Authorization": f"Bearer {service_key}", "apikey": service_key}

    def _object(self, key: str) -> str:
        validate_key(key)
        _, _, rest = key.partition("/")  # first segment ("embroidery") maps to the configured bucket
        if not rest:
            raise ValueError(f"invalid storage key {key!r}")
        return f"{self.bucket}/{quote(rest)}"

    def _check(self, res: httpx.Response, what: str) -> httpx.Response:
        if res.status_code >= 400:
            raise StorageError(f"storage {what} failed ({res.status_code})")
        return res

    def put(self, key: str, data: bytes) -> str:
        res = self.http.post(f"{self.base}/object/{self._object(key)}", content=data,
                             headers={**self.headers, "x-upsert": "true", "content-type": _content_type(key),
                                      "cache-control": "max-age=0"})
        self._check(res, "upload")
        return hashlib.sha256(data).hexdigest()

    def get(self, key: str) -> bytes:
        res = self.http.get(f"{self.base}/object/{self._object(key)}", headers=self.headers)
        if res.status_code in (400, 404):
            raise FileNotFoundError(key)
        return self._check(res, "download").content

    def exists(self, key: str) -> bool:
        try:
            self.get(key)
            return True
        except FileNotFoundError:
            return False

    def signed_download_url(self, key: str, filename: str | None, ttl_s: int) -> str | None:
        res = self._check(self.http.post(f"{self.base}/object/sign/{self._object(key)}",
                                         json={"expiresIn": ttl_s}, headers=self.headers), "sign")
        url = f"{self.base}{res.json()['signedURL']}"
        return f"{url}&download={quote(filename)}" if filename else url

    def signed_upload(self, key: str, content_type: str) -> dict | None:
        res = self._check(self.http.post(f"{self.base}/object/upload/sign/{self._object(key)}",
                                         json={}, headers=self.headers), "upload sign")
        return {"url": f"{self.base}{res.json()['url']}",
                "headers": {"content-type": content_type, "x-upsert": "false"}}


_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".svg": "image/svg+xml", ".zip": "application/zip",
          ".json": "application/json", ".txt": "text/plain; charset=utf-8"}


def _content_type(key: str) -> str:
    return _TYPES.get(os.path.splitext(key)[1].lower(), "application/octet-stream")


@lru_cache
def get_storage() -> LocalStorage | SupabaseStorage:
    settings = get_settings()
    if settings.storage_backend == "supabase":
        return SupabaseStorage(settings.supabase_url, settings.supabase_service_key, settings.storage_bucket)
    return LocalStorage(settings.data_dir / "storage")
