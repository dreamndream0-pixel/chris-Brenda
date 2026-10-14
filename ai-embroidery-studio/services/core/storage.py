"""Private object storage. Local filesystem for development; same key layout as Supabase Storage.

Keys: embroidery/private/{userId}/{projectId}/{revision|uploads}/{file}
Files are never served directly - only through short-lived signed URLs (signing.py).
"""
from __future__ import annotations

import hashlib
import os
import re
from functools import lru_cache
from pathlib import Path

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


@lru_cache
def get_storage() -> LocalStorage:
    return LocalStorage(get_settings().data_dir / "storage")
