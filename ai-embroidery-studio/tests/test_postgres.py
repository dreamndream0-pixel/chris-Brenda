"""API flow against real Postgres with the Supabase migration (set EMB_TEST_PG_URL to run)."""
import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, make_url, text

from test_api import make_client  # noqa: F401 - shared fixture

PG_URL = os.environ.get("EMB_TEST_PG_URL")
pytestmark = pytest.mark.skipif(not PG_URL, reason="EMB_TEST_PG_URL not set")
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def pg_client(make_client):
    admin = create_engine(PG_URL, isolation_level="AUTOCOMMIT")
    db_name = f"emb_test_{uuid.uuid4().hex[:8]}"
    with admin.connect() as conn:
        conn.execute(text(f"create database {db_name}"))
    url = make_url(PG_URL).set(database=db_name)
    eng = create_engine(url)
    with eng.begin() as conn:
        conn.exec_driver_sql((Path(__file__).with_name("supabase_stub.sql")).read_text())
        conn.exec_driver_sql((ROOT / "infra/supabase/migrations/0001_embroidery.sql").read_text())
        conn.exec_driver_sql("grant select on all tables in schema public to authenticated")
        from services.api.auth import _DEV_NS
        for name in ("alice", "bob"):
            conn.execute(text("insert into auth.users (id) values (:id)"), {"id": str(uuid.uuid5(_DEV_NS, name))})
    yield make_client(EMB_DATABASE_URL=url.render_as_string(hide_password=False)), eng
    eng.dispose()
    with admin.connect() as conn:
        conn.execute(text(f"drop database {db_name} with (force)"))
    admin.dispose()


def test_flow_on_postgres_with_rls(pg_client):
    from test_api import ALICE, BOB, SIMPLE_SVG, upload
    client, eng = pg_client
    pid, job = upload(client, ALICE, SIMPLE_SVG)
    assert job["status"] == "ready", job
    assert client.post(f"/api/v1/projects/{pid}/compile", json={"revision": 1}, headers=ALICE).json()["status"] == "ready"
    assert client.post(f"/api/v1/projects/{pid}/exports", json={"revision": 1}, headers=ALICE).json()["status"] == "ready"
    assert client.get(f"/api/v1/projects/{pid}", headers=BOB).status_code == 404
    stale = client.patch(f"/api/v1/projects/{pid}/design", json={"baseRevision": 0}, headers=ALICE)
    assert stale.status_code == 409

    # RLS: a signed-in user reading through Supabase only sees their own rows.
    from services.api.auth import _DEV_NS
    alice, bob = (str(uuid.uuid5(_DEV_NS, n)) for n in ("alice", "bob"))
    with eng.begin() as conn:
        conn.exec_driver_sql("set local role authenticated")
        conn.execute(text("select set_config('request.jwt.claim.sub', :s, true)"), {"s": alice})
        assert conn.execute(text("select count(*) from emb_projects")).scalar_one() == 1
        assert conn.execute(text("select count(*) from emb_revisions")).scalar_one() == 1
        assert conn.execute(text("select count(*) from emb_artifacts")).scalar_one() >= 5
    with eng.begin() as conn:
        conn.exec_driver_sql("set local role authenticated")
        conn.execute(text("select set_config('request.jwt.claim.sub', :s, true)"), {"s": bob})
        assert conn.execute(text("select count(*) from emb_projects")).scalar_one() == 0
        assert conn.execute(text("select count(*) from emb_artifacts")).scalar_one() == 0
        with pytest.raises(Exception):
            conn.execute(text("insert into emb_projects (user_id, name, fabric_preset) values (:u, 'x', 'canvas')"), {"u": bob})
