"""Auto-digitising narrow areas into satin columns.

Commercial digitising software sews letters, rings and other stroke-like shapes
as satin: the thread runs across the stroke, back and forth, following its
direction. A 45-degree tatami fill over the same shape looks flat and coarse.

Here a shape's skeleton is split into branches at its junctions, and every
branch becomes one satin column whose two rails follow the shape's local
half-width on either side (variable width). Branch ends are extended to the
outline at free ends and into the junction at joins, so neighbouring columns
overlap instead of leaving gaps. The result is only used when the columns
reproduce the silhouette closely (coverage and spill are measured).
"""
from __future__ import annotations

import cv2
import numpy as np

SAMPLE_MM = 0.5            # rung spacing along a column
MIN_BRANCH_MM = 0.8        # shorter skeleton pieces are spurs or junction noise
MAX_COLUMNS = 80
MIN_COVERAGE = 0.88        # columns must cover this much of the shape
MAX_SPILL = 0.12           # and add at most this much outside it


def _transitions(img: np.ndarray) -> np.ndarray:
    """0->1 transitions around each pixel's 8-neighbourhood (the crossing number)."""
    p = np.pad(img.astype(np.uint8), 1)
    ring = [p[:-2, 1:-1], p[:-2, 2:], p[1:-1, 2:], p[2:, 2:], p[2:, 1:-1], p[2:, :-2], p[1:-1, :-2], p[:-2, :-2]]
    seq = ring + [ring[0]]
    return sum(((seq[i] == 0) & (seq[i + 1] == 1)).astype(np.int16) for i in range(8))


def _junctions(skel: np.ndarray, r_in: float = 2.5, r_out: float = 4.5) -> np.ndarray:
    """True branch points: at least three separate skeleton pieces leave a small ring around the pixel.

    Thinning leaves 2-px clumps and staircases on curves whose crossing number looks like a
    junction; checking the ring around a candidate filters those out.
    """
    cand = skel & ((_transitions(skel) >= 3) |
                   (cv2.filter2D(skel.astype(np.uint8), -1, np.ones((3, 3), np.float32), borderType=cv2.BORDER_CONSTANT) >= 5))
    out = np.zeros(skel.shape, bool)
    R = int(np.ceil(r_out))
    yy, xx = np.mgrid[-R:R + 1, -R:R + 1]
    rr = np.hypot(yy, xx)
    ring = ((rr >= r_in) & (rr <= r_out)).astype(np.uint8)
    padded = np.pad(skel, R)
    for y, x in zip(*np.nonzero(cand)):
        window = padded[y:y + 2 * R + 1, x:x + 2 * R + 1].astype(np.uint8) & ring
        if window.sum() < 3:
            continue
        n, _ = cv2.connectedComponents(window, connectivity=8)
        if n - 1 >= 3:
            out[y, x] = True
    # one representative pixel per junction cluster
    n, labels, stats, cents = cv2.connectedComponentsWithStats(
        cv2.dilate(out.astype(np.uint8), np.ones((3, 3), np.uint8)), connectivity=8)
    rep = np.zeros(skel.shape, bool)
    for i in range(1, n):
        ys, xs = np.nonzero((labels == i) & skel)
        if len(ys):
            k = np.argmin((ys - cents[i][1]) ** 2 + (xs - cents[i][0]) ** 2)
            rep[ys[k], xs[k]] = True
    return rep


def _order(component: np.ndarray) -> tuple[list[tuple[int, int]], bool]:
    """Order a branch's pixels into a path; (points as (y, x), closed)."""
    ys, xs = np.nonzero(component)
    pts = set(zip(ys.tolist(), xs.tolist()))

    def bfs(start):
        parent = {start: None}
        queue, far = [start], start
        for cur in queue:
            far = cur
            y, x = cur
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    nxt = (y + dy, x + dx)
                    if (dy or dx) and nxt in pts and nxt not in parent:
                        parent[nxt] = cur
                        queue.append(nxt)
        return parent, far

    counts = cv2.filter2D(component.astype(np.uint8), -1, np.ones((3, 3), np.float32), borderType=cv2.BORDER_CONSTANT)
    ends = [(int(y), int(x)) for y, x in zip(*np.nonzero(component & (counts == 2)))]
    if not ends:  # a loop (ring)
        contours, _ = cv2.findContours(component.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        if not contours:
            return [], False
        c = max(contours, key=len)
        order = [(int(p[0][1]), int(p[0][0])) for p in c]
        # a 1-px loop is traced on both sides; keep one pass
        return order[: max(2, len(order) // 2 + 1)] if len(order) > 1.6 * len(pts) else order, True
    _, a = bfs(ends[0])
    parent, b = bfs(a)
    order, cur = [], b
    while cur is not None:
        order.append(cur)
        cur = parent[cur]
    return order, False


def _resample(pts: np.ndarray, step: float, closed: bool) -> np.ndarray:
    if closed:
        pts = np.vstack([pts, pts[:1]])
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    s = np.concatenate([[0], np.cumsum(seg)])
    total = s[-1]
    if total < 1e-6:
        return pts[:1]
    n = max(2, int(round(total / step)) + 1)
    t = np.linspace(0, total, n, endpoint=not closed) if not closed else np.linspace(0, total, n)[:-1]
    return np.stack([np.interp(t, s, pts[:, 0]), np.interp(t, s, pts[:, 1])], axis=1)


def _smooth(a: np.ndarray, window: int, closed: bool) -> np.ndarray:
    if window <= 1 or len(a) < 3:
        return a
    k = np.ones(window) / window
    pad = window // 2
    if closed:
        ext = np.concatenate([a[-pad:], a, a[:pad]])
    else:
        ext = np.concatenate([np.repeat(a[:1], pad, 0), a, np.repeat(a[-1:], pad, 0)])
    if a.ndim == 1:
        return np.convolve(ext, k, mode="valid")[: len(a)]
    return np.stack([np.convolve(ext[:, i], k, mode="valid")[: len(a)] for i in range(a.shape[1])], axis=1)


def _extend(pts: np.ndarray, at_start: bool, mask: np.ndarray, limit: float) -> np.ndarray:
    """Push a free end along its tangent until it reaches the outline (at most `limit` px)."""
    end, prev = (pts[0], pts[min(2, len(pts) - 1)]) if at_start else (pts[-1], pts[max(-3, -len(pts))])
    d = end - prev
    n = np.linalg.norm(d)
    if n == 0:
        return pts
    d = d / n
    best = end
    for dist in np.arange(0.5, limit + 0.5, 0.5):
        c = end + d * dist
        x, y = int(round(c[0])), int(round(c[1]))
        if not (0 <= y < mask.shape[0] and 0 <= x < mask.shape[1] and mask[y, x]):
            break
        best = c
    if best is end:
        return pts
    return np.vstack([best, pts]) if at_start else np.vstack([pts, best])


def satin_columns(mask: np.ndarray, dist: np.ndarray, ppm: float) -> dict | None:
    """Columns in mask pixel coordinates: {"columns": [{"left", "right", "widths"}], coverage, spill}.

    `dist` is the distance transform of `mask`; `ppm` pixels per millimetre.
    """
    from .geometry import zhang_suen  # local import: geometry imports this module
    if mask.sum() < 4:
        return None
    skel = zhang_suen(mask)
    if not skel.any():
        return None
    junction = _junctions(skel)
    # Cut the skeleton around each junction so the branches separate cleanly.
    junction_zone = cv2.dilate(junction.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))).astype(bool) & skel
    branches = skel & ~junction_zone
    n, labels = cv2.connectedComponents(branches.astype(np.uint8), connectivity=8)
    jy, jx = np.nonzero(junction)
    jpts = np.stack([jx, jy], axis=1).astype(np.float64) if len(jy) else np.zeros((0, 2))

    min_len = MIN_BRANCH_MM * ppm
    columns = []
    for label in range(1, n):
        comp = labels == label
        if comp.sum() < 2:
            continue
        order, closed = _order(comp)
        if len(order) < 2:
            continue
        pts = np.array([(x, y) for y, x in order], np.float64)
        length = float(np.sum(np.linalg.norm(np.diff(pts, axis=0), axis=1)))
        widths_px = 2 * dist[tuple(np.array(order).T)]
        local_w = float(np.median(widths_px))
        if not closed:
            # Ends touching a junction reach into it (columns overlap there); free ends reach the outline.
            for at_start in (True, False):
                end = pts[0] if at_start else pts[-1]
                jd = float(np.min(np.linalg.norm(jpts - end, axis=1))) if len(jpts) else 1e9
                if jd <= 6:
                    # Into the junction along the stroke's own direction, a little past its centre.
                    pts = _extend(pts, at_start, mask, limit=jd + 0.3 * local_w)
                else:
                    pts = _extend(pts, at_start, mask, limit=local_w * 0.6 + 2)
            length = float(np.sum(np.linalg.norm(np.diff(pts, axis=0), axis=1)))
        if (not closed and length < max(min_len, 0.5 * local_w)) or (closed and length < 4 * local_w):
            continue  # spurs, and the tiny loops thinning leaves inside junction blobs
        step = SAMPLE_MM * ppm
        smoothed = _smooth(pts, max(1, int(round(0.6 * ppm))) | 1, closed) if len(pts) > 5 else pts
        if not closed:
            smoothed[0], smoothed[-1] = pts[0], pts[-1]
        res = _resample(smoothed, step, closed)
        if len(res) < 2:
            continue
        xi = np.clip(np.round(res[:, 0]).astype(int), 0, mask.shape[1] - 1)
        yi = np.clip(np.round(res[:, 1]).astype(int), 0, mask.shape[0] - 1)
        # Width from the distance transform; at the very ends it falls off, keep the neighbours' width.
        w = 2 * cv2.dilate(dist, np.ones((3, 3), np.uint8))[yi, xi]
        w = np.maximum(w, 1.0)
        w = _smooth(w, 3, closed)
        if closed:
            tang = np.roll(res, -1, 0) - np.roll(res, 1, 0)
        else:
            tang = np.gradient(res, axis=0)
        tang /= np.maximum(np.linalg.norm(tang, axis=1, keepdims=True), 1e-9)
        normal = np.stack([-tang[:, 1], tang[:, 0]], axis=1)
        # Average the stitch direction over about one stroke width so rails do not fold on bends.
        win = max(3, int(round(np.median(w) / step)) | 1)
        normal = _smooth(normal, win, closed)
        normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-9)
        left = res + normal * (w[:, None] / 2)
        right = res - normal * (w[:, None] / 2)
        if closed:  # close the ring
            left, right, w = np.vstack([left, left[:1]]), np.vstack([right, right[:1]]), np.append(w, w[0])
        columns.append({"left": left, "right": right, "widths": w, "closed": closed})
        if len(columns) > MAX_COLUMNS:
            return None
    if not columns:
        return None

    cover = np.zeros(mask.shape, np.uint8)
    for c in columns:
        for i in range(len(c["left"]) - 1):
            quad = np.array([c["left"][i], c["left"][i + 1], c["right"][i + 1], c["right"][i]])
            cv2.fillPoly(cover, [np.round(quad * 4).astype(np.int32)], 1, shift=2)
    cover = cover.astype(bool)
    area = mask.sum()
    coverage = float((cover & mask).sum() / area)
    spill = float((cover & ~cv2.dilate(mask.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)).sum() / area)
    # What the columns miss (round blob ends, wide joins) is filled underneath; the satin covers the seams.
    rest = mask & ~cv2.erode(cover.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    rest = cv2.morphologyEx(rest.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    contours, hierarchy = cv2.findContours(rest, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    patches = []
    min_patch = (0.8 * ppm) ** 2
    if hierarchy is not None:
        for i, c in enumerate(contours):
            if hierarchy[0][i][3] < 0 and cv2.contourArea(c) >= min_patch:
                patches.append(c.reshape(-1, 2).astype(np.float64))
    return {"columns": columns, "coverage": round(coverage, 3), "spill": round(spill, 3), "patches": patches}
