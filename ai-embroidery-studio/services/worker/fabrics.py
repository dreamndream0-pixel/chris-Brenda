"""Fabric presets and parameter limits.

Values are starting points, not tuned production settings: every preset
must be calibrated with factory test-sews on the real fabric + stabiliser.
"""
from __future__ import annotations

FABRIC_PRESETS: dict[str, dict] = {
    "woven_cotton": {
        "label": "平織棉",
        "fill": {"fillAngleDeg": 45, "rowSpacingMm": 0.40, "maxStitchLengthMm": 3.0,
                 "underlay": True, "pullCompensationMm": 0.10},
        "running": {"runningStitchLengthMm": 2.0, "repeats": 1},
        "satin": {"zigzagSpacingMm": 0.40, "pullCompensationMm": 0.20, "underlay": True},
    },
    "knit_cotton": {
        "label": "針織棉",
        "fill": {"fillAngleDeg": 45, "rowSpacingMm": 0.40, "maxStitchLengthMm": 3.0,
                 "underlay": True, "pullCompensationMm": 0.25},
        "running": {"runningStitchLengthMm": 2.2, "repeats": 1},
        "satin": {"zigzagSpacingMm": 0.40, "pullCompensationMm": 0.35, "underlay": True},
    },
    "canvas": {
        "label": "帆布",
        "fill": {"fillAngleDeg": 45, "rowSpacingMm": 0.38, "maxStitchLengthMm": 3.5,
                 "underlay": True, "pullCompensationMm": 0.10},
        "running": {"runningStitchLengthMm": 2.5, "repeats": 1},
        "satin": {"zigzagSpacingMm": 0.38, "pullCompensationMm": 0.20, "underlay": True},
    },
    "other": {
        "label": "其他",
        "fill": {"fillAngleDeg": 45, "rowSpacingMm": 0.40, "maxStitchLengthMm": 3.0,
                 "underlay": True, "pullCompensationMm": 0.15},
        "running": {"runningStitchLengthMm": 2.0, "repeats": 1},
        "satin": {"zigzagSpacingMm": 0.40, "pullCompensationMm": 0.25, "underlay": True},
    },
}

# Whitelisted parameters with hard [min, max] clamps (spec §6 stage 4).
PARAM_LIMITS: dict[str, dict[str, tuple[float, float]]] = {
    "fill": {
        "fillAngleDeg": (-180, 180),
        "rowSpacingMm": (0.25, 1.5),
        "maxStitchLengthMm": (1.0, 7.0),
        "pullCompensationMm": (0.0, 0.6),
    },
    "running": {
        "runningStitchLengthMm": (1.0, 5.0),
        "repeats": (1, 5),
    },
    "satin": {
        "zigzagSpacingMm": (0.25, 1.0),
        "pullCompensationMm": (0.0, 0.8),
    },
}
BOOL_PARAMS = {"fill": {"underlay"}, "running": set(), "satin": {"underlay"}}
STITCH_TYPES = ("fill", "running", "satin")

# Satin columns: narrower is not stitchable, wider gives long loose stitches (spec §6 stage 4).
SATIN_WIDTH_MM = (1.0, 7.0)
THIN_RUNNING_MM = 1.2
INT_PARAMS = {"repeats"}

SIZE_LIMITS_MM = (5.0, 300.0)

# Detail level: denser rows and shorter stitches follow small shapes and curves more closely,
# at the cost of more stitches (time) and more stiffness / puckering on thin or stretchy fabric.
DETAIL_LEVELS: dict[str, dict] = {
    "standard": {"spacing": 1.0, "maxStitchMm": None, "runningMm": None},
    "fine": {"spacing": 0.875, "maxStitchMm": 2.5, "runningMm": 1.6},
    "ultra": {"spacing": 0.75, "maxStitchMm": 2.0, "runningMm": 1.2},
}


def apply_detail(stitch_type: str, params: dict, level: str | None) -> dict:
    """Tighten a region's parameters for the design's detail level (still clamped afterwards)."""
    d = DETAIL_LEVELS.get(level or "standard", DETAIL_LEVELS["standard"])
    out = dict(params)
    if stitch_type == "fill":
        out["rowSpacingMm"] = float(out.get("rowSpacingMm", 0.4)) * d["spacing"]
        if d["maxStitchMm"]:
            out["maxStitchLengthMm"] = min(float(out.get("maxStitchLengthMm", 3.0)), d["maxStitchMm"])
    elif stitch_type == "satin":
        out["zigzagSpacingMm"] = float(out.get("zigzagSpacingMm", 0.4)) * d["spacing"]
    elif stitch_type == "running" and d["runningMm"]:
        out["runningStitchLengthMm"] = min(float(out.get("runningStitchLengthMm", 2.0)), d["runningMm"])
    return out


def default_params(fabric: str, stitch_type: str) -> dict:
    preset = FABRIC_PRESETS.get(fabric) or FABRIC_PRESETS["other"]
    return dict(preset[stitch_type])


def clamp_params(stitch_type: str, params: dict) -> dict:
    """Drop unknown keys and clamp numbers into their allowed range."""
    limits = PARAM_LIMITS[stitch_type]
    out: dict = {}
    for key, value in params.items():
        if key in BOOL_PARAMS[stitch_type]:
            out[key] = bool(value)
        elif key in limits:
            lo, hi = limits[key]
            v = min(max(float(value), lo), hi)
            out[key] = int(round(v)) if key in INT_PARAMS else round(v, 3)
    return out
