"""Design JSON -> Ink/Stitch-parameterised SVG (the single compile input).

Only path elements with whitelisted, clamped parameters are written. Path
data is re-serialised by svgelements, never copied from user input.
"""
from __future__ import annotations

import re

from lxml import etree
from svgelements import Path

from .engine import INKSTITCH_SVG_VERSION
from .fabrics import clamp_params

SVG_NS = "http://www.w3.org/2000/svg"
INKSCAPE_NS = "http://www.inkscape.org/namespaces/inkscape"
INKSTITCH_NS = "http://inkstitch.org/namespace"
NSMAP = {None: SVG_NS, "inkscape": INKSCAPE_NS, "inkstitch": INKSTITCH_NS}
_HEX = re.compile(r"^#[0-9a-f]{6}$")
RUNNING_STROKE_MM = 0.1


class CompileInputError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _ink(name: str) -> str:
    return f"{{{INKSTITCH_NS}}}{name}"


def _fmt(v) -> str:
    if isinstance(v, bool):
        return "True" if v else "False"
    return f"{v:g}" if isinstance(v, float) else str(v)


def _fill_attrs(p: dict) -> dict[str, str]:
    return {
        _ink("fill_method"): "tatami_fill",
        _ink("angle"): _fmt(float(p.get("fillAngleDeg", 45))),
        _ink("row_spacing_mm"): _fmt(float(p.get("rowSpacingMm", 0.4))),
        _ink("max_stitch_length_mm"): _fmt(float(p.get("maxStitchLengthMm", 3.0))),
        _ink("fill_underlay"): _fmt(bool(p.get("underlay", True))),
        _ink("pull_compensation_mm"): _fmt(float(p.get("pullCompensationMm", 0.0))),
    }


def _running_attrs(p: dict) -> dict[str, str]:
    return {
        _ink("stroke_method"): "running_stitch",
        _ink("running_stitch_length_mm"): _fmt(float(p.get("runningStitchLengthMm", 2.0))),
        _ink("repeats"): _fmt(int(p.get("repeats", 1))),
    }


def compile_design(design: dict) -> bytes:
    if design.get("schemaVersion") != 1:
        raise CompileInputError("unsupported_schema", "schemaVersion must be 1")
    w_mm = float(design["sizeMm"]["width"])
    h_mm = float(design["sizeMm"]["height"])
    _, _, vw, vh = (float(v) for v in design["geometry"]["viewBox"])
    if min(w_mm, h_mm, vw, vh) <= 0:
        raise CompileInputError("invalid_size", "size and viewBox must be positive")
    sx, sy = w_mm / vw, h_mm / vh
    colors = {c["id"]: c["hex"].lower() for c in design["palette"]}

    root = etree.Element(f"{{{SVG_NS}}}svg", nsmap=NSMAP)
    root.set("width", f"{w_mm:g}mm")
    root.set("height", f"{h_mm:g}mm")
    root.set("viewBox", f"0 0 {w_mm:g} {h_mm:g}")
    meta = etree.SubElement(root, f"{{{SVG_NS}}}metadata")
    etree.SubElement(meta, _ink("inkstitch_svg_version")).text = str(INKSTITCH_SVG_VERSION)

    layer = etree.SubElement(root, f"{{{SVG_NS}}}g")
    layer.set("id", "layer1")
    layer.set(f"{{{INKSCAPE_NS}}}groupmode", "layer")
    layer.set(f"{{{INKSCAPE_NS}}}label", "design")
    layer.set("transform", f"matrix({sx:.8g},0,0,{sy:.8g},0,0)")

    regions = sorted(design["regions"], key=lambda r: (r.get("order", 0), r["id"]))
    if not regions:
        raise CompileInputError("no_regions", "design has no regions")
    for region in regions:
        if region.get("hidden"):
            continue
        hex_color = colors.get(region["colorId"])
        if not hex_color or not _HEX.match(hex_color):
            raise CompileInputError("invalid_color", f"region {region['id']} has no valid colour")
        try:
            d = Path(region["svgPath"]).d()
        except Exception as exc:  # noqa: BLE001
            raise CompileInputError("invalid_path", f"region {region['id']} path is invalid") from exc
        if not d:
            continue
        stitch_type = region["stitchType"]
        if stitch_type not in ("fill", "running"):
            raise CompileInputError("unsupported_stitch_type", f"{stitch_type} is not available yet")
        params = clamp_params(stitch_type, region.get("params", {}))

        node = etree.SubElement(layer, f"{{{SVG_NS}}}path")
        node.set("id", re.sub(r"[^\w-]", "_", str(region["id"]))[:64])
        node.set("d", d)
        if stitch_type == "fill":
            rule = "evenodd" if region.get("fillRule") == "evenodd" else "nonzero"
            node.set("style", f"fill:{hex_color};stroke:none;fill-rule:{rule}")
            attrs = _fill_attrs(params)
        else:
            stroke_w = RUNNING_STROKE_MM / max(min(sx, sy), 1e-9)
            node.set("style", f"fill:none;stroke:{hex_color};stroke-width:{stroke_w:.6g}")
            attrs = _running_attrs(params)
        for key, value in attrs.items():
            node.set(key, value)

    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")
