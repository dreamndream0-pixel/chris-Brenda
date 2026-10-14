"""Geometry metrics, rule-based stitch choice, satin limits and colour reordering."""
import copy
from pathlib import Path

import pytest

from services.worker.geometry import analyze_design
from services.worker.rules import color_changes, plan_design, satin_blocker
from services.worker.svg_import import import_svg

UPLOADS = Path(__file__).resolve().parents[1] / "fixtures" / "uploads"


def _design(paths: dict, w=100, h=100):
    return {"geometry": {"viewBox": [0, 0, w, h]}, "sizeMm": {"width": w, "height": h}, "fabricPreset": "woven_cotton",
            "palette": [{"id": "c1", "hex": "#000000"}],
            "regions": [{"id": k, "svgPath": d, "colorId": "c1", "order": i, "stitchType": "fill", "params": {},
                         "shape": "area", "bbox": [0, 0, w, h]} for i, (k, d) in enumerate(paths.items(), 1)]}


SHAPES = {
    "thin": "M 10 10 L 90 10 L 90 10.6 L 10 10.6 Z",
    "ribbon": "M 10 50 A 40 40 0 0 1 90 50 L 87 50 A 37 37 0 0 0 13 50 Z",
    "ring": "M 50 20 A 30 30 0 1 1 49.99 20 Z M 50 22 A 28 28 0 1 0 50.01 22 Z",
    "rect": "M 10 70 L 20 70 L 20 75 L 10 75 Z",
    "H": "M 30 80 L 33 80 L 33 88 L 40 88 L 40 80 L 43 80 L 43 99 L 40 99 L 40 91 L 33 91 L 33 99 L 30 99 Z",
}


def test_centerlines_only_for_simple_strokes():
    m = analyze_design(_design(SHAPES))
    assert m["thin"]["centerline"] and m["ribbon"]["centerline"] and m["ring"]["centerline"]["closed"]
    assert m["H"]["centerline"] is None
    assert abs(m["ribbon"]["centerline"]["widthUnits"] - 3.0) < 0.3
    assert abs(m["ring"]["centerline"]["widthUnits"] - 2.0) < 0.3


def test_rule_choices():
    planned = {r["id"]: r for r in plan_design(_design(SHAPES), reorder=False)["regions"]}
    assert planned["thin"]["stitchType"] == "running" and planned["thin"]["runningPath"] == "centerline"
    assert planned["ribbon"]["stitchType"] == "satin" and planned["ring"]["stitchType"] == "satin"
    assert planned["rect"]["stitchType"] == "fill" and planned["H"]["stitchType"] == "fill"
    assert "zigzagSpacingMm" in planned["ribbon"]["params"]


def test_satin_limits_follow_size():
    d = plan_design(_design({"ribbon": SHAPES["ribbon"]}), reorder=False)
    region = d["regions"][0]
    assert satin_blocker(region, d) is None
    big = copy.deepcopy(d)
    big["sizeMm"] = {"width": 300, "height": 300}  # 3 mm stroke becomes 9 mm
    assert satin_blocker(big["regions"][0], big) == "satin_too_wide"


def test_reorder_respects_overlap():
    svg = b'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 40">
      <rect x="0" y="0" width="40" height="40" fill="#111111"/>
      <rect x="10" y="10" width="20" height="20" fill="#cc0000"/>
      <rect x="15" y="15" width="10" height="10" fill="#111111"/>
      <rect x="60" y="0" width="20" height="20" fill="#cc0000"/>
    </svg>'''
    d = import_svg(svg, 100)
    p = plan_design(d)
    order = [r["id"] for r in sorted(p["regions"], key=lambda r: r["order"])]
    # r3 sits on top of r2 (overlap) so it must stay after it; r4 overlaps nothing and joins r2.
    assert order.index("r3") > order.index("r2")
    assert order == ["r1", "r2", "r4", "r3"]
    assert color_changes(d) == 3 and color_changes(p) == 2


def test_badge_strokes_are_lines_and_colours_grouped():
    d = import_svg((UPLOADS / "two_color_badge.svg").read_bytes(), 70)
    p = plan_design(d)
    circle = next(r for r in p["regions"] if r["shape"] == "line")
    assert circle["stitchType"] == "running" and circle["runningPath"] == "centerline"
    assert color_changes(d) == 2 and color_changes(p) == 1


@pytest.mark.parametrize("width", [40, 140])
def test_wide_svg_stroke_becomes_satin_only_in_range(width):
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50"><path d="M5 25 L95 25" stroke="#000" stroke-width="3" fill="none"/></svg>'
    p = plan_design(import_svg(svg, width))
    r = p["regions"][0]
    w_mm = 3 * width / p["geometry"]["viewBox"][2]
    assert p["sizeMm"]["height"] >= 1  # a lone straight stroke still has its stroke height
    assert r["stitchType"] == ("satin" if 1.5 <= w_mm <= 6 else "running")
