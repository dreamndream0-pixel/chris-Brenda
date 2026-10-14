"""Background jobs: analyze (SVG upload -> Design JSON), compile (revision -> DST/PES), export (ZIP).

Each job writes only artifacts of its own revision, so a slow job for an old
revision can never overwrite the results of a newer one.
"""
from __future__ import annotations

import io
import json
import tempfile
import traceback
import zipfile
from pathlib import Path

from sqlalchemy import insert, select, update

from services.core import db
from services.core.storage import get_storage, object_key

from .engine import EngineError, compile_svg
from .fabrics import FABRIC_PRESETS
from .preview import stitch_sequence
from .svg_compile import CompileInputError, compile_design
from .svg_import import ImportError_, annotate_warnings, import_svg
from .validate import compare_exports, validate_file

INKSTITCH_VERSION = "v3.3.0"


class JobFailure(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _set(job_id: str, **values) -> None:
    with db.get_engine().begin() as conn:
        conn.execute(update(db.jobs).where(db.jobs.c.id == job_id).values(updated_at=db.now(), **values))


def run_job(job_id: str) -> None:
    with db.get_engine().connect() as conn:
        job = conn.execute(select(db.jobs).where(db.jobs.c.id == job_id)).mappings().first()
    if job is None or job["status"] not in ("queued",):
        return
    handler = {"analyze": _analyze, "compile": _compile, "export": _export}.get(job["kind"])
    try:
        if handler is None:
            raise JobFailure("unknown_job_kind", job["kind"])
        result = handler(dict(job))
        _set(job_id, status="ready", progress=100, result=result)
    except (JobFailure, ImportError_, CompileInputError, EngineError) as exc:
        _set(job_id, status="failed", error_code=exc.code, error_message=str(exc)[:2000])
    except Exception as exc:  # noqa: BLE001 - never leave a job stuck in a running state
        traceback.print_exc()
        _set(job_id, status="failed", error_code="internal_error", error_message=type(exc).__name__)


def _project(conn, project_id: str) -> dict:
    row = conn.execute(select(db.projects).where(db.projects.c.id == project_id)).mappings().first()
    if row is None:
        raise JobFailure("project_not_found", project_id)
    return dict(row)


def _design(conn, project_id: str, revision: int) -> dict:
    row = conn.execute(select(db.revisions.c.design_json).where(
        db.revisions.c.project_id == project_id, db.revisions.c.revision == revision)).first()
    if row is None:
        raise JobFailure("revision_not_found", f"revision {revision}")
    return row[0]


def save_revision(conn, project: dict, design: dict) -> int:
    revision = project["current_revision"] + 1
    design = {**design, "projectId": project["id"], "revision": revision}
    conn.execute(insert(db.revisions).values(id=db.new_id(), project_id=project["id"], revision=revision,
                                             design_json=design))
    conn.execute(update(db.projects).where(db.projects.c.id == project["id"]).values(
        current_revision=revision, width_mm=design["sizeMm"]["width"], height_mm=design["sizeMm"]["height"],
        fabric_preset=design["fabricPreset"], color_count=len(design["palette"]), updated_at=db.now()))
    get_storage().put(object_key(project["user_id"], project["id"], revision, "design.json"),
                      json.dumps(design, ensure_ascii=False).encode())
    return revision


def _put_artifact(conn, project: dict, revision: int, job_id: str, kind: str, filename: str, data: bytes) -> None:
    key = object_key(project["user_id"], project["id"], revision, filename)
    checksum = get_storage().put(key, data)
    table = db.artifacts
    existing = conn.execute(select(table.c.id).where(table.c.project_id == project["id"],
                                                     table.c.revision == revision, table.c.kind == kind)).first()
    values = dict(job_id=job_id, storage_key=key, checksum=checksum, size_bytes=len(data), created_at=db.now())
    if existing:
        conn.execute(update(table).where(table.c.id == existing[0]).values(**values))
    else:
        conn.execute(insert(table).values(id=db.new_id(), project_id=project["id"], revision=revision,
                                          kind=kind, **values))


def _analyze(job: dict) -> dict:
    params = job["params"] or {}
    _set(job["id"], status="preprocessing", progress=10)
    with db.get_engine().connect() as conn:
        project = _project(conn, job["project_id"])
        upload = conn.execute(select(db.uploads).where(db.uploads.c.id == params.get("uploadId"),
                                                       db.uploads.c.project_id == project["id"])).mappings().first()
    if upload is None or upload["status"] != "uploaded":
        raise JobFailure("upload_missing", "upload not found or not finished")
    data = get_storage().get(upload["storage_key"])

    _set(job["id"], status="planning", progress=40)
    design = import_svg(data, width_mm=params.get("widthMm") or project["width_mm"] or 50,
                        fabric=project["fabric_preset"], height_mm=params.get("heightMm"))
    design["lockAspect"] = params.get("lockAspect", True)
    design["source"] = {"uploadId": upload["id"], "filename": upload["filename"]}

    with db.get_engine().begin() as conn:
        project = _project(conn, job["project_id"])
        revision = save_revision(conn, project, design)
        conn.execute(update(db.uploads).where(db.uploads.c.id == upload["id"]).values(status="used"))
    _set(job["id"], revision=revision)
    return {"revision": revision, "regions": len(design["regions"]), "colors": len(design["palette"]),
            "warnings": design["warnings"], "sizeMm": design["sizeMm"]}


def _expected_color_blocks(design: dict) -> int:
    blocks, last = 0, None
    for region in sorted(design["regions"], key=lambda r: r["order"]):
        if region.get("hidden"):
            continue
        if region["colorId"] != last:
            blocks, last = blocks + 1, region["colorId"]
    return blocks


def _compile(job: dict) -> dict:
    revision = job["revision"]
    _set(job["id"], status="compiling", progress=20)
    with db.get_engine().connect() as conn:
        project = _project(conn, job["project_id"])
        design = annotate_warnings(_design(conn, project["id"], revision))
    svg = compile_design(design)

    with tempfile.TemporaryDirectory(prefix="emb-compile-") as tmp:
        tmp_dir = Path(tmp)
        (tmp_dir / "design.svg").write_bytes(svg)
        compiled = compile_svg(tmp_dir / "design.svg", tmp_dir / "out")

        _set(job["id"], status="validating", progress=75)
        size = design["sizeMm"]
        tol = max(1.5, 0.03 * max(size["width"], size["height"]))
        expected = {"widthMm": size["width"], "heightMm": size["height"], "toleranceMm": tol}
        dst = validate_file(compiled.files[".dst"], expected)
        pes = validate_file(compiled.files[".pes"], expected)
        errors = dst.errors + [f"pes.{e}" for e in pes.errors]
        if errors:
            raise JobFailure("validation_failed", "; ".join(errors))
        warnings = sorted(set(dst.warnings + pes.warnings + compare_exports(dst, pes)))
        if dst.summary.color_blocks != _expected_color_blocks(design):
            warnings.append("color_blocks_differ_from_design")
        region_warnings = sorted({w for r in design["regions"] for w in r["warnings"]})
        preview = stitch_sequence(compiled.files[".dst"], palette_source=compiled.files[".pes"])
        # DST stores no colours and PES snaps them; show the design's own palette in order of use.
        order = [r["colorId"] for r in sorted(design["regions"], key=lambda r: r["order"]) if not r.get("hidden")]
        hexes = {c["id"]: c["hex"] for c in design["palette"]}
        seq = [hexes[c] for i, c in enumerate(order) if i == 0 or c != order[i - 1]]
        if len(seq) == preview["summary"]["color_blocks"]:
            preview["colors"] = seq

        summary = dst.summary.to_dict()
        report = {"revision": revision, "engine": f"Ink/Stitch {INKSTITCH_VERSION}", "dst": dst.to_dict(),
                  "pes": pes.to_dict(), "warnings": warnings, "regionWarnings": region_warnings}
        files = {
            "design_svg": ("design.svg", svg),
            "dst": ("result.dst", compiled.files[".dst"].read_bytes()),
            "pes": ("result.pes", compiled.files[".pes"].read_bytes()),
            "stitches": ("stitches.json", json.dumps(preview, separators=(",", ":")).encode()),
            "report": ("report.json", json.dumps(report, ensure_ascii=False, indent=2).encode()),
        }
        if ".txt" in compiled.files:
            files["threadlist"] = ("threadlist.txt", compiled.files[".txt"].read_bytes())

    with db.get_engine().begin() as conn:
        for kind, (filename, data) in files.items():
            _put_artifact(conn, project, revision, job["id"], kind, filename, data)
        current = _project(conn, project["id"])
        if (current["compiled_revision"] or 0) <= revision:
            conn.execute(update(db.projects).where(db.projects.c.id == project["id"]).values(
                compiled_revision=revision, stitch_count=summary["stitches"], updated_at=db.now()))
    return {"revision": revision, "widthMm": summary["width_mm"], "heightMm": summary["height_mm"],
            "stitches": summary["stitches"], "colorChanges": summary["color_changes"],
            "jumps": summary["jumps"], "trims": summary["trims"], "colorBlocks": summary["color_blocks"],
            "warnings": warnings + region_warnings, "artifacts": sorted(files)}


def _spec_text(design: dict, report: dict) -> str:
    s = report["dst"]["summary"]
    fabric = FABRIC_PRESETS.get(design["fabricPreset"], {}).get("label", design["fabricPreset"])
    lines = [
        "AI Embroidery Studio — 工廠規格（技術匯出，需試繡確認）",
        f"專案：{design.get('projectId')}  版本：revision {design['revision']}",
        f"轉換引擎：{report['engine']}",
        f"設計尺寸：{design['sizeMm']['width']} × {design['sizeMm']['height']} mm",
        f"實際針跡範圍：{s['width_mm']} × {s['height_mm']} mm",
        f"針數：{s['stitches']}  換色：{s['color_changes']}  跳針：{s['jumps']}  剪線：{s['trims']}",
        f"布料：{fabric}（襯紙：待工廠確認）",
        "",
        "線色順序（DST 不含線色資訊，請依此表上線）：",
    ]
    hexes = {c["id"]: c for c in design["palette"]}
    seen = []
    for r in sorted(design["regions"], key=lambda r: r["order"]):
        if not r.get("hidden") and (not seen or seen[-1] != r["colorId"]):
            seen.append(r["colorId"])
    for i, cid in enumerate(seen, start=1):
        c = hexes[cid]
        lines.append(f"  {i}. {c['hex']}  線號：{c.get('threadCode') or '待指定'}")
    warnings = report["warnings"] + report.get("regionWarnings", [])
    lines += ["", "警告：" + ("、".join(warnings) if warnings else "無"),
              "", "注意：PES 內的線色已被吸附到 Brother 色票，僅供參考；請以本表為準。",
              "技術匯出成功不代表生產品質，請先以相同布料與襯紙試繡。"]
    return "\n".join(lines) + "\n"


def _export(job: dict) -> dict:
    revision = job["revision"]
    _set(job["id"], status="exporting", progress=30)
    with db.get_engine().connect() as conn:
        project = _project(conn, job["project_id"])
        design = _design(conn, project["id"], revision)
        rows = conn.execute(select(db.artifacts).where(db.artifacts.c.project_id == project["id"],
                                                       db.artifacts.c.revision == revision)).mappings().all()
    by_kind = {r["kind"]: r for r in rows}
    if not {"dst", "pes", "design_svg", "report"} <= set(by_kind):
        raise JobFailure("not_compiled", f"revision {revision} has no successful compile")
    storage = get_storage()
    report = json.loads(storage.get(by_kind["report"]["storage_key"]))
    spec = _spec_text(design, report)
    base = f"embroidery_r{revision}"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{base}.dst", storage.get(by_kind["dst"]["storage_key"]))
        z.writestr(f"{base}.pes", storage.get(by_kind["pes"]["storage_key"]))
        z.writestr(f"{base}_inkstitch.svg", storage.get(by_kind["design_svg"]["storage_key"]))
        if "threadlist" in by_kind:
            z.writestr(f"{base}_threadlist.txt", storage.get(by_kind["threadlist"]["storage_key"]))
        z.writestr(f"{base}_spec.txt", spec)
        z.writestr(f"{base}_spec.json", json.dumps({"design": {k: design[k] for k in (
            "sizeMm", "fabricPreset", "palette")}, "report": report}, ensure_ascii=False, indent=2))
    with db.get_engine().begin() as conn:
        _put_artifact(conn, project, revision, job["id"], "export_zip", f"{base}.zip", buf.getvalue())
        _put_artifact(conn, project, revision, job["id"], "spec_txt", "spec.txt", spec.encode())
        if project["status"] == "draft":
            conn.execute(update(db.projects).where(db.projects.c.id == project["id"]).values(
                status="awaiting_test_sew", updated_at=db.now()))
    return {"revision": revision, "artifacts": ["export_zip", "spec_txt"]}
