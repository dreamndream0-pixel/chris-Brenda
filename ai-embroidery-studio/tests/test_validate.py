from helpers import make_pattern
from preview import stitch_sequence
from validate import compare_exports, validate_file


def test_single_color_summary(tmp_path):
    dst = make_pattern(tmp_path / "a", [("#654a3b", 0, 30)])
    rep = validate_file(dst, {"widthMm": 30, "heightMm": 30, "toleranceMm": 1, "colors": 1})
    assert rep.ok, rep.errors
    assert rep.summary.stitches > 0
    assert rep.summary.color_blocks == 1
    assert "factory_test_required" in rep.warnings


def test_two_colors_and_size_mismatch(tmp_path):
    dst = make_pattern(tmp_path / "b", [("#c0392b", 0, 20), ("#2471a3", 20, 20)])
    rep = validate_file(dst, {"widthMm": 40, "heightMm": 20, "toleranceMm": 1, "colors": 2})
    assert rep.ok, rep.errors
    assert rep.summary.color_changes == 1

    bad = validate_file(dst, {"widthMm": 60, "heightMm": 20, "toleranceMm": 1, "colors": 1})
    assert not bad.ok
    assert any(e.startswith("widthMm_out_of_tolerance") for e in bad.errors)
    assert any(e.startswith("color_blocks_mismatch") for e in bad.errors)


def test_unreadable_file_fails(tmp_path):
    junk = tmp_path / "x.dst"
    junk.write_bytes(b"not an embroidery file")
    rep = validate_file(junk)
    assert not rep.ok


def test_dst_pes_cross_check(tmp_path):
    blocks = [("#c0392b", 0, 20), ("#2471a3", 20, 20)]
    dst = validate_file(make_pattern(tmp_path / "c", blocks, ".dst"))
    pes = validate_file(make_pattern(tmp_path / "c", blocks, ".pes"))
    assert compare_exports(dst, pes) == []


def test_preview_replays_every_stitch(tmp_path):
    blocks = [("#c0392b", 0, 20), ("#2471a3", 20, 20)]
    dst = make_pattern(tmp_path / "d", blocks, ".dst")
    pes = make_pattern(tmp_path / "d", blocks, ".pes")
    data = stitch_sequence(dst, palette_source=pes)
    pts = data["points"]
    assert len(pts) % 4 == 0
    played = sum(1 for i in range(2, len(pts), 4) if pts[i] == 0)
    assert played == data["summary"]["stitches"]
    # DST stores no colours; they come from the PES. PES snaps to the Brother thread
    # palette, so hues are approximate - the factory colour list must come from the
    # threadlist / spec sheet, not from PES.
    assert len(data["colors"]) >= 2 and data["colors"][0] != data["colors"][1]
    assert min(pts[0::4]) >= 0 and min(pts[1::4]) >= 0
