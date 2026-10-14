import io
import sys
import zipfile
from pathlib import Path

import pytest

import engine
from helpers import make_pattern

FAKE = Path(__file__).with_name("fake_inkstitch.py")
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "fixture_circle_fill.svg"


def _zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    return buf.getvalue()


def _use_fake(monkeypatch, mode, payload):
    monkeypatch.setenv(engine.INKSTITCH_CMD_ENV, f"{sys.executable} {FAKE} {mode} {payload}")


def test_extract_blocks_traversal_and_unknown_types(tmp_path):
    data = _zip({"../../etc/evil.dst": b"A", "x/design.pes": b"B", "run.sh": b"C", "/abs/notes.txt": b"D"})
    files = engine.extract_allowed(data, tmp_path)
    assert set(files) == {".dst", ".pes", ".txt"}
    assert all(p.parent == tmp_path for p in files.values())
    assert not (tmp_path / "run.sh").exists()


def test_extract_rejects_non_zip(tmp_path):
    with pytest.raises(engine.EngineError) as e:
        engine.extract_allowed(b"plain text", tmp_path)
    assert e.value.code == "bad_engine_output"


def test_args_never_contain_user_filename(tmp_path):
    args = engine.build_zip_args(tmp_path / "design.svg")
    assert args[0] == "--extension=zip"
    assert "--format-dst=True" in args and "--format-pes=True" in args


def test_unconfigured_engine(monkeypatch, tmp_path):
    monkeypatch.delenv(engine.INKSTITCH_CMD_ENV, raising=False)
    with pytest.raises(engine.EngineError) as e:
        engine.compile_svg(FIXTURE, tmp_path)
    assert e.value.code == "engine_not_configured"


def test_compile_happy_path(monkeypatch, tmp_path):
    dst = make_pattern(tmp_path / "p", [("#654a3b", 0, 10)], ".dst")
    pes = make_pattern(tmp_path / "p", [("#654a3b", 0, 10)], ".pes")
    payload = tmp_path / "payload.zip"
    payload.write_bytes(_zip({"design.dst": dst.read_bytes(), "design.pes": pes.read_bytes()}))
    _use_fake(monkeypatch, "zip", payload)
    res = engine.compile_svg(FIXTURE, tmp_path / "out")
    assert res.files[".dst"].read_bytes() == dst.read_bytes()


def test_compile_missing_pes(monkeypatch, tmp_path):
    payload = tmp_path / "payload.zip"
    payload.write_bytes(_zip({"design.dst": b"x"}))
    _use_fake(monkeypatch, "zip", payload)
    with pytest.raises(engine.EngineError) as e:
        engine.compile_svg(FIXTURE, tmp_path / "out")
    assert e.value.code == "missing_outputs"


def test_compile_failure_keeps_stderr(monkeypatch, tmp_path):
    _use_fake(monkeypatch, "fail", "-")
    with pytest.raises(engine.EngineError) as e:
        engine.compile_svg(FIXTURE, tmp_path / "out")
    assert e.value.code == "engine_failed" and "boom" in e.value.stderr


def test_compile_timeout(monkeypatch, tmp_path):
    _use_fake(monkeypatch, "sleep", "5")
    with pytest.raises(engine.EngineError) as e:
        engine.compile_svg(FIXTURE, tmp_path / "out", timeout_s=1)
    assert e.value.code == "engine_timeout"


def test_child_env_drops_secrets(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    env = engine._child_env(tmp_path)
    assert "OPENAI_API_KEY" not in env and env["HOME"] == str(tmp_path)
