"""Raster fixtures through real Ink/Stitch. Runs only where INKSTITCH_CMD is set (~3-4 min)."""
import os
from pathlib import Path

import pytest

from services.worker.engine import compile_svg
from services.worker.raster_import import RasterOptions, import_raster
from services.worker.rules import plan_design
from services.worker.svg_import import import_svg
from services.worker.svg_compile import compile_design
from services.worker.tasks import expected_extent_mm
from services.worker.validate import validate_file

pytestmark = pytest.mark.skipif(not os.environ.get("INKSTITCH_CMD"), reason="INKSTITCH_CMD not set")
RASTER = Path(__file__).resolve().parents[1] / "fixtures" / "raster"


@pytest.mark.parametrize("name,width,colors", [
    ("wordmark_chue.png", 80, 1),
    ("two_color_transparent.png", 70, 2),
    ("mascot.jpg", 70, 3),
])
def test_raster_fixture_compiles(tmp_path, name, width, colors):
    design, *_ = import_raster((RASTER / name).read_bytes(), width, "woven_cotton", RasterOptions())
    design = plan_design(design)  # same as the analyze job
    print(name, {r["id"]: r["stitchType"] for r in design["regions"]})
    svg = tmp_path / "design.svg"
    svg.write_bytes(compile_design(design))
    res = compile_svg(svg, tmp_path / "out", timeout_s=240)
    w, h = expected_extent_mm(design)
    rep = validate_file(res.files[".dst"], {"widthMm": w, "heightMm": h, "toleranceMm": 1.5, "colors": colors})
    assert rep.ok, rep.errors


SATIN_SVG = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 60">
<path d="M10 40 C 30 5, 70 5, 90 40" fill="none" stroke="#1f2a44" stroke-width="3"/>
<path d="M10 50 L 90 50" fill="none" stroke="#c0392b" stroke-width="0.4"/>
<path d="M10 55 C 40 52, 60 58, 90 55 L 90 58.5 C 60 61.5, 40 55.5, 10 58.5 Z" fill="#1f2a44"/>
<rect x="40" y="20" width="20" height="15" fill="#c0392b"/></svg>"""


def test_planned_satin_and_centerline_compile(tmp_path):
    design = plan_design(import_svg(SATIN_SVG, 100))
    kinds = sorted(r["stitchType"] for r in design["regions"])
    assert kinds == ["fill", "running", "satin", "satin"]
    svg = tmp_path / "design.svg"
    svg.write_bytes(compile_design(design))
    res = compile_svg(svg, tmp_path / "out", timeout_s=240)
    w, h = expected_extent_mm(design)
    rep = validate_file(res.files[".dst"], {"widthMm": w, "heightMm": h, "toleranceMm": 1.5, "colors": 2})
    assert rep.ok, rep.errors
