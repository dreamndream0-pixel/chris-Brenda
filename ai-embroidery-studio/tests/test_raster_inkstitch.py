"""Raster fixtures through real Ink/Stitch. Runs only where INKSTITCH_CMD is set (~3-4 min)."""
import os
from pathlib import Path

import pytest

from services.worker.engine import compile_svg
from services.worker.raster_import import RasterOptions, import_raster
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
    svg = tmp_path / "design.svg"
    svg.write_bytes(compile_design(design))
    res = compile_svg(svg, tmp_path / "out", timeout_s=240)
    w, h = expected_extent_mm(design)
    rep = validate_file(res.files[".dst"], {"widthMm": w, "heightMm": h, "toleranceMm": 1.5, "colors": colors})
    assert rep.ok, rep.errors
