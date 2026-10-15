"""Database tables (SQLAlchemy Core) - SQLite locally, Postgres/Supabase in production.

Mirrors infra/supabase/migrations. The backend connects with a service role,
so every query here is scoped by user_id explicitly; RLS is defence in depth.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from functools import lru_cache

from sqlalchemy import (JSON, Column, DateTime, Float, ForeignKey, Integer, MetaData, String, Table, Text,
                        UniqueConstraint, Uuid, create_engine, event)
from sqlalchemy.engine import Engine

from .settings import get_settings

metadata = MetaData()
# Native uuid on Postgres (matches the Supabase migration); CHAR(32) on SQLite. Values stay strings.
UUID = Uuid(as_uuid=False)


def new_id() -> str:
    return str(uuid.uuid4())


def now() -> datetime:
    return datetime.now(timezone.utc)


projects = Table(
    "emb_projects", metadata,
    Column("id", UUID, primary_key=True),
    Column("user_id", UUID, nullable=False, index=True),
    Column("name", String(120), nullable=False),
    Column("fabric_preset", String(32), nullable=False),
    Column("status", String(32), nullable=False, default="draft"),  # draft / awaiting_test_sew / accepted
    Column("current_revision", Integer, nullable=False, default=0),
    Column("compiled_revision", Integer, nullable=True),
    Column("width_mm", Float, nullable=True),
    Column("height_mm", Float, nullable=True),
    Column("color_count", Integer, nullable=True),
    Column("stitch_count", Integer, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, default=now),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=now),
)

revisions = Table(
    "emb_revisions", metadata,
    Column("id", UUID, primary_key=True),
    Column("project_id", UUID, ForeignKey("emb_projects.id", ondelete="CASCADE"), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("design_json", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, default=now),
    UniqueConstraint("project_id", "revision", name="uq_revision"),
)

uploads = Table(
    "emb_uploads", metadata,
    Column("id", UUID, primary_key=True),
    Column("project_id", UUID, ForeignKey("emb_projects.id", ondelete="CASCADE"), nullable=False),
    Column("user_id", UUID, nullable=False),
    Column("filename", String(200), nullable=False),
    Column("content_type", String(64), nullable=False),
    Column("declared_size", Integer, nullable=False),
    Column("storage_key", Text, nullable=False),
    Column("status", String(16), nullable=False, default="pending"),  # pending / uploaded / used
    Column("created_at", DateTime(timezone=True), nullable=False, default=now),
)

jobs = Table(
    "emb_jobs", metadata,
    Column("id", UUID, primary_key=True),
    Column("project_id", UUID, ForeignKey("emb_projects.id", ondelete="CASCADE"), nullable=False),
    Column("user_id", UUID, nullable=False, index=True),
    Column("revision", Integer, nullable=True),
    Column("kind", String(16), nullable=False),  # analyze / compile / export / ai_plan
    Column("status", String(16), nullable=False, default="queued"),
    Column("progress", Integer, nullable=False, default=0),
    Column("params", JSON, nullable=True),
    Column("error_code", String(64), nullable=True),
    Column("error_message", Text, nullable=True),
    Column("result", JSON, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, default=now),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=now),
)

artifacts = Table(
    "emb_artifacts", metadata,
    Column("id", UUID, primary_key=True),
    Column("project_id", UUID, ForeignKey("emb_projects.id", ondelete="CASCADE"), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("job_id", UUID, nullable=True),
    Column("kind", String(32), nullable=False),  # design_svg / dst / pes / threadlist / stitches / export_zip ...
    Column("storage_key", Text, nullable=False),
    Column("checksum", String(64), nullable=False),
    Column("size_bytes", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, default=now),
    UniqueConstraint("project_id", "revision", "kind", name="uq_artifact"),
)

test_sews = Table(
    "emb_test_sews", metadata,
    Column("id", UUID, primary_key=True),
    Column("project_id", UUID, ForeignKey("emb_projects.id", ondelete="CASCADE"), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("photo_storage_key", Text, nullable=True),
    Column("issue_tags", JSON, nullable=True),
    Column("notes", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, default=now),
)

ACTIVE_JOB_STATUSES = ("queued", "preprocessing", "planning", "compiling", "validating", "exporting")


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    url = settings.database_url
    kwargs = {}
    if url.startswith("sqlite"):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    if not url.startswith("sqlite"):
        kwargs["pool_pre_ping"] = True
        if "+psycopg" in url:
            # Supabase's pooler (transaction mode) cannot keep prepared statements between queries.
            kwargs["connect_args"] = {"prepare_threshold": None}
    engine = create_engine(url, future=True, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _pragmas(conn, _):
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA journal_mode=WAL")
    return engine


def init_db() -> None:
    """SQLite (development) is created on start-up; Postgres/Supabase is created by
    infra/supabase/migrations so RLS and auth foreign keys exist (EMB_DB_CREATE=1 overrides)."""
    import os
    engine = get_engine()
    if engine.dialect.name == "sqlite" or os.environ.get("EMB_DB_CREATE") == "1":
        metadata.create_all(engine)
