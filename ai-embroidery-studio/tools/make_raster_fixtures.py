"""Regenerate fixtures/raster/*: python tools/make_raster_fixtures.py

Drawn at 4x and downsampled so edges are anti-aliased like real exports.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parents[1] / "fixtures" / "raster"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
S = 4


def wordmark():
    img = Image.new("RGB", (1200 * S, 420 * S), "white")
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT, 300 * S)
    d.text((600 * S, 210 * S), "CHUÉ", fill="#2b211c", font=font, anchor="mm")
    img.resize((1200, 420), Image.LANCZOS).save(OUT / "wordmark_chue.png")


def two_color():
    img = Image.new("RGBA", (800 * S, 500 * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((40 * S, 40 * S, 460 * S, 460 * S), fill="#c0392b")
    d.rounded_rectangle((380 * S, 150 * S, 760 * S, 350 * S), radius=40 * S, fill="#2471a3")
    img.resize((800, 500), Image.LANCZOS).save(OUT / "two_color_transparent.png")


def mascot():
    img = Image.new("RGB", (800 * S, 800 * S), "#eeeeea")
    d = ImageDraw.Draw(img)
    d.ellipse((100 * S, 120 * S, 700 * S, 720 * S), fill="#f2c230", outline="#3a2a1a", width=18 * S)
    d.ellipse((90 * S, 60 * S, 260 * S, 230 * S), fill="#3a2a1a")   # ears
    d.ellipse((540 * S, 60 * S, 710 * S, 230 * S), fill="#3a2a1a")
    d.ellipse((250 * S, 330 * S, 330 * S, 430 * S), fill="#3a2a1a")  # eyes
    d.ellipse((470 * S, 330 * S, 550 * S, 430 * S), fill="#3a2a1a")
    d.ellipse((190 * S, 470 * S, 290 * S, 540 * S), fill="#e98a8a")  # cheeks
    d.ellipse((510 * S, 470 * S, 610 * S, 540 * S), fill="#e98a8a")
    d.arc((320 * S, 450 * S, 480 * S, 590 * S), 20, 160, fill="#3a2a1a", width=16 * S)
    img.resize((800, 800), Image.LANCZOS).save(OUT / "mascot.jpg", quality=70)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    wordmark(); two_color(); mascot()
    print(sorted(p.name for p in OUT.iterdir()))
