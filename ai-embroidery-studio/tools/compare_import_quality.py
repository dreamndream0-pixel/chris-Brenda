"""Reproducible source-processing comparison; not a machine stitch-out simulation.

Run from the project root: python tools/compare_import_quality.py --baseline-ref 824c7da
Writes PNG and JSON into ignored out/quality/. Uses only synthetic fixtures.
"""
import argparse
import io
import json
import subprocess
import sys
import types
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.worker import raster_import as current


def fixtures():
    white = np.full((240, 240, 4), 255, np.uint8)
    white[25:215, 25:215, :3] = [172, 45, 63]
    white[85:115, 65:95, :3] = 255
    white[85:115, 145:175, :3] = 255
    yield "Enclosed white highlights", white, 70
    accent = np.zeros((300, 300, 4), np.uint8)
    accent[10:290, 10:290] = [200, 40, 40, 255]
    accent[140:152, 140:152] = [20, 180, 60, 255]
    yield "Small contrasting colour", accent, 70
    thin = np.zeros((240, 240, 4), np.uint8)
    thin[80:200, 40:200] = [35, 75, 115, 255]
    thin[40, 40:200] = [35, 75, 115, 255]
    yield "Fine horizontal line", thin, 80
    dot = np.zeros((400, 400, 4), np.uint8)
    dot[100:380, 50:380] = [35, 75, 115, 255]
    dot[40:43, 40:43] = [35, 75, 115, 255]
    yield "Separate small accent", dot, 80


def tile(array):
    image = Image.fromarray(array).convert("RGBA").resize((240, 240), Image.Resampling.NEAREST)
    bg = Image.new("RGBA", (240, 240), "#eeeeee")
    draw = ImageDraw.Draw(bg)
    for y in range(0, 240, 10):
        for x in range(0, 240, 10):
            if (x // 10 + y // 10) % 2:
                draw.rectangle((x, y, x + 9, y + 9), fill="#d4d4d4")
    return Image.alpha_composite(bg, image).convert("RGB")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-ref", required=True)
    args = parser.parse_args()
    # Resolve a commit before composing the git object name; never invoke a shell.
    commit = subprocess.check_output(["git", "rev-parse", "--verify", "--end-of-options",
                                      args.baseline_ref + "^{commit}"], cwd=ROOT, text=True).strip()
    source = subprocess.check_output(["git", "show", f"{commit}:ai-embroidery-studio/services/worker/raster_import.py"],
                                     cwd=ROOT).decode("utf-8")
    baseline = types.ModuleType("services.worker.baseline_raster")
    baseline.__package__ = "services.worker"
    sys.modules[baseline.__name__] = baseline
    exec(compile(source, "baseline_raster_import.py", "exec"), baseline.__dict__)
    out = ROOT / "out" / "quality"
    out.mkdir(parents=True, exist_ok=True)
    font = ImageFont.load_default(size=17)
    sheet = Image.new("RGB", (800, 1240), "#faf8f4")
    draw = ImageDraw.Draw(sheet)
    draw.text((20, 12), "Source processing regression comparison (not stitched output)", font=font, fill="#222222")
    for col, heading in enumerate(("Source", "Before", "After")):
        draw.text((20 + col * 260, 45), heading, font=font, fill="#333333")
    records = []
    for row, (name, rgba, width) in enumerate(fixtures()):
        buf = io.BytesIO()
        Image.fromarray(rgba).save(buf, "PNG")
        data = buf.getvalue()
        before = baseline.raster_to_svg(data, width, baseline.RasterOptions())
        after = current.raster_to_svg(data, width, current.RasterOptions())
        y = 85 + row * 285
        draw.text((20, y), name, font=font, fill="#222222")
        for col, array in enumerate((rgba, before[3], after[3])):
            sheet.paste(tile(array), (20 + col * 260, y + 26))
        records.append({"case": name, "widthMm": width,
                        "before": before[1], "after": after[1]})
    sheet.save(out / "comparison.png")
    (out / "comparison.json").write_text(json.dumps({"baseline": commit, "cases": records}, indent=2), encoding="utf-8")
    print(out / "comparison.png")


if __name__ == "__main__":
    main()
