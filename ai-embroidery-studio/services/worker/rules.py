"""Rule engine (spec §6 stage 4): decides each region's stitch type from geometry, and
reviews AI suggestions against hard limits. AI may only suggest; rules decide.
"""
from __future__ import annotations

import copy

import numpy as np

from .fabrics import SATIN_WIDTH_MM, THIN_RUNNING_MM, default_params
from .geometry import METRICS_VERSION, analyze_design, masks_for

SATIN_MAX_WIDTH_CV = 0.25      # width variation along the stroke
SATIN_MIN_COVERAGE = 0.75      # centreline x width must explain most of the area
MIN_SHAPE_FIDELITY = 0.90     # measured overlap of reconstructed stroke and original silhouette
AUTO_SATIN_MM = (1.5, 6.0)     # rules-only satin is more conservative than the hard limits
OVERLAP_MM2 = 0.05


def unit_to_mm(design: dict) -> float:
    _, _, vw, vh = design["geometry"]["viewBox"]
    return (design["sizeMm"]["width"] / vw + design["sizeMm"]["height"] / vh) / 2


def stroke_width_mm(region: dict, design: dict) -> float | None:
    c = (region.get("metrics") or {}).get("centerline")
    return c["widthUnits"] * unit_to_mm(design) if c else None


def satin_blocker(region: dict, design: dict) -> str | None:
    """None if a satin column is allowed for this region at the design's current size."""
    c = (region.get("metrics") or {}).get("centerline")
    if not c:
        return "satin_needs_uniform_stroke"
    if c.get("fidelity", 1.0) < MIN_SHAPE_FIDELITY:
        return "satin_shape_mismatch"
    if c["widthCv"] > SATIN_MAX_WIDTH_CV or c["coverage"] < SATIN_MIN_COVERAGE or c["lengthUnits"] < 2 * c["widthUnits"]:
        return "satin_needs_uniform_stroke"
    w = c["widthUnits"] * unit_to_mm(design)
    if w < SATIN_WIDTH_MM[0]:
        return "satin_too_narrow"
    if w > SATIN_WIDTH_MM[1]:
        return "satin_too_wide"
    return None


def is_line(region: dict) -> bool:
    return region.get("shape") == "line"


def allowed(region: dict, design: dict, stitch: str) -> str | None:
    """None if `stitch` may be used for the region, else a reason code."""
    if stitch == "fill":
        return "fill_needs_area" if is_line(region) else None
    if stitch == "satin":
        return satin_blocker(region, design)
    return None


def rule_choice(region: dict, design: dict) -> tuple[str, str]:
    """Deterministic default: (stitchType, reason code)."""
    w = stroke_width_mm(region, design)
    if is_line(region):
        if w is not None and satin_blocker(region, design) is None and AUTO_SATIN_MM[0] <= w <= AUTO_SATIN_MM[1]:
            return "satin", "wide_stroke"
        return "running", "stroke_line"
    fidelity = ((region.get("metrics") or {}).get("centerline") or {}).get("fidelity", 1.0)
    # At sub-millimetre widths, a single raster pixel is a large area fraction.
    if w is not None and w < THIN_RUNNING_MM and fidelity >= 0.75:
        return "running", "thin_line_centerline"
    if w is not None and satin_blocker(region, design) is None and AUTO_SATIN_MM[0] <= w <= AUTO_SATIN_MM[1]:
        return "satin", "uniform_stroke"
    return "fill", "preserve_shape" if fidelity < MIN_SHAPE_FIDELITY else "area_fill"


def set_stitch(region: dict, design: dict, stitch: str) -> None:
    if region["stitchType"] != stitch or not region.get("params"):
        region["params"] = default_params(design["fabricPreset"], stitch)
    region["stitchType"] = stitch
    has_centerline = bool((region.get("metrics") or {}).get("centerline"))
    region["runningPath"] = "centerline" if stitch == "running" and has_centerline and (
        is_line(region) or (stroke_width_mm(region, design) or 99) < THIN_RUNNING_MM) else "outline"


def ensure_metrics(design: dict) -> dict:
    missing = [r for r in design["regions"] if (r.get("metrics") or {}).get("version") != METRICS_VERSION]
    if missing:
        metrics = analyze_design(design)
        for r in design["regions"]:
            r["metrics"] = metrics[r["id"]]
    return design


def plan_design(design: dict, ai: dict | None = None, reorder: bool = True) -> dict:
    """Return a copy with stitch types decided, AI suggestions reviewed, and colours reordered.

    `ai` maps region id -> {"stitch", "needsReview", "reason", "confidence"} (already
    validated to reference existing ids only).
    """
    design = ensure_metrics(copy.deepcopy(design))
    ai = ai or {}
    for region in design["regions"]:
        rule_stitch, rule_reason = rule_choice(region, design)
        suggestion = ai.get(region["id"])
        plan = {"source": "rules", "suggested": rule_stitch, "reason": rule_reason, "needsReview": False,
                "confidence": None, "aiReason": None, "override": None}
        chosen = rule_stitch
        if suggestion:
            plan.update(source="ai", suggested=suggestion["stitch"], confidence=suggestion.get("confidence"),
                        aiReason=suggestion.get("reason"), needsReview=bool(suggestion.get("needsReview")))
            blocker = allowed(region, design, suggestion["stitch"])
            if blocker:
                plan.update(override=blocker, needsReview=True)
                chosen = rule_stitch if rule_stitch != suggestion["stitch"] else ("running" if is_line(region) else "fill")
            else:
                chosen = suggestion["stitch"]
            if (plan["confidence"] or 1) < 0.6:
                plan["needsReview"] = True
        plan["applied"] = chosen
        set_stitch(region, design, chosen)
        region["plan"] = plan
    if reorder:
        reorder_for_colors(design)
    return design


def reorder_for_colors(design: dict) -> None:
    """Group same-colour regions to cut colour changes, never moving a region past one it overlaps.

    Moving region r earlier is safe only if r does not overlap anything it jumps over:
    stacking order between overlapping shapes is what the artwork depends on.
    """
    regions = sorted(design["regions"], key=lambda r: r["order"])
    masks, ppu = masks_for(design)
    min_px = OVERLAP_MM2 * (ppu / unit_to_mm(design)) ** 2

    def overlaps(a: str, b: str) -> bool:
        return int(np.logical_and(masks[a], masks[b]).sum()) > min_px

    result: list[dict] = []
    for region in regions:
        insert_at = len(result)
        for j in range(len(result) - 1, -1, -1):
            if result[j]["colorId"] == region["colorId"]:
                insert_at = j + 1
                break
            if overlaps(region["id"], result[j]["id"]):
                break
        result.insert(insert_at, region)
    for i, region in enumerate(result, start=1):
        region["order"] = i
    design["regions"] = result


def color_changes(design: dict) -> int:
    seq = [r["colorId"] for r in sorted(design["regions"], key=lambda r: r["order"]) if not r.get("hidden")]
    return sum(1 for a, b in zip(seq, seq[1:]) if a != b)


def region_warnings(region: dict, design: dict) -> list[str]:
    """Size-dependent warnings for the region's current stitch type."""
    warns = []
    if region["stitchType"] == "satin":
        blocker = satin_blocker(region, design)
        if blocker:
            warns.append(blocker)
    w = stroke_width_mm(region, design)
    if region["stitchType"] == "fill" and w is not None and w < THIN_RUNNING_MM:
        warns.append("thin_fill_use_running")
    return warns
