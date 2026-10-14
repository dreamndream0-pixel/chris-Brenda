"""Untrusted SVG -> sanitised geometry -> Design JSON (spec §5, §6 stages 1-2).

1. Parse with a hardened XML parser (no DTD, entities, network or huge trees).
2. Rebuild the document from an element/attribute allow-list; scripts, events,
   foreignObject, images, external references, <use>, CSS and url() paints
   are removed and reported as warnings.
3. Flatten transforms and shapes into absolute paths with svgelements.
4. Emit regions: filled shapes -> `fill`, stroke-only shapes -> `running`.

The original SVG is never rendered or embedded in a page.
"""
from __future__ import annotations

import re
from io import BytesIO

from lxml import etree
from svgelements import SVG, Matrix, Path, Shape

from .fabrics import SIZE_LIMITS_MM, default_params

SVG_NS = "http://www.w3.org/2000/svg"
MAX_BYTES = 8 * 1024 * 1024
MAX_ELEMENTS = 5000
MAX_SHAPES = 2000
MAX_SEGMENTS = 50000
MAX_COLORS = 12

ALLOWED_TAGS = {"svg", "g", "path", "rect", "circle", "ellipse", "line", "polyline", "polygon", "title", "desc"}
SHAPE_ATTRS = {"d", "x", "y", "width", "height", "cx", "cy", "r", "rx", "ry", "x1", "y1", "x2", "y2", "points"}
PAINT_ATTRS = {"fill", "stroke", "stroke-width", "fill-rule", "fill-opacity", "stroke-opacity", "opacity",
               "display", "visibility"}
ALLOWED_ATTRS = SHAPE_ATTRS | PAINT_ATTRS | {"id", "transform", "viewBox", "preserveAspectRatio", "style"}
ROOT_ONLY_ATTRS = {"viewBox", "preserveAspectRatio", "width", "height"}
UNSAFE_TAGS = {"script", "foreignObject", "iframe", "object", "embed", "image", "use", "a", "animate",
               "set", "animateTransform", "animateMotion", "handler", "listener"}
_SAFE_VALUE = re.compile(r"^[\w\s#.,%()+\-]*$")
_NUMBER_LIST = re.compile(r"^[\d\s.,eE+\-]+$")


class ImportError_(Exception):
    """Rejected upload; `code` is shown to the user."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _local(tag) -> str:
    return etree.QName(tag).localname if isinstance(tag, str) else ""


def sanitize_svg(data: bytes) -> tuple[bytes, list[str]]:
    """Return a rebuilt, allow-listed SVG plus warnings, or raise ImportError_."""
    if len(data) > MAX_BYTES:
        raise ImportError_("file_too_large", "SVG exceeds 8 MB")
    head = data[:4096].lower()
    if b"<!doctype" in head or b"<!entity" in data.lower():
        raise ImportError_("doctype_not_allowed", "SVG must not contain DOCTYPE or ENTITY declarations")

    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False,
                             remove_comments=True, remove_pis=True)
    try:
        src = etree.fromstring(data, parser)
    except etree.XMLSyntaxError as exc:
        raise ImportError_("invalid_svg", f"cannot parse SVG: {exc}") from exc
    if _local(src.tag) != "svg" or etree.QName(src.tag).namespace not in (SVG_NS, None):
        raise ImportError_("invalid_svg", "root element is not <svg>")

    warnings: set[str] = set()
    count = 0

    def copy(node, parent):
        nonlocal count
        for child in node:
            count += 1
            if count > MAX_ELEMENTS:
                raise ImportError_("too_complex", f"more than {MAX_ELEMENTS} elements")
            name = _local(child.tag)
            ns = etree.QName(child.tag).namespace if isinstance(child.tag, str) else None
            if ns not in (SVG_NS, None):
                continue  # editor metadata (inkscape:, sodipodi:) - silently dropped
            if name not in ALLOWED_TAGS:
                if name in UNSAFE_TAGS:
                    warnings.add("unsafe_content_removed")
                elif name in ("text", "tspan", "textPath"):
                    warnings.add("text_not_supported_convert_to_outlines")
                elif name not in ("defs", "metadata", "style", "namedview"):
                    warnings.add(f"unsupported_element_removed:{name}")
                elif name == "style":
                    warnings.add("css_ignored")
                continue
            out = etree.SubElement(parent, f"{{{SVG_NS}}}{name}")
            _copy_attrs(child, out, warnings)
            if name in ("title", "desc"):
                continue
            copy(child, out)

    root = etree.Element(f"{{{SVG_NS}}}svg", nsmap={None: SVG_NS})
    for attr in ROOT_ONLY_ATTRS:
        value = src.get(attr)
        if value is not None and _SAFE_VALUE.match(value):
            root.set(attr, value)
    _check_viewbox(root.get("viewBox"))
    copy(src, root)
    return etree.tostring(root), sorted(warnings)


def _copy_attrs(src, dst, warnings: set[str]) -> None:
    for key, value in src.attrib.items():
        if etree.QName(key).namespace is not None:
            continue  # xlink:href, inkscape:*, etc.
        if key.startswith("on"):
            warnings.add("unsafe_content_removed")
            continue
        if key not in ALLOWED_ATTRS:
            continue
        if key == "style":
            style = _filter_style(value, warnings)
            if style:
                dst.set("style", style)
            continue
        if "url(" in value.replace(" ", "").lower():
            warnings.add("gradient_or_pattern_replaced")
            continue
        if key in ("d", "points") or _SAFE_VALUE.match(value):
            dst.set(key, value)


def _filter_style(style: str, warnings: set[str]) -> str:
    kept = []
    for decl in style.split(";"):
        if ":" not in decl:
            continue
        prop, val = (s.strip() for s in decl.split(":", 1))
        if prop not in PAINT_ATTRS:
            continue
        if "url(" in val.lower() or not _SAFE_VALUE.match(val):
            warnings.add("gradient_or_pattern_replaced")
            continue
        kept.append(f"{prop}:{val}")
    return ";".join(kept)


def _check_viewbox(viewbox: str | None) -> None:
    if not viewbox:
        raise ImportError_("missing_viewbox", "SVG must have a viewBox")
    parts = viewbox.replace(",", " ").split()
    try:
        _, _, w, h = (float(p) for p in parts)
    except ValueError as exc:
        raise ImportError_("invalid_viewbox", "viewBox must be four numbers") from exc
    if w <= 0 or h <= 0 or w / h > 100 or h / w > 100:
        raise ImportError_("invalid_viewbox", "viewBox has invalid or extreme proportions")


def _hex(color) -> str | None:
    if color is None or color.value is None:
        return None
    if color.opacity is not None and color.opacity <= 0:
        return None
    return "#%02x%02x%02x" % (color.red, color.green, color.blue)


def _visible(el) -> bool:
    v = el.values
    if str(v.get("display", "")).strip() == "none" or str(v.get("visibility", "")).strip() == "hidden":
        return False
    try:
        return float(v.get("opacity", 1)) > 0
    except ValueError:
        return True


def import_svg(data: bytes, width_mm: float, fabric: str = "woven_cotton",
               height_mm: float | None = None) -> dict:
    """Return a revision-1 Design JSON for an uploaded SVG."""
    clean, warnings = sanitize_svg(data)
    svg = SVG.parse(BytesIO(clean), reify=True)

    raw = []  # (kind, hex, path, fill_rule)
    shapes = segments = 0
    for el in svg.elements():
        if not isinstance(el, Shape) or not _visible(el):
            continue
        path = Path(el)
        if len(path) == 0:
            continue
        shapes += 1
        segments += len(path)
        if shapes > MAX_SHAPES or segments > MAX_SEGMENTS:
            raise ImportError_("too_complex", "SVG has too many shapes or path segments")
        fill = _hex(el.fill)
        try:
            fill_opacity = float(el.values.get("fill-opacity", 1))
        except ValueError:
            fill_opacity = 1.0
        if fill and fill_opacity > 0:
            raw.append(("fill", fill, path, el.values.get("fill-rule", "nonzero")))
        stroke = _hex(el.stroke)
        if stroke and (el.stroke_width or 0) > 0:
            raw.append(("running", stroke, path, None))

    if not raw:
        raise ImportError_("no_embroiderable_shapes", "SVG contains no visible filled or stroked shapes")

    boxes = [r[2].bbox() for r in raw]
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    bw = max(b[2] for b in boxes) - x0
    bh = max(b[3] for b in boxes) - y0
    if bw <= 0 or bh <= 0:
        raise ImportError_("degenerate_geometry", "design has zero width or height")

    palette: dict[str, str] = {}
    regions = []
    shift = Matrix(f"translate({-x0},{-y0})")
    for i, (kind, hex_color, path, rule) in enumerate(raw, start=1):
        if hex_color not in palette:
            palette[hex_color] = f"c{len(palette) + 1}"
        moved = path * shift
        moved.reify()
        bx0, by0, bx1, by1 = moved.bbox()
        regions.append({
            "id": f"r{i}",
            "name": f"{'填針' if kind == 'fill' else '平針'} {i}",
            "svgPath": moved.d(),
            "fillRule": rule if rule in ("nonzero", "evenodd") else "nonzero",
            "colorId": palette[hex_color],
            "order": i,
            "stitchType": kind,
            "params": default_params(fabric, kind),
            "bbox": [round(bx0, 4), round(by0, 4), round(bx1, 4), round(by1, 4)],
            "warnings": [],
        })
    if len(palette) > MAX_COLORS:
        raise ImportError_("too_many_colors", f"more than {MAX_COLORS} colours; simplify the artwork")

    lo, hi = SIZE_LIMITS_MM
    width_mm = min(max(float(width_mm), lo), hi)
    if height_mm is None:
        height_mm = width_mm * bh / bw
    design = {
        "schemaVersion": 1,
        "revision": 1,
        "sizeMm": {"width": round(width_mm, 2), "height": round(min(max(height_mm, 1.0), hi), 2)},
        "lockAspect": True,
        "fabricPreset": fabric,
        "geometry": {"viewBox": [0, 0, round(bw, 4), round(bh, 4)]},
        "palette": [{"id": cid, "hex": hx, "threadCode": None} for hx, cid in palette.items()],
        "regions": regions,
        "warnings": warnings + (["many_colors"] if len(palette) > 6 else []),
    }
    annotate_warnings(design)
    return design


def annotate_warnings(design: dict) -> dict:
    """Recompute size-dependent region warnings for the design's current mm size."""
    _, _, vw, vh = design["geometry"]["viewBox"]
    sx = design["sizeMm"]["width"] / vw
    sy = design["sizeMm"]["height"] / vh
    for region in design["regions"]:
        x0, y0, x1, y1 = region["bbox"]
        w, h = (x1 - x0) * sx, (y1 - y0) * sy
        warns = []
        if region["stitchType"] == "fill" and min(w, h) < 1.0:
            warns.append("narrow_fill_under_1mm")
        if max(w, h) < 0.5:
            warns.append("tiny_region")
        region["warnings"] = warns
    return design
