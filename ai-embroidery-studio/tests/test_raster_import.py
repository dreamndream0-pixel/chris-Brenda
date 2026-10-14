"""Raster pipeline: fixtures from tools/make_raster_fixtures.py."""
import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from services.worker.raster_import import RasterOptions, import_raster, load_image
from services.worker.svg_import import ImportError_

RASTER = Path(__file__).resolve().parents[1] / "fixtures" / "raster"


def _hex_close(a: str, b: str, tol: int = 40) -> bool:
    return all(abs(int(a[i:i + 2], 16) - int(b[i:i + 2], 16)) <= tol for i in (1, 3, 5))


def test_wordmark_single_color_keeps_accent():
    design, thumb, preview = import_raster((RASTER / "wordmark_chue.png").read_bytes(), 80, "woven_cotton", RasterOptions())
    assert len(design["palette"]) == 1 and _hex_close(design["palette"][0]["hex"], "#2b211c")
    assert len(design["regions"]) == 5  # C, H, U, E and the accent of É
    assert design["raster"]["backgroundHex"] == "#ffffff"
    w, h = design["sizeMm"]["width"], design["sizeMm"]["height"]
    assert w == 80 and 23 < h < 28  # accent raises the top edge
    assert thumb.startswith(b"\x89PNG") and preview.startswith(b"\x89PNG")


def test_transparent_png_uses_alpha():
    design, *_ = import_raster((RASTER / "two_color_transparent.png").read_bytes(), 70, "woven_cotton", RasterOptions())
    hexes = [c["hex"] for c in design["palette"]]
    assert len(hexes) == 2 and _hex_close(hexes[0], "#c0392b") and _hex_close(hexes[1], "#2471a3")
    assert design["raster"]["backgroundHex"] is None


def test_mascot_jpeg_auto_colors_keep_small_details():
    design, *_ = import_raster((RASTER / "mascot.jpg").read_bytes(), 70, "woven_cotton", RasterOptions())
    hexes = [c["hex"] for c in design["palette"]]
    assert len(hexes) == 3, hexes
    assert _hex_close(hexes[0], "#f2c230")             # largest area first (sewn first)
    assert any(_hex_close(h, "#e98a8a") for h in hexes)  # pink cheeks survive auto colour count
    assert all(r["stitchType"] == "fill" for r in design["regions"])


def test_forced_color_count():
    design, *_ = import_raster((RASTER / "mascot.jpg").read_bytes(), 70, "woven_cotton", RasterOptions(colors=2))
    assert len(design["palette"]) == 2


def test_keep_background_includes_it():
    design, *_ = import_raster((RASTER / "mascot.jpg").read_bytes(), 70, "woven_cotton",
                               RasterOptions(colors=4, remove_background=False))
    assert any(_hex_close(c["hex"], "#eeeeea", 12) for c in design["palette"])


def _png(img: Image.Image, fmt="PNG", **kw) -> bytes:
    buf = io.BytesIO()
    img.save(buf, fmt, **kw)
    return buf.getvalue()


def test_exif_orientation_applied_and_dropped():
    img = Image.new("RGB", (200, 100), "white")
    img.paste((0, 0, 0), (20, 20, 180, 60))
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90° on display
    rgba = load_image(_png(img, "JPEG", exif=exif.tobytes()))
    assert rgba.shape[:2] == (200, 100)


@pytest.mark.parametrize("data,code", [
    (b"GIF89a" + b"\0" * 100, "unsupported_file_type"),
    (b"\x89PNG\r\n\x1a\n" + b"garbage" * 10, "invalid_image"),
    (b'<svg xmlns="http://www.w3.org/2000/svg"/>', "unsupported_file_type"),
])
def test_bad_images(data, code):
    with pytest.raises(ImportError_) as e:
        load_image(data)
    assert e.value.code == code


def test_oversized_image_rejected():
    with pytest.raises(ImportError_) as e:
        load_image(_png(Image.new("L", (5000, 20))))
    assert e.value.code == "image_too_large"


def test_blank_image_has_no_foreground():
    with pytest.raises(ImportError_) as e:
        import_raster(_png(Image.new("RGB", (300, 300), "white")), 50, "woven_cotton", RasterOptions())
    assert e.value.code == "no_foreground"


def test_manual_background_color():
    img = Image.new("RGB", (300, 300), "#336699")
    img.paste((255, 255, 255), (0, 0, 300, 40))  # light band on the border fools auto-detection
    img.paste((250, 200, 0), (100, 100, 200, 200))
    design, *_ = import_raster(_png(img), 50, "woven_cotton", RasterOptions(background_hex="#336699"))
    assert any(_hex_close(c["hex"], "#fac800") for c in design["palette"])
    assert not any(_hex_close(c["hex"], "#336699", 15) for c in design["palette"])
