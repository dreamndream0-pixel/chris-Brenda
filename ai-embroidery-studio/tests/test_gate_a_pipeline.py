"""gate_a.py end to end with the fake engine: report, preview JSON and viewer HTML."""
import json
import sys
from pathlib import Path

import gate_a
import engine
from helpers import make_pattern
from test_engine import FAKE, _zip

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _run(monkeypatch, tmp_path, size_mm):
    dst = make_pattern(tmp_path / "p", [("#654a3b", 0, size_mm)], ".dst")
    pes = make_pattern(tmp_path / "p", [("#654a3b", 0, size_mm)], ".pes")
    payload = tmp_path / "payload.zip"
    payload.write_bytes(_zip({"design.dst": dst.read_bytes(), "design.pes": pes.read_bytes()}))
    monkeypatch.setenv(engine.INKSTITCH_CMD_ENV, f"{sys.executable} {FAKE} zip {payload}")
    out = tmp_path / "out"
    rc = gate_a.main(["--fixtures", str(FIXTURES), "--out", str(out), "--only", "fixture_circle_fill.svg"])
    return rc, out


def test_pass_writes_report_and_viewer(monkeypatch, tmp_path):
    rc, out = _run(monkeypatch, tmp_path, 30)
    assert rc == 0
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert report[0]["ok"] and report[0]["dst"]["summary"]["stitches"] > 0
    html = (out / "preview.html").read_text(encoding="utf-8")
    assert "/*__GATE_A_DATA__*/" not in html and '"fixture":"fixture_circle_fill.svg"' in html
    assert (out / "fixture_circle_fill" / "stitches.json").exists()


def test_wrong_size_fails(monkeypatch, tmp_path):
    rc, out = _run(monkeypatch, tmp_path, 12)
    assert rc == 1
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert any("widthMm_out_of_tolerance" in e for e in report[0]["errors"])
