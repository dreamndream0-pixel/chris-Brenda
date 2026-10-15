"""Design JSON -> Ink/Stitch-parameterised SVG (the single compile input).

Only path elements with whitelisted, clamped parameters are written. Path
data is re-serialised by svgelements, never copied from user input.
"""
from __future__ import annotations

import re

import numpy as np
from lxml import etree
from svgelements import Path

from .engine import INKSTITCH_SVG_VERSION
from .fabrics import apply_detail, clamp_params, default_params

SVG_NS = "http://www.w3.org/2000/svg"
INKSCAPE_NS = "http://www.inkscape.org/namespaces/inkscape"
INKSTITCH_NS = "http://inkstitch.org/namespace"
NSMAP = {None: SVG_NS, "inkscape": INKSCAPE_NS, "inkstitch": INKSTITCH_NS}
_HEX = re.compile(r"^#[0-9a-f]{6}$")
RUNNING_STROKE_MM = 0.1
SATIN_SPLIT_MM = 7.0       # satin stitches longer than this are split (wide columns stay flat and secure)
TRIM_GAP_MM = 2.0          # within a region, jumps longer than this end in a trim


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


def _satin_attrs(p: dict, width_mm: float) -> dict[str, str]:
    underlay = bool(p.get("underlay", True))
    return {
        _ink("satin_column"): "True",
        _ink("zigzag_spacing_mm"): _fmt(float(p.get("zigzagSpacingMm", 0.4))),
        _ink("pull_compensation_mm"): _fmt(float(p.get("pullCompensationMm", 0.2))),
        _ink("center_walk_underlay"): _fmt(underlay),
        _ink("contour_underlay"): _fmt(underlay and width_mm >= 2.0),
        _ink("zigzag_underlay"): _fmt(underlay and width_mm >= 3.5),
        _ink("max_stitch_length_mm"): _fmt(SATIN_SPLIT_MM),
    }


def _ring(sub: Path, n: int = 48) -> np.ndarray:
    pts = sub.npoint(np.linspace(0, 1, n, endpoint=False))
    return np.asarray(pts, dtype=float)


def _inside(pt: np.ndarray, ring: np.ndarray) -> bool:
    x, y = pt
    xs, ys = ring[:, 0], ring[:, 1]
    xn, yn = np.roll(xs, -1), np.roll(ys, -1)
    crosses = (ys > y) != (yn > y)
    with np.errstate(divide="ignore", invalid="ignore"):
        xi = xs + (y - ys) * (xn - xs) / (yn - ys)
    return bool(np.count_nonzero(crosses & (x < xi)) % 2)


def split_components(d: str) -> list[str]:
    """Split an even-odd fill path into its separate islands (each outline with its own holes).

    Ink/Stitch joins the islands of one fill element with stitches or untrimmed jumps; as
    separate elements each one ends in a trim, so no thread is left running across the fabric."""
    subs = [Path(sub) for sub in Path(d).as_subpaths()]
    subs = [sub for sub in subs if len(sub) and sub.length(error=1e-3) > 0]
    if len(subs) < 2:
        return [d]
    rings = [_ring(sub) for sub in subs]
    areas = [abs(float(np.dot(r[:, 0], np.roll(r[:, 1], -1)) - np.dot(r[:, 1], np.roll(r[:, 0], -1)))) / 2
             for r in rings]
    containers = [[j for j in range(len(subs)) if j != i and areas[j] > areas[i] and _inside(rings[i][0], rings[j])]
                  for i in range(len(subs))]
    outers = [i for i in range(len(subs)) if len(containers[i]) % 2 == 0]
    if len(outers) < 2:
        return [d]
    groups: dict[int, list[int]] = {i: [i] for i in outers}
    for i in range(len(subs)):
        if i in groups:
            continue
        # A hole belongs to the smallest island around it.
        owner = min((j for j in containers[i] if j in groups), key=lambda j: areas[j], default=None)
        if owner is None:
            return [d]
        groups[owner].append(i)
    return [" ".join(subs[k].d() for k in groups[i]) for i in outers]


def _centerline(region: dict) -> dict | None:
    return (region.get("metrics") or {}).get("centerline")


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
        if stitch_type not in ("fill", "running", "satin"):
            raise CompileInputError("unsupported_stitch_type", f"{stitch_type} is not available")
        params = clamp_params(stitch_type, apply_detail(stitch_type, region.get("params", {}), design.get("detailLevel")))
        base_id = re.sub(r"[^\w-]", "_", str(region["id"]))[:56]
        if stitch_type == "satin" and region.get("satinPath") == "columns" and region.get("shape") != "line":
            _emit_columns(layer, region, design, params, hex_color, sx, sy, base_id)
            continue
        center = _centerline(region)
        if stitch_type == "satin" or (stitch_type == "running" and region.get("runningPath") == "centerline"):
            if not center:
                raise CompileInputError("missing_centerline", f"region {region['id']} has no centreline")
            d = Path(center["d"]).d()
        if stitch_type == "fill" and region.get("shape") == "line":
            raise CompileInputError("fill_needs_area", f"region {region['id']} is a line")

        parts = split_components(d) if stitch_type == "fill" else [d]
        for index, part in enumerate(parts):
            node = etree.SubElement(layer, f"{{{SVG_NS}}}path")
            node.set("id", base_id if len(parts) == 1 else f"{base_id}_{index + 1}")
            node.set("d", part)
            _style(node, stitch_type, region, params, center, hex_color, sx, sy)

    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


def _rails(d: str) -> list[list[tuple[float, float]]]:
    rails = []
    for sub in d.split("M")[1:]:
        rails.append([tuple(float(v) for v in pt.split(",")) for pt in sub.replace("L", " ").split()])
    return rails


def _rails_d(rails) -> str:
    return " ".join("M " + " L ".join(f"{x:.3f},{y:.3f}" for x, y in rail) for rail in rails)


def _emit_columns(layer, region: dict, design: dict, params: dict, hex_color: str, sx: float, sy: float,
                  base_id: str) -> None:
    """Auto-digitised satin: uncovered parts filled first, then one satin column per stroke branch."""
    cols = ((region.get("metrics") or {}).get("columns") or {})
    items = cols.get("items") or []
    if not items:
        raise CompileInputError("missing_columns", f"region {region['id']} has no satin columns")
    k = (sx + sy) / 2
    nodes = []
    if cols.get("patches"):
        fill = clamp_params("fill", apply_detail("fill", default_params(design["fabricPreset"], "fill"),
                                                 design.get("detailLevel")))
        for i, part in enumerate(split_components(Path(cols["patches"]).d())):
            node = etree.SubElement(layer, f"{{{SVG_NS}}}path")
            node.set("id", f"{base_id}_f{i + 1}")
            node.set("d", part)
            node.set("style", f"fill:{hex_color};stroke:none;fill-rule:evenodd")
            for key, value in _fill_attrs(fill).items():
                node.set(key, value)
            nodes.append((node, None, None))
    # Sew the columns in a chain: each one starts at the end nearest to where the last one stopped.
    pending = [(_rails(c["d"]), float(c["widthUnits"])) for c in items]
    pos = None
    while pending:
        best, rev, dist = 0, False, float("inf")
        for i, (rails, _) in enumerate(pending):
            if pos is None:
                break
            for r, (x, y) in ((False, rails[0][0]), (True, rails[0][-1])):
                dd = (x - pos[0]) ** 2 + (y - pos[1]) ** 2
                if dd < dist:
                    best, rev, dist = i, r, dd
        rails, width = pending.pop(best)
        if rev:
            rails = [rail[::-1] for rail in rails]
        node = etree.SubElement(layer, f"{{{SVG_NS}}}path")
        node.set("id", f"{base_id}_s{len(nodes) + 1}")
        node.set("d", _rails_d(rails))
        node.set("style", f"fill:none;stroke:{hex_color};stroke-width:{RUNNING_STROKE_MM / max(k, 1e-9):.6g}")
        for key, value in _satin_attrs(params, width * k).items():
            node.set(key, value)
        nodes.append((node, rails[0][0], rails[0][-1]))
        pos = rails[0][-1]
    # Trim only where the next column starts away from where this one ended.
    for i, (node, _, end) in enumerate(nodes):
        nxt = nodes[i + 1] if i + 1 < len(nodes) else None
        far = nxt is None or end is None or nxt[1] is None or \
            ((nxt[1][0] - end[0]) ** 2 + (nxt[1][1] - end[1]) ** 2) ** 0.5 * k > TRIM_GAP_MM
        if far:
            node.set(_ink("trim_after"), "True")


def _style(node, stitch_type: str, region: dict, params: dict, center: dict | None, hex_color: str,
           sx: float, sy: float) -> None:
    if stitch_type == "fill":
        rule = "evenodd" if region.get("fillRule") == "evenodd" else "nonzero"
        node.set("style", f"fill:{hex_color};stroke:none;fill-rule:{rule}")
        attrs = _fill_attrs(params)
    elif stitch_type == "satin":
        # Ink/Stitch turns a single stroke wider than its satin threshold into a satin column.
        width_units = float(center["widthUnits"])
        node.set("style", f"fill:none;stroke:{hex_color};stroke-width:{width_units:.6g};stroke-linecap:butt")
        attrs = _satin_attrs(params, width_units * (sx + sy) / 2)
    else:
        stroke_w = RUNNING_STROKE_MM / max(min(sx, sy), 1e-9)
        node.set("style", f"fill:none;stroke:{hex_color};stroke-width:{stroke_w:.6g}")
        attrs = _running_attrs(params)
    # Cut the thread after every element instead of leaving a jump or travel stitch between them.
    attrs[_ink("trim_after")] = "True"
    for key, value in attrs.items():
        node.set(key, value)
