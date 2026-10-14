"""API flow tests: inline queue + fake Ink/Stitch (mode=auto), isolated data dir per test."""
import io
import sys
import time
import zipfile
from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, select

FAKE = Path(__file__).with_name("fake_inkstitch.py")
UPLOADS = Path(__file__).resolve().parents[1] / "fixtures" / "uploads"
ALICE = {"X-Dev-User": "alice"}
BOB = {"X-Dev-User": "bob"}

SIMPLE_SVG = (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50">'
              b'<rect x="0" y="0" width="60" height="50" fill="#c0392b"/>'
              b'<rect x="60" y="0" width="40" height="50" fill="#2471a3"/></svg>')


def _reset_caches():
    from services.api import auth
    from services.core import db, settings, storage
    settings.get_settings.cache_clear()
    db.get_engine.cache_clear()
    storage.get_storage.cache_clear()
    auth._jwks_client.cache_clear()


@pytest.fixture
def make_client(tmp_path, monkeypatch):
    def factory(**env):
        base = {"EMB_DATA_DIR": str(tmp_path / "data"), "EMB_QUEUE_MODE": "inline", "EMB_AUTH_MODE": "dev",
                "EMB_PUBLIC_API_URL": "http://testserver",
                "INKSTITCH_CMD": f"{sys.executable} {FAKE} auto -"}
        for k, v in {**base, **env}.items():
            monkeypatch.setenv(k, v)
        _reset_caches()
        from services.api.main import create_app
        return TestClient(create_app()).__enter__()
    yield factory
    _reset_caches()


@pytest.fixture
def client(make_client):
    return make_client()


def _path(url: str) -> str:
    return url.replace("http://testserver", "")


def upload(client, headers, svg: bytes, width=50.0, name="logo"):
    p = client.post("/api/v1/projects", json={"name": name, "widthMm": width, "fabricPreset": "woven_cotton"},
                    headers=headers)
    assert p.status_code == 201, p.text
    pid = p.json()["id"]
    u = client.post(f"/api/v1/projects/{pid}/upload-url",
                    json={"filename": "logo.svg", "contentType": "image/svg+xml", "sizeBytes": len(svg)},
                    headers=headers)
    assert u.status_code == 200, u.text
    put = client.put(_path(u.json()["uploadUrl"]), content=svg)
    assert put.status_code == 204, put.text
    job = client.post(f"/api/v1/projects/{pid}/analyze", json={"uploadId": u.json()["uploadId"]}, headers=headers)
    assert job.status_code == 202, job.text
    return pid, job.json()


def test_full_flow_upload_compile_export_download(client):
    pid, job = upload(client, ALICE, SIMPLE_SVG, width=50)
    assert job["status"] == "ready", job
    proj = client.get(f"/api/v1/projects/{pid}", headers=ALICE).json()
    design = proj["design"]
    assert design["revision"] == 1 and design["sizeMm"] == {"width": 50.0, "height": 25.0}
    assert [r["stitchType"] for r in design["regions"]] == ["fill", "fill"]
    assert len(design["palette"]) == 2

    patched = client.patch(f"/api/v1/projects/{pid}/design",
                           json={"baseRevision": 1, "sizeMm": {"width": 80}, "fabricPreset": "knit_cotton"},
                           headers=ALICE)
    assert patched.status_code == 200, patched.text
    d2 = patched.json()["design"]
    assert d2["revision"] == 2 and d2["sizeMm"] == {"width": 80.0, "height": 40.0}  # aspect locked
    assert d2["regions"][0]["params"]["pullCompensationMm"] == 0.25  # knit preset applied

    comp = client.post(f"/api/v1/projects/{pid}/compile", json={"revision": 2}, headers=ALICE).json()
    assert comp["status"] == "ready", comp
    assert abs(comp["result"]["widthMm"] - 80) < 1.5 and comp["result"]["colorBlocks"] == 2

    st = client.get(f"/api/v1/projects/{pid}/stitches", headers=ALICE).json()
    assert st["revision"] == 2 and st["colors"] == ["#c0392b", "#2471a3"]  # design palette, not PES snap

    exp = client.post(f"/api/v1/projects/{pid}/exports", json={"revision": 2}, headers=ALICE).json()
    assert exp["status"] == "ready", exp
    proj = client.get(f"/api/v1/projects/{pid}", headers=ALICE).json()
    assert proj["project"]["status"] == "awaiting_test_sew"
    zip_art = next(a for a in proj["artifacts"] if a["kind"] == "export_zip")
    link = client.get(f"/api/v1/projects/{pid}/exports/{zip_art['id']}", headers=ALICE).json()
    dl = client.get(_path(link["url"]))
    assert dl.status_code == 200 and dl.headers["content-type"] == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(dl.content)).namelist()
    assert {"embroidery_r2.dst", "embroidery_r2.pes", "embroidery_r2_spec.txt", "embroidery_r2_inkstitch.svg"} <= set(names)
    spec = zipfile.ZipFile(io.BytesIO(dl.content)).read("embroidery_r2_spec.txt").decode()
    assert "#c0392b" in spec and "試繡" in spec


def test_other_user_cannot_access(client):
    pid, job = upload(client, ALICE, SIMPLE_SVG)
    assert client.get(f"/api/v1/projects/{pid}", headers=BOB).status_code == 404
    assert client.get(f"/api/v1/jobs/{job['jobId']}", headers=BOB).status_code == 404
    assert client.post(f"/api/v1/projects/{pid}/compile", json={"revision": 1}, headers=BOB).status_code == 404
    assert client.patch(f"/api/v1/projects/{pid}/design", json={"baseRevision": 1}, headers=BOB).status_code == 404
    assert client.get("/api/v1/projects", headers=BOB).json() == []
    client.post(f"/api/v1/projects/{pid}/compile", json={"revision": 1}, headers=ALICE)
    art = next(a for a in client.get(f"/api/v1/projects/{pid}", headers=ALICE).json()["artifacts"] if a["kind"] == "dst")
    assert client.get(f"/api/v1/projects/{pid}/exports/{art['id']}", headers=BOB).status_code == 404


def test_requires_auth(client):
    assert client.get("/api/v1/projects").status_code == 401
    assert client.get("/api/v1/projects", headers={"X-Dev-User": "bad name!"}).status_code == 401


def test_signed_links_are_checked(client):
    pid, _ = upload(client, ALICE, SIMPLE_SVG)
    client.post(f"/api/v1/projects/{pid}/compile", json={"revision": 1}, headers=ALICE)
    art = next(a for a in client.get(f"/api/v1/projects/{pid}", headers=ALICE).json()["artifacts"] if a["kind"] == "dst")
    url = _path(client.get(f"/api/v1/projects/{pid}/exports/{art['id']}", headers=ALICE).json()["url"])
    assert client.get(url).status_code == 200
    assert client.get(url[:-3] + "AAA").status_code == 403
    from services.core.signing import sign
    upload_token, _ = sign("upload", art["id"], 60)  # right id, wrong purpose
    assert client.get(f"/api/v1/files/{upload_token}").status_code == 403
    expired, _ = sign("download", art["id"], -1)
    assert client.get(f"/api/v1/files/{expired}").status_code == 403


def test_upload_limits(client):
    pid = client.post("/api/v1/projects", json={"name": "x", "widthMm": 50}, headers=ALICE).json()["id"]
    req = lambda **kw: client.post(f"/api/v1/projects/{pid}/upload-url", headers=ALICE, json={
        "filename": "a.svg", "contentType": "image/svg+xml", "sizeBytes": 100, **kw})
    assert req(contentType="image/png", filename="a.png").status_code == 415
    assert req(sizeBytes=9 * 1024 * 1024).status_code == 413
    u = req(sizeBytes=10).json()
    assert client.put(_path(u["uploadUrl"]), content=b"x" * 11).status_code == 413
    assert client.put(f"/api/v1/uploads/{u['uploadId']}?token=forged", content=b"x").status_code == 403
    assert client.post("/api/v1/projects", json={"name": "x", "widthMm": 500}, headers=ALICE).status_code == 422


def test_hazardous_svg_is_sanitised(client):
    pid, job = upload(client, ALICE, (UPLOADS / "logo_with_hazards.svg").read_bytes(), width=60)
    assert job["status"] == "ready", job
    assert "unsafe_content_removed" in job["result"]["warnings"]
    assert "text_not_supported_convert_to_outlines" in job["result"]["warnings"]


@pytest.mark.parametrize("svg,code", [
    (b'<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
     b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><text>&x;</text></svg>', "doctype_not_allowed"),
    (b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="5" height="5"/></svg>',
     "missing_viewbox"),
    (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><script>x</script></svg>',
     "no_embroiderable_shapes"),
    (b'not xml at all', "invalid_svg"),
])
def test_rejected_svgs(client, svg, code):
    _, job = upload(client, ALICE, svg)
    assert job["status"] == "failed" and job["errorCode"] == code, job


def test_revision_conflict(client):
    pid, _ = upload(client, ALICE, SIMPLE_SVG)
    ok = client.patch(f"/api/v1/projects/{pid}/design", json={"baseRevision": 1, "lockAspect": False}, headers=ALICE)
    assert ok.status_code == 200
    stale = client.patch(f"/api/v1/projects/{pid}/design", json={"baseRevision": 1, "lockAspect": True}, headers=ALICE)
    assert stale.status_code == 409


def test_old_compile_does_not_override_newer(client):
    pid, _ = upload(client, ALICE, SIMPLE_SVG, width=50)
    client.patch(f"/api/v1/projects/{pid}/design", json={"baseRevision": 1, "sizeMm": {"width": 90, "height": 45}},
                 headers=ALICE)
    assert client.post(f"/api/v1/projects/{pid}/compile", json={"revision": 2}, headers=ALICE).json()["status"] == "ready"
    assert client.post(f"/api/v1/projects/{pid}/compile", json={"revision": 1}, headers=ALICE).json()["status"] == "ready"
    proj = client.get(f"/api/v1/projects/{pid}", headers=ALICE).json()["project"]
    assert proj["compiledRevision"] == 2
    latest = client.get(f"/api/v1/projects/{pid}/stitches", headers=ALICE).json()
    assert latest["revision"] == 2 and abs(latest["widthMm"] - 90) < 2
    old = client.get(f"/api/v1/projects/{pid}/stitches?revision=1", headers=ALICE).json()
    assert abs(old["widthMm"] - 50) < 2


def test_export_requires_compile(client):
    pid, _ = upload(client, ALICE, SIMPLE_SVG)
    assert client.post(f"/api/v1/projects/{pid}/exports", json={"revision": 1}, headers=ALICE).status_code == 409


def test_active_job_limit(client):
    from services.core import db
    pid, _ = upload(client, ALICE, SIMPLE_SVG)
    user_id = None
    with db.get_engine().begin() as conn:
        user_id = conn.execute(select(db.projects.c.user_id).where(db.projects.c.id == pid)).scalar_one()
        for _ in range(3):
            conn.execute(insert(db.jobs).values(id=db.new_id(), project_id=pid, user_id=user_id, kind="compile",
                                                revision=1, status="compiling", progress=0))
    assert client.post(f"/api/v1/projects/{pid}/compile", json={"revision": 1}, headers=ALICE).status_code == 429


def test_engine_failure_is_reported(make_client):
    client = make_client(INKSTITCH_CMD=f"{sys.executable} {FAKE} fail -")
    pid, _ = upload(client, ALICE, SIMPLE_SVG)
    job = client.post(f"/api/v1/projects/{pid}/compile", json={"revision": 1}, headers=ALICE).json()
    assert job["status"] == "failed" and job["errorCode"] == "engine_failed"


def test_supabase_jwt(make_client):
    secret = "test-jwt-secret-with-enough-length-0123456789"
    client = make_client(EMB_AUTH_MODE="supabase", SUPABASE_JWT_SECRET=secret, EMB_SIGNING_SECRET="s" * 32)
    claims = {"sub": "user-123", "aud": "authenticated", "role": "authenticated", "exp": int(time.time()) + 60}
    good = jwt.encode(claims, secret, algorithm="HS256")
    assert client.get("/api/v1/projects", headers={"Authorization": f"Bearer {good}"}).status_code == 200
    bad = jwt.encode(claims, "wrong-secret-wrong-secret-wrong-secret!!", algorithm="HS256")
    assert client.get("/api/v1/projects", headers={"Authorization": f"Bearer {bad}"}).status_code == 401
    assert client.get("/api/v1/projects", headers=ALICE).status_code == 401  # dev header ignored
    expired = jwt.encode({**claims, "exp": int(time.time()) - 10}, secret, algorithm="HS256")
    assert client.get("/api/v1/projects", headers={"Authorization": f"Bearer {expired}"}).status_code == 401
