"""Re-read exported embroidery files and check them against expectations.

pyembroidery units are 0.1 mm. Only STITCH points count toward the
design extents; jumps/trims are reported separately.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

import pyembroidery as pe

UNITS_PER_MM = 10.0


@dataclass
class StitchSummary:
    stitches: int
    jumps: int
    trims: int
    color_changes: int
    color_blocks: int  # colour segments that contain at least one stitch
    width_mm: float
    height_mm: float
    min_x_mm: float
    min_y_mm: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ValidationReport:
    file: str
    ok: bool
    summary: StitchSummary | None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["summary"] = self.summary.to_dict() if self.summary else None
        return d


def read_pattern(path: Path) -> pe.EmbPattern:
    pattern = pe.read(str(path))
    if pattern is None:
        raise ValueError(f"unreadable embroidery file: {path.name}")
    return pattern


def summarize(pattern: pe.EmbPattern) -> StitchSummary:
    stitches = jumps = trims = color_changes = 0
    color = 0
    colors_with_stitches: set[int] = set()
    xs: list[float] = []
    ys: list[float] = []

    for x, y, cmd in pattern.stitches:
        command = cmd & pe.COMMAND_MASK
        if command == pe.STITCH:
            stitches += 1
            colors_with_stitches.add(color)
            xs.append(x)
            ys.append(y)
        elif command == pe.JUMP:
            jumps += 1
        elif command == pe.TRIM:
            trims += 1
        elif command in (pe.COLOR_CHANGE, pe.NEEDLE_SET):
            # A leading needle-set before any stitch only selects the first colour.
            if stitches or command == pe.COLOR_CHANGE:
                color_changes += 1
                color += 1

    if xs:
        min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
    else:
        min_x = max_x = min_y = max_y = 0.0

    return StitchSummary(
        stitches=stitches,
        jumps=jumps,
        trims=trims,
        color_changes=color_changes,
        color_blocks=len(colors_with_stitches),
        width_mm=round((max_x - min_x) / UNITS_PER_MM, 2),
        height_mm=round((max_y - min_y) / UNITS_PER_MM, 2),
        min_x_mm=round(min_x / UNITS_PER_MM, 2),
        min_y_mm=round(min_y / UNITS_PER_MM, 2),
    )


def validate_file(path: Path, expected: dict | None = None) -> ValidationReport:
    """Validate one DST/PES. `expected` keys: widthMm, heightMm, toleranceMm, colors."""
    try:
        summary = summarize(read_pattern(path))
    except Exception as exc:  # noqa: BLE001 - any reader failure is a validation failure
        return ValidationReport(file=path.name, ok=False, summary=None, errors=[f"read_failed: {exc}"])

    errors: list[str] = []
    warnings: list[str] = ["factory_test_required"]

    if summary.stitches == 0:
        errors.append("no_stitches")

    if expected:
        tol = float(expected.get("toleranceMm", 1.0))
        for key, actual in (("widthMm", summary.width_mm), ("heightMm", summary.height_mm)):
            if key in expected and abs(actual - float(expected[key])) > tol:
                errors.append(f"{key}_out_of_tolerance: expected {expected[key]}±{tol}, got {actual}")
        if "colors" in expected and summary.color_blocks != int(expected["colors"]):
            errors.append(f"color_blocks_mismatch: expected {expected['colors']}, got {summary.color_blocks}")

    if summary.jumps > max(20, summary.stitches // 50):
        warnings.append("many_jumps")

    return ValidationReport(file=path.name, ok=not errors, summary=summary, errors=errors, warnings=warnings)


def compare_exports(a: ValidationReport, b: ValidationReport, tolerance_mm: float = 0.2) -> list[str]:
    """Cross-check two formats (e.g. DST vs PES) compiled from the same revision."""
    if not (a.summary and b.summary):
        return ["cross_check_skipped"]
    issues = []
    if a.summary.stitches != b.summary.stitches:
        issues.append(f"stitch_count_differs: {a.file}={a.summary.stitches} {b.file}={b.summary.stitches}")
    for attr in ("width_mm", "height_mm"):
        if abs(getattr(a.summary, attr) - getattr(b.summary, attr)) > tolerance_mm:
            issues.append(f"{attr}_differs between {a.file} and {b.file}")
    return issues
