"""Regression cases for contour loss before the embroidery engine sees the art."""
import io

import numpy as np
from PIL import Image

from services.worker.raster_import import RasterOptions, _clean_labels, _resize, foreground_mask, import_raster


def png(rgba):
    buf = io.BytesIO()
    Image.fromarray(rgba).save(buf, "PNG")
    return buf.getvalue()


def test_cleanup_does_not_depend_on_palette_numbering():
    labels = np.array([[0, 0, 0], [1, 1, 0], [2, 2, 1]], np.int16)
    fg = np.ones(labels.shape, bool)
    permutation = np.array([1, 2, 0])
    a, _ = _clean_labels(labels, fg, 3, 1)
    b, _ = _clean_labels(permutation[labels], fg, 3, 1)
    assert np.array_equal(permutation[a], b)
    assert np.array_equal(a, labels)


def test_cleanup_keeps_a_long_one_pixel_line():
    labels = np.zeros((30, 30), np.int16)
    fg = np.zeros_like(labels, bool)
    fg[15, 3:27] = True
    clean, _ = _clean_labels(labels, fg, 1, 4)
    assert np.array_equal(clean == 0, fg)


def test_fine_line_survives_vectorization_and_planning():
    from services.worker.rules import plan_design
    rgba = np.zeros((240, 240, 4), np.uint8)
    rgba[80:200, 40:200] = [35, 75, 115, 255]
    rgba[40, 40:200] = [35, 75, 115, 255]
    design, *_ = import_raster(png(rgba), 80, "woven_cotton", RasterOptions())
    planned = plan_design(design)
    assert len(planned["regions"]) == 2
    assert {r["stitchType"] for r in planned["regions"]} == {"fill", "running"}


def test_background_removal_preserves_enclosed_white_details():
    rgba = np.full((100, 100, 4), 255, np.uint8)
    rgba[10:90, 10:90, :3] = [180, 30, 30]
    rgba[40:60, 40:60, :3] = 255
    fg, _ = foreground_mask(rgba, RasterOptions())
    assert fg[50, 50]  # white eye/highlight surrounded by the artwork
    assert not fg[0, 0]


def test_small_transparent_border_is_still_transparency():
    rgba = np.full((300, 300, 4), 255, np.uint8)
    rgba[0, :, 3] = 0  # < 1% of the image; old heuristic erased white artwork
    fg, _ = foreground_mask(rgba, RasterOptions())
    assert fg[150, 150] and not fg[0, 150]


def test_auto_colors_keep_a_small_contrasting_feature():
    rgba = np.zeros((300, 300, 4), np.uint8)
    rgba[10:290, 10:290] = [200, 40, 40, 255]
    rgba[140:148, 140:148] = [20, 180, 60, 255]  # less than 0.1% of foreground
    design, *_ = import_raster(png(rgba), 70, "woven_cotton", RasterOptions())
    assert len(design["palette"]) == 2


def test_small_separate_detail_survives_default_import():
    rgba = np.zeros((400, 400, 4), np.uint8)
    rgba[60:380, 60:380] = [40, 40, 40, 255]
    rgba[20:23, 20:23] = [40, 40, 40, 255]
    design, *_ = import_raster(png(rgba), 80, "woven_cotton", RasterOptions())
    assert len(design["regions"]) == 2


def test_cleanup_never_expands_into_transparent_pixels():
    labels = np.zeros((12, 12), np.int16)
    fg = np.zeros_like(labels, bool)
    fg[2:10, 2:10] = True
    fg[5, 5] = False
    clean, _ = _clean_labels(labels, fg, 1, 1)
    assert np.all(clean[~fg] == -1)


def test_all_background_mode_can_remove_enclosed_counters():
    rgba = np.full((100, 100, 4), 255, np.uint8)
    rgba[10:90, 10:90, :3] = [180, 30, 30]
    rgba[40:60, 40:60, :3] = 255
    fg, _ = foreground_mask(rgba, RasterOptions(background_scope="all"))
    assert not fg[50, 50] and fg[20, 20]


def test_resize_does_not_mix_hidden_rgb_into_the_edge():
    rgba = np.zeros((1700, 1700, 4), np.uint8)
    rgba[..., :3] = [0, 0, 255]  # invisible blue
    rgba[:, 849:] = [255, 0, 0, 255]
    small = _resize(rgba)
    edge = small[(small[..., 3] > 0) & (small[..., 3] < 255)]
    assert len(edge) and np.all(edge[:, :3] == [255, 0, 0])


def test_cleanup_modes_and_options_are_recorded():
    rgba = np.zeros((400, 400, 4), np.uint8)
    rgba[60:380, 60:380] = [40, 40, 40, 255]
    rgba[20:23, 20:23] = [40, 40, 40, 255]
    opts = RasterOptions(detail_mode="clean", background_scope="all", remove_background=False)
    design, *_ = import_raster(png(rgba), 80, "woven_cotton", opts)
    assert len(design["regions"]) == 1
    assert design["raster"]["options"]["detailMode"] == "clean"
    assert design["raster"]["options"]["removeBackground"] is False
    assert "small_details_removed" in design["warnings"]


def test_forced_low_color_count_reports_lost_contrast():
    rgba = np.zeros((300, 300, 4), np.uint8)
    rgba[10:290, 10:290] = [200, 40, 40, 255]
    rgba[140:148, 140:148] = [20, 180, 60, 255]
    design, *_ = import_raster(png(rgba), 70, "woven_cotton", RasterOptions(colors=1))
    assert "color_detail_limited" in design["warnings"]
