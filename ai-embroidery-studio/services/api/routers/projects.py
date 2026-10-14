"""Projects, uploads, design revisions, compile/export jobs and downloads (spec §9)."""
from __future__ import annotations

import copy
import json
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, insert, select, update

from services.api.auth import current_user
from services.core import db
from services.core.queue import enqueue
from services.core.settings import get_settings
from services.core.signing import sign, verify
from services.core.storage import get_storage, object_key
from services.worker.fabrics import FABRIC_PRESETS, SIZE_LIMITS_MM, default_params
from services.worker.svg_import import annotate_warnings
from services.worker.tasks import save_revision

router = APIRouter(prefix="/api/v1")
MIN_MM, MAX_MM = SIZE_LIMITS_MM
FabricPreset = str
ALLOWED_UPLOAD_TYPES = {"image/svg+xml": ".svg", "image/png": ".png", "image/jpeg": ".jpg"}
ALLOWED_SUFFIXES = {".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
PREVIEWABLE = {"source_preview", "quantized_preview"}
DOWNLOADABLE = {"export_zip", "dst", "pes", "design_svg", "spec_txt", "threadlist"}
DOWNLOAD_TYPES = {".zip": "application/zip", ".png": "image/png", ".dst": "application/octet-stream",
                  ".pes": "application/octet-stream", ".svg": "image/svg+xml", ".txt": "text/plain; charset=utf-8"}


# ---------- schemas ----------

class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    widthMm: float = Field(ge=MIN_MM, le=MAX_MM)
    heightMm: float | None = Field(default=None, ge=MIN_MM, le=MAX_MM)
    lockAspect: bool = True
    fabricPreset: FabricPreset = "woven_cotton"


class UploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=200)
    contentType: str
    sizeBytes: int = Field(gt=0)


class AnalyzeRequest(BaseModel):
    uploadId: str
    colors: int | None = Field(default=None, ge=1, le=6)       # raster only; None = auto
    removeBackground: bool = True                              # raster only
    backgroundHex: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    widthMm: float | None = Field(default=None, ge=MIN_MM, le=MAX_MM)


class SizeMm(BaseModel):
    width: float = Field(ge=MIN_MM, le=MAX_MM)
    height: float | None = Field(default=None, ge=MIN_MM, le=MAX_MM)  # ignored while aspect is locked


class RegionPatch(BaseModel):
    id: str
    stitchType: Literal["fill", "running"] | None = None
    colorId: str | None = None
    hidden: bool | None = None


class PalettePatch(BaseModel):
    id: str
    hex: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")


class DesignPatch(BaseModel):
    baseRevision: int
    sizeMm: SizeMm | None = None
    lockAspect: bool | None = None
    fabricPreset: FabricPreset | None = None
    regions: list[RegionPatch] | None = Field(default=None, max_length=2000)
    palette: list[PalettePatch] | None = Field(default=None, max_length=12)


class RevisionRequest(BaseModel):
    revision: int


# ---------- helpers ----------

def _owned_project(conn, project_id: str, user_id: str) -> dict:
    row = conn.execute(select(db.projects).where(db.projects.c.id == project_id,
                                                 db.projects.c.user_id == user_id)).mappings().first()
    if row is None:  # same answer for "missing" and "not yours": no existence leak
        raise HTTPException(404, "project_not_found")
    return dict(row)


def _check_fabric(fabric: str) -> None:
    if fabric not in FABRIC_PRESETS:
        raise HTTPException(422, "unknown_fabric_preset")


def _project_out(p: dict) -> dict:
    return {
        "id": p["id"], "name": p["name"], "fabricPreset": p["fabric_preset"], "status": p["status"],
        "currentRevision": p["current_revision"], "compiledRevision": p["compiled_revision"],
        "widthMm": p["width_mm"], "heightMm": p["height_mm"], "colorCount": p["color_count"],
        "stitchCount": p["stitch_count"], "createdAt": p["created_at"].isoformat(),
        "updatedAt": p["updated_at"].isoformat(),
    }


def _job_out(j: dict) -> dict:
    return {"jobId": j["id"], "projectId": j["project_id"], "kind": j["kind"], "revision": j["revision"],
            "status": j["status"], "progress": j["progress"], "errorCode": j["error_code"],
            "errorMessage": j["error_message"], "result": j["result"]}


def _create_job(user_id: str, project_id: str, kind: str, revision: int | None, params: dict | None = None) -> dict:
    with db.get_engine().begin() as conn:
        active = conn.execute(select(func.count()).select_from(db.jobs).where(
            db.jobs.c.user_id == user_id, db.jobs.c.status.in_(db.ACTIVE_JOB_STATUSES))).scalar_one()
        if active >= get_settings().max_active_jobs_per_user:
            raise HTTPException(429, "too_many_active_jobs")
        job_id = db.new_id()
        conn.execute(insert(db.jobs).values(id=job_id, project_id=project_id, user_id=user_id, kind=kind,
                                            revision=revision, status="queued", progress=0, params=params))
    try:
        enqueue(job_id)
    except Exception as exc:  # queue down: record it instead of leaving a phantom queued job
        with db.get_engine().begin() as conn:
            conn.execute(update(db.jobs).where(db.jobs.c.id == job_id).values(
                status="failed", error_code="queue_unavailable", error_message=type(exc).__name__))
    with db.get_engine().connect() as conn:
        return _job_out(conn.execute(select(db.jobs).where(db.jobs.c.id == job_id)).mappings().one())


def _revision_exists(conn, project_id: str, revision: int) -> None:
    hit = conn.execute(select(db.revisions.c.id).where(db.revisions.c.project_id == project_id,
                                                       db.revisions.c.revision == revision)).first()
    if hit is None:
        raise HTTPException(404, "revision_not_found")


# ---------- projects ----------

@router.get("/fabrics")
def list_fabrics():
    return [{"id": k, "label": v["label"]} for k, v in FABRIC_PRESETS.items()]


@router.post("/projects", status_code=201)
def create_project(body: ProjectCreate, user_id: str = Depends(current_user)):
    _check_fabric(body.fabricPreset)
    pid = db.new_id()
    with db.get_engine().begin() as conn:
        conn.execute(insert(db.projects).values(
            id=pid, user_id=user_id, name=body.name.strip(), fabric_preset=body.fabricPreset, status="draft",
            current_revision=0, width_mm=body.widthMm,
            height_mm=None if body.lockAspect else body.heightMm))
        return _project_out(_owned_project(conn, pid, user_id)) | {"lockAspect": body.lockAspect}


@router.get("/projects")
def list_projects(user_id: str = Depends(current_user)):
    with db.get_engine().connect() as conn:
        rows = conn.execute(select(db.projects).where(db.projects.c.user_id == user_id)
                            .order_by(db.projects.c.updated_at.desc()).limit(200)).mappings().all()
    return [_project_out(dict(r)) for r in rows]


@router.get("/projects/{project_id}")
def get_project(project_id: str, user_id: str = Depends(current_user)):
    with db.get_engine().connect() as conn:
        p = _owned_project(conn, project_id, user_id)
        design = None
        if p["current_revision"]:
            design = conn.execute(select(db.revisions.c.design_json).where(
                db.revisions.c.project_id == project_id,
                db.revisions.c.revision == p["current_revision"])).scalar_one()
        arts = conn.execute(select(db.artifacts.c.id, db.artifacts.c.kind, db.artifacts.c.revision,
                                   db.artifacts.c.size_bytes, db.artifacts.c.created_at)
                            .where(db.artifacts.c.project_id == project_id)
                            .order_by(db.artifacts.c.revision.desc())).mappings().all()
        jobs = conn.execute(select(db.jobs).where(db.jobs.c.project_id == project_id)
                            .order_by(db.jobs.c.created_at.desc()).limit(10)).mappings().all()
    return {
        "project": _project_out(p),
        "design": design,
        "artifacts": [{"id": a["id"], "kind": a["kind"], "revision": a["revision"], "sizeBytes": a["size_bytes"],
                       "createdAt": a["created_at"].isoformat()} for a in arts if a["kind"] in DOWNLOADABLE],
        "jobs": [_job_out(dict(j)) for j in jobs],
    }


# ---------- upload ----------

@router.post("/projects/{project_id}/upload-url")
def create_upload_url(project_id: str, body: UploadRequest, user_id: str = Depends(current_user)):
    settings = get_settings()
    suffix = "." + body.filename.lower().rsplit(".", 1)[-1] if "." in body.filename else ""
    if body.contentType not in ALLOWED_UPLOAD_TYPES or ALLOWED_SUFFIXES.get(suffix) != body.contentType:
        raise HTTPException(415, "unsupported_file_type")
    if body.sizeBytes > settings.max_upload_bytes:
        raise HTTPException(413, "file_too_large")
    upload_id = db.new_id()
    with db.get_engine().begin() as conn:
        _owned_project(conn, project_id, user_id)
        key = object_key(user_id, project_id, "uploads", f"{upload_id}{ALLOWED_UPLOAD_TYPES[body.contentType]}")
        safe_name = re.sub(r"[^\w.\- ]", "_", body.filename)[:200]
        conn.execute(insert(db.uploads).values(id=upload_id, project_id=project_id, user_id=user_id,
                                               filename=safe_name, content_type=body.contentType,
                                               declared_size=body.sizeBytes, storage_key=key, status="pending"))
    token, exp = sign("upload", upload_id, ttl_s=600)
    return {"uploadId": upload_id, "method": "PUT", "expiresAt": exp,
            "uploadUrl": f"{settings.public_api_url}/api/v1/uploads/{upload_id}?token={token}"}


@router.put("/uploads/{upload_id}", status_code=204)
async def receive_upload(upload_id: str, token: str, request: Request):
    """Local stand-in for a Storage signed upload URL: the token is the only credential."""
    claims = verify(token, "upload")
    if not claims or claims["s"] != upload_id:
        raise HTTPException(403, "invalid_or_expired_upload_token")
    with db.get_engine().connect() as conn:
        up = conn.execute(select(db.uploads).where(db.uploads.c.id == upload_id)).mappings().first()
    if up is None or up["status"] != "pending":
        raise HTTPException(409, "upload_not_pending")
    limit = min(up["declared_size"], get_settings().max_upload_bytes)
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > limit:
            raise HTTPException(413, "file_too_large")
    if not body:
        raise HTTPException(400, "empty_upload")
    get_storage().put(up["storage_key"], bytes(body))
    with db.get_engine().begin() as conn:
        conn.execute(update(db.uploads).where(db.uploads.c.id == upload_id).values(status="uploaded"))
    return Response(status_code=204)


@router.post("/projects/{project_id}/analyze", status_code=202)
def analyze(project_id: str, body: AnalyzeRequest, user_id: str = Depends(current_user)):
    with db.get_engine().connect() as conn:
        p = _owned_project(conn, project_id, user_id)
        up = conn.execute(select(db.uploads).where(db.uploads.c.id == body.uploadId,
                                                   db.uploads.c.project_id == project_id)).mappings().first()
    if up is None or up["status"] not in ("uploaded", "used"):
        raise HTTPException(409, "upload_not_ready")
    rerun = up["status"] == "used"
    params = {"uploadId": body.uploadId, "widthMm": body.widthMm or p["width_mm"],
              # A first analysis honours an unlocked height from project creation; re-runs keep the aspect.
              "heightMm": None if rerun else p["height_mm"], "colors": body.colors,
              "removeBackground": body.removeBackground, "backgroundHex": body.backgroundHex}
    return _create_job(user_id, project_id, "analyze", None, params)


# ---------- design revisions ----------

@router.patch("/projects/{project_id}/design")
def patch_design(project_id: str, body: DesignPatch, user_id: str = Depends(current_user)):
    with db.get_engine().begin() as conn:
        p = _owned_project(conn, project_id, user_id)
        if body.baseRevision != p["current_revision"] or not p["current_revision"]:
            raise HTTPException(409, "revision_conflict")
        design = copy.deepcopy(conn.execute(select(db.revisions.c.design_json).where(
            db.revisions.c.project_id == project_id, db.revisions.c.revision == p["current_revision"])).scalar_one())
        if body.lockAspect is not None:
            design["lockAspect"] = body.lockAspect
        if body.sizeMm is not None:
            width, height = body.sizeMm.width, body.sizeMm.height
            if design.get("lockAspect", True):
                _, _, vw, vh = design["geometry"]["viewBox"]
                height = round(width * vh / vw, 2)
                if not MIN_MM <= height <= MAX_MM:
                    raise HTTPException(422, "height_out_of_range")
            elif height is None:
                raise HTTPException(422, "height_required_when_unlocked")
            design["sizeMm"] = {"width": round(width, 2), "height": round(height, 2)}
        if body.fabricPreset is not None and body.fabricPreset != design["fabricPreset"]:
            _check_fabric(body.fabricPreset)
            design["fabricPreset"] = body.fabricPreset
            for region in design["regions"]:
                region["params"] = default_params(body.fabricPreset, region["stitchType"])
        if body.palette:
            by_id = {c["id"]: c for c in design["palette"]}
            for c in body.palette:
                if c.id not in by_id:
                    raise HTTPException(422, "unknown_color")
                by_id[c.id]["hex"] = c.hex.lower()
        if body.regions:
            regions = {r["id"]: r for r in design["regions"]}
            colors = {c["id"] for c in design["palette"]}
            for rp in body.regions:
                region = regions.get(rp.id)
                if region is None:
                    raise HTTPException(422, "unknown_region")
                if rp.colorId is not None:
                    if rp.colorId not in colors:
                        raise HTTPException(422, "unknown_color")
                    region["colorId"] = rp.colorId
                if rp.stitchType is not None and rp.stitchType != region["stitchType"]:
                    region["stitchType"] = rp.stitchType
                    region["params"] = default_params(design["fabricPreset"], rp.stitchType)
                if rp.hidden is not None:
                    region["hidden"] = rp.hidden
            if all(r.get("hidden") for r in design["regions"]):
                raise HTTPException(422, "all_regions_hidden")
        annotate_warnings(design)
        revision = save_revision(conn, p, design)
        design = conn.execute(select(db.revisions.c.design_json).where(
            db.revisions.c.project_id == project_id, db.revisions.c.revision == revision)).scalar_one()
    return {"revision": revision, "design": design}


# ---------- compile / stitches / export ----------

@router.post("/projects/{project_id}/compile", status_code=202)
def compile_revision(project_id: str, body: RevisionRequest, user_id: str = Depends(current_user)):
    with db.get_engine().connect() as conn:
        _owned_project(conn, project_id, user_id)
        _revision_exists(conn, project_id, body.revision)
    return _create_job(user_id, project_id, "compile", body.revision)


@router.get("/projects/{project_id}/stitches")
def get_stitches(project_id: str, revision: int | None = None, user_id: str = Depends(current_user)):
    with db.get_engine().connect() as conn:
        p = _owned_project(conn, project_id, user_id)
        revision = revision or p["compiled_revision"]
        art = conn.execute(select(db.artifacts.c.storage_key).where(
            db.artifacts.c.project_id == project_id, db.artifacts.c.revision == revision,
            db.artifacts.c.kind == "stitches")).first() if revision else None
    if art is None:
        raise HTTPException(404, "not_compiled")
    data = json.loads(get_storage().get(art[0]))
    return {"revision": revision, **data}


@router.post("/projects/{project_id}/exports", status_code=202)
def create_export(project_id: str, body: RevisionRequest, user_id: str = Depends(current_user)):
    with db.get_engine().connect() as conn:
        _owned_project(conn, project_id, user_id)
        compiled = conn.execute(select(db.artifacts.c.id).where(
            db.artifacts.c.project_id == project_id, db.artifacts.c.revision == body.revision,
            db.artifacts.c.kind == "dst")).first()
    if compiled is None:
        raise HTTPException(409, "not_compiled")
    return _create_job(user_id, project_id, "export", body.revision)


@router.get("/projects/{project_id}/exports/{artifact_id}")
def get_download_url(project_id: str, artifact_id: str, user_id: str = Depends(current_user)):
    with db.get_engine().connect() as conn:
        _owned_project(conn, project_id, user_id)
        art = conn.execute(select(db.artifacts).where(db.artifacts.c.id == artifact_id,
                                                      db.artifacts.c.project_id == project_id)).mappings().first()
    if art is None or art["kind"] not in DOWNLOADABLE:
        raise HTTPException(404, "artifact_not_found")
    settings = get_settings()
    token, exp = sign("download", art["id"], ttl_s=settings.signed_url_ttl_s)
    return {"url": f"{settings.public_api_url}/api/v1/files/{token}", "expiresAt": exp}


@router.get("/projects/{project_id}/previews")
def get_previews(project_id: str, revision: int, user_id: str = Depends(current_user)):
    """Short-lived URLs for the re-encoded original and the colour-separation preview (raster uploads)."""
    with db.get_engine().connect() as conn:
        _owned_project(conn, project_id, user_id)
        # Previews are made by the analysis that created the geometry; later edit revisions reuse them.
        arts = conn.execute(select(db.artifacts.c.id, db.artifacts.c.kind).where(
            db.artifacts.c.project_id == project_id, db.artifacts.c.revision <= revision,
            db.artifacts.c.kind.in_(PREVIEWABLE)).order_by(db.artifacts.c.revision.desc())).all()
    settings = get_settings()
    out = {}
    for art_id, kind in arts:
        if kind in out:
            continue
        token, _ = sign("preview", art_id, ttl_s=settings.signed_url_ttl_s)
        out[kind] = f"{settings.public_api_url}/api/v1/files/{token}"
    return out


@router.get("/files/{token}")
def download(token: str):
    claims = verify(token, "download")
    inline = False
    if not claims:
        claims = verify(token, "preview")
        inline = True
    if not claims:
        raise HTTPException(403, "invalid_or_expired_link")
    with db.get_engine().connect() as conn:
        art = conn.execute(select(db.artifacts).where(db.artifacts.c.id == claims["s"])).mappings().first()
    if art is None or (inline and art["kind"] not in PREVIEWABLE):
        raise HTTPException(404, "artifact_not_found")
    filename = art["storage_key"].rsplit("/", 1)[-1]
    suffix = "." + filename.rsplit(".", 1)[-1]
    disposition = "inline" if inline else f'attachment; filename="{filename}"'
    return Response(get_storage().get(art["storage_key"]), media_type=DOWNLOAD_TYPES.get(suffix, "application/octet-stream"),
                    headers={"Content-Disposition": disposition,
                             "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store",
                             "Content-Security-Policy": "default-src 'none'; sandbox"})


# ---------- jobs ----------

@router.get("/jobs/{job_id}")
def get_job(job_id: str, user_id: str = Depends(current_user)):
    with db.get_engine().connect() as conn:
        job = conn.execute(select(db.jobs).where(db.jobs.c.id == job_id, db.jobs.c.user_id == user_id)).mappings().first()
    if job is None:
        raise HTTPException(404, "job_not_found")
    return _job_out(dict(job))
