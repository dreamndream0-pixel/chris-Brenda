"""Decode an exported embroidery file into the stitch sequence the editor plays.

The preview is built from the file the factory receives (never re-simulated
from the source SVG), so what the Canvas draws is what the machine sews.
"""
from __future__ import annotations

import json
from pathlib import Path

import pyembroidery as pe

from validate import UNITS_PER_MM, read_pattern, summarize

# Compact command codes used by the front-end player.
CMD_STITCH, CMD_JUMP, CMD_TRIM, CMD_COLOR = 0, 1, 2, 3
FALLBACK_COLORS = ["#654a3b", "#c0392b", "#2471a3", "#1e8449", "#b7950b", "#6c3483"]


def _thread_hex(thread: pe.EmbThread) -> str:
    return "#%06x" % (thread.color & 0xFFFFFF)


def stitch_sequence(path: Path, palette_source: Path | None = None) -> dict:
    """Return {widthMm, heightMm, colors, points, summary}.

    `points` is a flat list [x_mm, y_mm, cmd, colorIndex, ...] with the
    origin moved to the top-left of the stitched area. `palette_source`
    (typically the PES) supplies thread colours, which DST cannot store.
    """
    pattern = read_pattern(path)
    summary = summarize(pattern)
    ox, oy = summary.min_x_mm, summary.min_y_mm

    colors = [_thread_hex(t) for t in pattern.threadlist]
    if palette_source and palette_source.exists():
        colors = [_thread_hex(t) for t in read_pattern(palette_source).threadlist] or colors

    points: list[float] = []
    color = 0
    seen_stitch = False
    for x, y, cmd in pattern.stitches:
        command = cmd & pe.COMMAND_MASK
        if command == pe.STITCH:
            code = CMD_STITCH
            seen_stitch = True
        elif command == pe.JUMP:
            code = CMD_JUMP
        elif command == pe.TRIM:
            code = CMD_TRIM
        elif command in (pe.COLOR_CHANGE, pe.NEEDLE_SET):
            if not (seen_stitch or command == pe.COLOR_CHANGE):
                continue
            color += 1
            code = CMD_COLOR
        else:
            continue
        points += [round(x / UNITS_PER_MM - ox, 2), round(y / UNITS_PER_MM - oy, 2), code, color]

    while len(colors) < summary.color_blocks:
        colors.append(FALLBACK_COLORS[len(colors) % len(FALLBACK_COLORS)])

    return {
        "source": path.name,
        "widthMm": summary.width_mm,
        "heightMm": summary.height_mm,
        "colors": colors,
        "points": points,
        "summary": summary.to_dict(),
    }


def write_preview(path: Path, out_json: Path, palette_source: Path | None = None) -> dict:
    data = stitch_sequence(path, palette_source)
    out_json.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    return data
