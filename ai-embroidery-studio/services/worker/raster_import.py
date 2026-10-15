"""PNG/JPG -> background removal -> Lab colour quantisation -> cleanup -> VTracer -> Design JSON.

Spec §6 stage 2 (deterministic computer vision, no AI). Each colour becomes
one disjoint binary mask that VTracer traces separately, so regions never
overlap (overlapping fills would be stitched twice). The traced SVG then goes
through the same sanitiser/import path as uploaded SVGs.
"""
from __future__ import annotations

import io
from dataclasses import dataclass

import cv2
import numpy as np
import vtracer
from PIL import Image, ImageOps
from svgelements import SVG, Path, Shape

from .svg_import import ImportError_, import_svg

MAX_BYTES = 8 * 1024 * 1024
MAX_PIXELS_SIDE = 4096
MIN_PIXELS_SIDE = 16
WORK_SIDE = 1600              # long side used for analysis/tracing
MAX_COLORS = 6
BG_DELTA_E = 12.0             # min Lab distance from background colour to count as foreground
AUTO_K_P95_DELTA_E = 10.0     # auto colour count: smallest k whose 95th-percentile ΔE is below this
                              # (a mean would let small details such as cheeks vanish)
DETAIL_MODES = {"preserve": 0.35, "balanced": 0.8, "clean": 1.2}
THIN_FEATURE_MM = 1.0

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"


@dataclass
class RasterOptions:
    colors: int | None = None          # None = auto (1..6)
    remove_background: bool = True
    background_hex: str | None = None  # None = auto-detect from the image border
    background_scope: str = "edge"     # edge-connected background, or all matching pixels
    detail_mode: str = "preserve"      # physical cleanup threshold, separate from stitch density


def sniff_format(data: bytes) -> str:
    if data.startswith(PNG_MAGIC):
        return "png"
    if data.startswith(JPEG_MAGIC):
        return "jpeg"
    raise ImportError_("unsupported_file_type", "file is not a PNG or JPEG image")


def load_image(data: bytes) -> np.ndarray:
    """Decode safely, honour EXIF orientation, drop all metadata. Returns RGBA uint8."""
    if len(data) > MAX_BYTES:
        raise ImportError_("file_too_large", "image exceeds 8 MB")
    fmt = sniff_format(data)
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS_SIDE * MAX_PIXELS_SIDE
    try:
        with Image.open(io.BytesIO(data)) as probe:
            if probe.format.lower() not in ("png", "jpeg") or probe.format.lower() != fmt:
                raise ImportError_("unsupported_file_type", "content does not match PNG/JPEG")
            w, h = probe.size
            if max(w, h) > MAX_PIXELS_SIDE:
                raise ImportError_("image_too_large", f"image exceeds {MAX_PIXELS_SIDE}x{MAX_PIXELS_SIDE} px")
            if min(w, h) < MIN_PIXELS_SIDE:
                raise ImportError_("image_too_small", "image is too small")
            probe.verify()
        with Image.open(io.BytesIO(data)) as img:
            img = ImageOps.exif_transpose(img)
            rgba = np.array(img.convert("RGBA"))
    except ImportError_:
        raise
    except (Image.DecompressionBombError, OSError, ValueError, SyntaxError) as exc:
        raise ImportError_("invalid_image", f"cannot decode image: {type(exc).__name__}") from exc
    return rgba


def _resize(rgba: np.ndarray) -> np.ndarray:
    h, w = rgba.shape[:2]
    scale = WORK_SIDE / max(h, w)
    if scale >= 1:
        return rgba
    # Premultiply before resampling: RGB hidden in transparent pixels must not bleed
    # into the artwork and become a new thread colour at its edge.
    premult = rgba.astype(np.float32)
    premult[..., :3] *= premult[..., 3:4] / 255
    small = cv2.resize(premult, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
    small[..., :3] *= 255 / np.maximum(small[..., 3:4], 1)
    return np.clip(np.round(small), 0, 255).astype(np.uint8)


def _to_lab(rgb: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(rgb.reshape(-1, 1, 3).astype(np.uint8), cv2.COLOR_RGB2LAB).reshape(-1, 3).astype(np.float32) \
        * np.array([100 / 255, 1, 1], np.float32) - np.array([0, 128, 128], np.float32)


def _lab_to_hex(lab: np.ndarray) -> str:
    raw = (lab + np.array([0, 128, 128])) / np.array([100 / 255, 1, 1])
    rgb = cv2.cvtColor(np.clip(raw, 0, 255).astype(np.uint8).reshape(1, 1, 3), cv2.COLOR_LAB2RGB)[0, 0]
    return "#%02x%02x%02x" % tuple(int(c) for c in rgb)


def _parse_hex(value: str) -> np.ndarray:
    v = value.strip().lstrip("#")
    if len(v) != 6 or any(c not in "0123456789abcdefABCDEF" for c in v):
        raise ImportError_("invalid_background_color", "background colour must be #rrggbb")
    return np.array([int(v[i:i + 2], 16) for i in (0, 2, 4)], np.uint8)


def foreground_mask(rgba: np.ndarray, opts: RasterOptions) -> tuple[np.ndarray, str | None]:
    alpha = rgba[..., 3]
    if (alpha < 128).any():  # even a narrow transparent border is intentional
        return alpha >= 128, None
    if not opts.remove_background:
        return np.ones(alpha.shape, bool), None
    rgb = rgba[..., :3]
    if opts.background_hex:
        bg = _parse_hex(opts.background_hex)
    else:
        border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
        bg = np.median(border, axis=0).astype(np.uint8)
    dist = np.linalg.norm(_to_lab(rgb) - _to_lab(bg.reshape(1, 3)), axis=1).reshape(alpha.shape)
    background = dist <= BG_DELTA_E
    if opts.background_scope == "edge":
        # Matching white inside a face or logo is artwork, unless the user explicitly
        # asks to remove all matching colours (e.g. enclosed letter counters).
        _, components = cv2.connectedComponents(background.astype(np.uint8), connectivity=4)
        border_ids = np.unique(np.concatenate([components[0], components[-1], components[:, 0], components[:, -1]]))
        background = np.isin(components, border_ids[border_ids != 0])
    return ~background, "#%02x%02x%02x" % tuple(int(c) for c in bg)


def _nearest_colors(pixels: np.ndarray, centers: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Linear memory instead of an image x palette x 3 temporary array."""
    labels = np.zeros(len(pixels), np.int16)
    error2 = np.full(len(pixels), np.inf, np.float32)
    for i, center in enumerate(centers):
        d2 = np.sum((pixels - center) ** 2, axis=1)
        better = d2 < error2
        labels[better], error2[better] = i, d2[better]
    return labels, np.sqrt(error2)


def _missing_detail(errors: np.ndarray, fg: np.ndarray, min_area: int) -> bool:
    residual = np.zeros(fg.shape, np.uint8)
    residual[fg] = (errors > 20).astype(np.uint8)
    # Ignore one-pixel JPEG/anti-alias fringes, but retain compact contrasting details.
    residual = cv2.morphologyEx(residual, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    _, _, stats, _ = cv2.connectedComponentsWithStats(residual, connectivity=8)
    return bool(np.any(stats[1:, cv2.CC_STAT_AREA] >= max(9, min_area)))


def quantize(lab_pixels: np.ndarray, k: int | None, fg: np.ndarray | None = None,
             min_area: int = 4) -> tuple[np.ndarray, np.ndarray]:
    """Auto colour count checks both global error and spatially coherent small details."""
    sample = lab_pixels
    if len(sample) > 60000:
        sample = sample[np.random.default_rng(0).choice(len(sample), 60000, replace=False)]
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 40, 0.2)
    candidates = [k] if k else range(1, MAX_COLORS + 1)
    best = None
    unique_count = len(np.unique(sample.round(0), axis=0))
    for kk in candidates:
        kk = min(kk, unique_count)
        cv2.setRNGSeed(1)
        _, _, centers = cv2.kmeans(sample, kk, None, criteria, 3, cv2.KMEANS_PP_CENTERS)
        _, sample_error = _nearest_colors(sample, centers)
        err = np.percentile(sample_error, 95)
        best = centers
        if not k and err < AUTO_K_P95_DELTA_E:
            _, errors = _nearest_colors(lab_pixels, centers)
            if fg is None or not _missing_detail(errors, fg, min_area):
                break
        if kk == unique_count:
            break
    labels, _ = _nearest_colors(lab_pixels, best)
    return labels, best


def _clean_labels(label_map: np.ndarray, fg: np.ndarray, n: int, min_area: int) -> tuple[np.ndarray, float]:
    """Remove only undersized components; never median-filter categorical colour IDs."""
    lm = np.where(fg, label_map, n).astype(np.uint8)  # background as its own label n
    removed = 0
    holes = np.zeros(fg.shape, bool)
    for i in range(n):
        mask = (lm == i).astype(np.uint8)
        count, comp, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        for c in range(1, count):
            if stats[c, cv2.CC_STAT_AREA] < min_area:
                holes[comp == c] = True
                removed += stats[c, cv2.CC_STAT_AREA]
    # Re-assign removed specks to the surrounding label (nearest non-removed neighbour).
    if holes.any():
        valid = (~holes).astype(np.uint8)
        if not valid.any():
            return np.full(fg.shape, -1, np.int16), 1.0
        _, idx = cv2.distanceTransformWithLabels(1 - valid, cv2.DIST_L2, 3, labelType=cv2.DIST_LABEL_PIXEL)
        ys, xs = np.nonzero(valid)
        lookup = lm[ys, xs]
        lm = np.where(holes, lookup[idx - 1], lm)
    out = lm.astype(np.int16)
    out[(out == n) | ~fg] = -1
    return out, removed / max(1, int(fg.sum()))


def _trace(mask: np.ndarray, min_area: int, detail_mode: str = "preserve") -> list[str]:
    img = np.where(mask, 0, 255).astype(np.uint8)
    img = np.pad(img, 2, constant_values=255)  # keep shapes touching the edge closed
    ok, png = cv2.imencode(".png", img)
    svg_text = vtracer.convert_raw_image_to_svg(
        png.tobytes(), img_format="png", colormode="binary", mode="spline",
        # Cleanup already applied the physical threshold. A second pixel filter here
        # used to silently delete accents and dots which had survived that cleanup.
        filter_speckle=0, corner_threshold=60,
        length_threshold=1.0 if detail_mode == "preserve" else 4.0,
        splice_threshold=45, path_precision=3)
    svg = SVG.parse(io.StringIO(svg_text), reify=True)
    paths = []
    for el in svg.elements():
        if isinstance(el, Shape):
            p = Path(el) * "translate(-2,-2)"
            p.reify()
            if len(p):
                paths.append(p.d())
    return paths


def _thickness_mm(mask: np.ndarray, px_per_mm: float) -> float:
    if not mask.any():
        return 0.0
    dist = cv2.distanceTransform(np.pad(mask.astype(np.uint8), 1), cv2.DIST_L2, 3)
    count, comp = cv2.connectedComponents(np.pad(mask.astype(np.uint8), 1))
    peak = np.zeros(count, np.float32)
    np.maximum.at(peak, comp.ravel(), dist.ravel())  # thickest point of each component
    return 2 * float(peak[1:].min()) / px_per_mm


def raster_to_svg(data: bytes, width_mm: float, opts: RasterOptions,
                  fit_height_mm: float | None = None) -> tuple[bytes, dict, np.ndarray, np.ndarray]:
    """Return (traced SVG, info, original RGBA thumbnail, quantised RGBA preview)."""
    rgba = _resize(load_image(data))
    h, w = rgba.shape[:2]
    if opts.detail_mode not in DETAIL_MODES:
        raise ImportError_("invalid_detail_mode", "unknown contour detail mode")
    if opts.background_scope not in ("edge", "all"):
        raise ImportError_("invalid_background_scope", "background scope must be edge or all")
    fg, bg_hex = foreground_mask(rgba, opts)
    if fg.mean() < 0.002:
        raise ImportError_("no_foreground", "no foreground found; check the background colour")
    if opts.colors is not None and not 1 <= opts.colors <= MAX_COLORS:
        raise ImportError_("invalid_color_count", f"colours must be 1-{MAX_COLORS}")

    lab = _to_lab(rgba[..., :3].reshape(-1, 3))
    fg_flat = fg.reshape(-1)
    cols = np.nonzero(fg.any(axis=0))[0]
    if fit_height_mm:
        rows = np.nonzero(fg.any(axis=1))[0]
        px_per_mm = (rows[-1] - rows[0] + 1) / max(fit_height_mm, 1)
    else:
        px_per_mm = (cols[-1] - cols[0] + 1) / max(width_mm, 1)
    min_feature = DETAIL_MODES[opts.detail_mode]
    min_area = max(2, int(np.ceil((min_feature * px_per_mm) ** 2)))
    labels_fg, centers = quantize(lab[fg_flat], opts.colors, fg, min_area)
    label_map = np.full(fg_flat.shape, 0, np.int16)
    label_map[fg_flat] = labels_fg
    label_map = label_map.reshape(h, w)

    clean, removed_frac = _clean_labels(label_map, fg, len(centers), min_area)

    order = sorted(range(len(centers)), key=lambda i: -(clean == i).sum())  # large areas first, details last
    parts, colors, thin = [], [], False
    for i in order:
        mask = clean == i
        if mask.sum() < min_area:
            continue
        hex_color = _lab_to_hex(centers[i])
        for d in _trace(mask, min_area=min_area, detail_mode=opts.detail_mode):
            parts.append(f'<path d="{d}" fill="{hex_color}" fill-rule="evenodd"/>')
        colors.append(hex_color)
        thin = thin or _thickness_mm(mask, px_per_mm) < THIN_FEATURE_MM
    if not parts:
        raise ImportError_("no_embroiderable_shapes", "nothing left after cleanup")

    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">'
           + "".join(parts) + "</svg>").encode()

    preview = np.zeros((h, w, 4), np.uint8)
    for i, c in enumerate(centers):
        rgb = _parse_hex(_lab_to_hex(c))
        preview[clean == i] = (*rgb, 255)
    warnings = []
    if removed_frac > 0:
        warnings.append("small_details_removed")
    if thin:
        warnings.append("thin_features_under_1mm")
    _, errors = _nearest_colors(lab[fg_flat], centers)
    if _missing_detail(errors, fg, min_area):
        warnings.append("color_detail_limited")
    info = {"kind": "raster", "pixels": [w, h], "colors": colors, "backgroundHex": bg_hex,
            "autoColors": opts.colors is None, "removedFraction": round(removed_frac, 4),
            "analysisVersion": 2, "detailMode": opts.detail_mode, "minFeatureMm": min_feature,
            "options": {"colors": opts.colors, "removeBackground": opts.remove_background,
                        "backgroundHex": opts.background_hex, "backgroundScope": opts.background_scope,
                        "detailMode": opts.detail_mode}}
    return svg, {**info, "warnings": warnings}, rgba, preview


def import_raster(data: bytes, width_mm: float, fabric: str, opts: RasterOptions,
                  height_mm: float | None = None, fit_height_mm: float | None = None) -> tuple[dict, bytes, bytes]:
    """Return (Design JSON, original thumbnail PNG, quantised preview PNG)."""
    svg, info, rgba, preview = raster_to_svg(data, width_mm, opts, fit_height_mm)
    design = import_svg(svg, width_mm, fabric, height_mm, fit_height_mm)
    design["warnings"] = sorted(set(design["warnings"]) | set(info.pop("warnings")))
    design["raster"] = info
    return design, _png(rgba, 800), _png(preview, 800)


def _png(rgba: np.ndarray, max_side: int) -> bytes:
    img = Image.fromarray(rgba, "RGBA")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)  # re-encoded: no EXIF or other metadata survives
    return buf.getvalue()
