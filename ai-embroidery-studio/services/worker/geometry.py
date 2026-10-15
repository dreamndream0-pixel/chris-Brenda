"""Deterministic region geometry (spec §6 stage 2): size, thickness, holes and centrelines.

Regions are rasterised at a fixed resolution in millimetres. Thin, single-path
shapes get a centreline (Zhang-Suen thinning + spur pruning) that the planner
can sew as a running stitch or a satin column. Everything is stored in viewBox
units so it stays valid when the design is resized.
"""
from __future__ import annotations

import cv2
import numpy as np
from svgelements import Path

PX_PER_MM = 10.0          # 0.1 mm raster
MAX_RASTER_SIDE = 3000
MIN_CENTERLINE_PX = 6
MAX_CENTERLINE_WIDTH_MM = 8.0  # wider shapes are never sewn as satin/running, so skip thinning
METRICS_VERSION = 2


def _scale(design: dict) -> tuple[float, float]:
    _, _, vw, vh = design["geometry"]["viewBox"]
    return design["sizeMm"]["width"] / vw, design["sizeMm"]["height"] / vh


def raster_params(design: dict) -> tuple[float, int, int]:
    """Pixels per viewBox unit and canvas size for the design at its current mm size."""
    sx, sy = _scale(design)
    w_mm, h_mm = design["sizeMm"]["width"], design["sizeMm"]["height"]
    ppm = min(PX_PER_MM, MAX_RASTER_SIDE / max(w_mm, h_mm))
    _, _, vw, vh = design["geometry"]["viewBox"]
    ppu = ppm * (sx + sy) / 2
    return ppu, int(np.ceil(vw * ppu)) + 4, int(np.ceil(vh * ppu)) + 4


def region_mask(svg_path: str, ppu: float, width: int, height: int) -> np.ndarray:
    """Rasterise a path (all subpaths, even-odd) into a boolean mask."""
    path = Path(svg_path)
    polys = []
    for sub in path.as_subpaths():
        sub = Path(sub)
        length = max(sub.length(error=1e-2), 1e-6)
        n = int(min(4000, max(16, length * ppu / 1.5)))
        pts = np.asarray(sub.npoint(np.linspace(0, 1, n)), np.float64).reshape(-1, 2)
        pts = pts[np.isfinite(pts).all(axis=1)]
        if len(pts) >= 3:
            polys.append(np.round((pts * ppu + 2) * 16).astype(np.int32))
    mask = np.zeros((height, width), np.uint8)
    if polys:
        cv2.fillPoly(mask, polys, 1, lineType=cv2.LINE_8, shift=4)  # even-odd between contours
    return mask.astype(bool)


def zhang_suen(mask: np.ndarray) -> np.ndarray:
    """Vectorised Zhang-Suen thinning; returns a 1-px skeleton."""
    img = np.pad(mask.astype(np.uint8), 1)
    changed = True
    while changed:
        changed = False
        for step in (0, 1):
            p = img
            p2, p3, p4 = np.roll(p, 1, 0), np.roll(np.roll(p, 1, 0), -1, 1), np.roll(p, -1, 1)
            p5, p6 = np.roll(np.roll(p, -1, 0), -1, 1), np.roll(p, -1, 0)
            p7, p8, p9 = np.roll(np.roll(p, -1, 0), 1, 1), np.roll(p, 1, 1), np.roll(np.roll(p, 1, 0), 1, 1)
            neighbours = [p2, p3, p4, p5, p6, p7, p8, p9]
            b = sum(n.astype(np.int16) for n in neighbours)
            seq = neighbours + [p2]
            a = sum(((seq[i] == 0) & (seq[i + 1] == 1)).astype(np.int16) for i in range(8))
            if step == 0:
                c = (p2 * p4 * p6) == 0
                d = (p4 * p6 * p8) == 0
            else:
                c = (p2 * p4 * p8) == 0
                d = (p2 * p6 * p8) == 0
            remove = (p == 1) & (b >= 2) & (b <= 6) & (a == 1) & c & d
            if remove.any():
                img = img & ~remove.astype(np.uint8)
                changed = True
    return img[1:-1, 1:-1].astype(bool)


_K = np.array([[1, 1, 1], [1, 0, 1], [1, 1, 1]], np.float32)


def _neighbour_count(skel: np.ndarray) -> np.ndarray:
    return cv2.filter2D(skel.astype(np.float32), -1, _K, borderType=cv2.BORDER_CONSTANT).astype(np.int16) * skel


def prune(skel: np.ndarray, iterations: int) -> np.ndarray:
    """Remove spurs: peel endpoints `iterations` times (loops are unaffected)."""
    skel = skel.copy()
    for _ in range(max(0, iterations)):
        ends = (_neighbour_count(skel) == 1)
        if not ends.any():
            break
        skel &= ~ends
    return skel


def _bfs(pts: set, start: tuple[int, int]) -> tuple[dict, tuple[int, int]]:
    parent = {start: None}
    queue, far = [start], start
    for cur in queue:  # list grows while iterating = BFS
        far = cur
        y, x = cur
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                nxt = (y + dy, x + dx)
                if (dy or dx) and nxt in pts and nxt not in parent:
                    parent[nxt] = cur
                    queue.append(nxt)
    return parent, far


def _walk(skel: np.ndarray, closed: bool, tolerance_px: float) -> list[tuple[int, int]] | None:
    """Order a skeleton into a polyline, or None if it branches.

    Open strokes: the geodesic diameter (BFS twice) - spurs and the 2-px "staircases" that
    thinning leaves on diagonals drop out on their own. Rings: trace the loop as a contour.
    Either way, nearly every skeleton pixel must lie on the result, otherwise it branches.
    """
    ys, xs = np.nonzero(skel)
    if len(ys) < MIN_CENTERLINE_PX:
        return None
    if closed:
        contours, _ = cv2.findContours(skel.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        if len(contours) != 1:
            return None
        order = [(int(p[0][1]), int(p[0][0])) for p in contours[0]]
        order = order[: max(2, len(order) // 2 + 1)] if len(order) > 2 * len(ys) * 0.9 else order
    else:
        pts = set(zip(ys.tolist(), xs.tolist()))
        _, a = _bfs(pts, next(iter(pts)))
        parent, b = _bfs(pts, a)
        if len(parent) < 0.98 * len(pts):
            return None  # disconnected skeleton
        order, cur = [], b
        while cur is not None:
            order.append(cur)
            cur = parent[cur]
    line = np.zeros(skel.shape, np.uint8)
    cv2.polylines(line, [np.array([(x, y) for y, x in order], np.int32)], closed, 1, 1)
    near = cv2.dilate(line, np.ones((3, 3), np.uint8), iterations=max(1, int(tolerance_px)))
    if near[skel].mean() < 0.95:
        return None  # side branches (H, E, ...) are far from the main path
    return order


def analyze_region(mask: np.ndarray, ppu: float, ppm: float = PX_PER_MM) -> dict:
    """Metrics in viewBox units: area, max thickness, holes, and centreline if the shape is a simple stroke."""
    area_px = int(mask.sum())
    if area_px == 0:
        return {"version": METRICS_VERSION, "areaUnits2": 0.0, "thicknessUnits": 0.0,
                "holes": 0, "components": 0, "centerline": None}
    ys, xs = np.nonzero(mask)
    y0, x0 = max(0, ys.min() - 2), max(0, xs.min() - 2)
    mask = mask[y0:ys.max() + 3, x0:xs.max() + 3]  # thinning cost scales with the canvas, so crop
    m8 = mask.astype(np.uint8)
    dist = cv2.distanceTransform(np.pad(m8, 1), cv2.DIST_L2, 5)[1:-1, 1:-1]
    contours, hierarchy = cv2.findContours(m8, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    outer = sum(1 for h in hierarchy[0] if h[3] < 0) if hierarchy is not None else 0
    holes = sum(1 for h in hierarchy[0] if h[3] >= 0) if hierarchy is not None else 0
    result = {
        "version": METRICS_VERSION,
        "areaUnits2": round(area_px / ppu ** 2, 4),
        "thicknessUnits": round(2 * float(dist.max()) / ppu, 4),
        "holes": holes,
        "components": outer,
        "centerline": None,
    }
    if outer != 1 or holes > 1 or result["thicknessUnits"] * ppu / ppm > MAX_CENTERLINE_WIDTH_MM:
        return result
    closed = holes == 1

    skel = zhang_suen(mask)
    widths = 2 * dist[skel]
    if len(widths) == 0:
        return result
    median_w = float(np.median(widths))
    order = _walk(skel, closed, tolerance_px=median_w * 0.75)
    if order is None:
        return result
    w_along = 2 * dist[tuple(np.array(order).T)]
    mean_w, std_w = float(w_along.mean()), float(w_along.std())
    pts = np.array([(x, y) for y, x in order], np.float32).reshape(-1, 1, 2)
    # A physical tolerance removes raster stair-steps without changing with SVG units.
    approx = cv2.approxPolyDP(pts, max(0.75, 0.12 * ppm), closed).reshape(-1, 2)
    if len(approx) < 2:
        return result
    if not closed:
        # A skeleton already stops inside a flat end. Trimming it by half a width
        # shortened it a second time. Extend its tangent to the actual boundary instead.
        for end, neighbour in ((0, 1), (-1, -2)):
            start = approx[end].copy()
            direction = start - approx[neighbour]
            norm = np.linalg.norm(direction)
            if norm == 0:
                continue
            direction /= norm
            for distance in np.arange(0.25, median_w + 0.25, 0.25):
                candidate = start + distance * direction
                x, y = np.round(candidate).astype(int)
                if not (0 <= y < mask.shape[0] and 0 <= x < mask.shape[1] and mask[y, x]):
                    break
                approx[end] = candidate
    reconstructed = np.zeros(mask.shape, np.uint8)
    cv2.polylines(reconstructed, [np.round(approx).astype(np.int32)], closed, 1, max(1, round(mean_w)))
    # Match the butt caps emitted by svg_compile, not OpenCV's round end caps.
    if not closed:
        yy, xx = np.indices(mask.shape)
        for end, neighbour in ((0, 1), (-1, -2)):
            outward = approx[end] - approx[neighbour]
            beyond = (xx - approx[end, 0]) * outward[0] + (yy - approx[end, 1]) * outward[1] > 0
            reconstructed[beyond] = 0
    fidelity = np.logical_and(mask, reconstructed).sum() / max(1, np.logical_or(mask, reconstructed).sum())
    coords = [((float(x) + x0 - 2) / ppu, (float(y) + y0 - 2) / ppu) for x, y in approx]
    d = "M " + " L ".join(f"{x:.3f},{y:.3f}" for x, y in coords) + (" Z" if closed else "")
    length_px = float(np.sum(np.linalg.norm(np.diff(approx, axis=0), axis=1)))
    if closed:
        length_px += float(np.linalg.norm(approx[0] - approx[-1]))
    # A stroke is "uniform" when its width varies little and it is clearly longer than wide.
    result["centerline"] = {
        "d": d,
        "closed": closed,
        "widthUnits": round(mean_w / ppu, 4),
        "widthCv": round(std_w / mean_w, 3) if mean_w else 1.0,
        "lengthUnits": round(length_px / ppu, 4),
        "coverage": round(min(1.0, (length_px * mean_w) / area_px), 3),
        "fidelity": round(float(fidelity), 3),
    }
    return result


def line_mask(svg_path: str, width_units: float, ppu: float, width: int, height: int) -> np.ndarray:
    """Rasterise a stroked line (an SVG stroke region) at its stroke width."""
    mask = np.zeros((height, width), np.uint8)
    thickness = max(1, int(round(width_units * ppu)))
    for sub in Path(svg_path).as_subpaths():
        sub = Path(sub)
        n = int(min(4000, max(8, sub.length(error=1e-2) * ppu / 1.5)))
        pts = np.asarray(sub.npoint(np.linspace(0, 1, n)), np.float64).reshape(-1, 2)
        pts = pts[np.isfinite(pts).all(axis=1)]
        if len(pts) >= 2:
            cv2.polylines(mask, [np.round(pts * ppu + 2).astype(np.int32)], False, 1, thickness)
    return mask.astype(bool)


def line_metrics(region: dict) -> dict:
    """A stroke region is its own centreline; the stroke width is exact (no raster estimate)."""
    path = Path(region["svgPath"])
    w = float(region.get("strokeWidthUnits") or 0.0)
    length = float(path.length(error=1e-2))
    return {"version": METRICS_VERSION, "areaUnits2": round(length * w, 4), "thicknessUnits": round(w, 4), "holes": 0, "components": 1,
            "centerline": {"d": region["svgPath"], "closed": region["svgPath"].rstrip().upper().endswith("Z"),
                           "widthUnits": round(w, 4), "widthCv": 0.0, "lengthUnits": round(length, 4),
                           "coverage": 1.0, "fidelity": 1.0}}


def _mask(region: dict, ppu: float, w: int, h: int) -> np.ndarray:
    if region.get("shape") == "line":
        return line_mask(region["svgPath"], float(region.get("strokeWidthUnits") or 0.0), ppu, w, h)
    return region_mask(region["svgPath"], ppu, w, h)


def analyze_design(design: dict) -> dict[str, dict]:
    ppu, w, h = raster_params(design)
    ppm = ppu / sum(_scale(design)) * 2
    return {r["id"]: line_metrics(r) if r.get("shape") == "line"
            else analyze_region(region_mask(r["svgPath"], ppu, w, h), ppu, ppm) for r in design["regions"]}


def masks_for(design: dict) -> tuple[dict[str, np.ndarray], float]:
    ppu, w, h = raster_params(design)
    return {r["id"]: _mask(r, ppu, w, h) for r in design["regions"]}, ppu
