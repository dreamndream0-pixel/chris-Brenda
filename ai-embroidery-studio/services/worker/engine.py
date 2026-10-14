"""Ink/Stitch CLI runner.

Runs the pinned Ink/Stitch build as a subprocess (never through a shell),
inside a per-job working directory, with a timeout, and extracts only
allow-listed files from the ZIP it writes to stdout.
"""
from __future__ import annotations

import io
import os
import shlex
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

# Command that starts Ink/Stitch, e.g. "/opt/venv/bin/python /opt/inkstitch/inkstitch.py"
# or the path of a packaged "inkstitch" binary. Set in the worker image.
INKSTITCH_CMD_ENV = "INKSTITCH_CMD"

DEFAULT_TIMEOUT_S = 180
MAX_ZIP_BYTES = 50 * 1024 * 1024
MAX_MEMBER_BYTES = 20 * 1024 * 1024
ALLOWED_SUFFIXES = {".dst", ".pes", ".txt", ".svg"}
OUTPUT_BASENAME = "design"


class EngineError(Exception):
    """Compilation failed; `code` is a stable error code for the job record."""

    def __init__(self, code: str, message: str, stderr: str = ""):
        super().__init__(message)
        self.code = code
        self.stderr = stderr


@dataclass
class CompileResult:
    files: dict[str, Path] = field(default_factory=dict)  # suffix -> path, e.g. ".dst"
    stderr: str = ""


def inkstitch_command() -> list[str]:
    raw = os.environ.get(INKSTITCH_CMD_ENV, "").strip()
    if not raw:
        raise EngineError("engine_not_configured", f"{INKSTITCH_CMD_ENV} is not set")
    argv = shlex.split(raw)
    exe = shutil.which(argv[0]) or argv[0]
    if not os.path.isabs(exe) or not os.access(exe, os.X_OK):
        raise EngineError("engine_not_configured", f"Ink/Stitch executable not found: {argv[0]}")
    return [exe, *argv[1:]]


def build_zip_args(svg_path: Path, formats: tuple[str, ...] = ("dst", "pes")) -> list[str]:
    args = ["--extension=zip", f"--custom-file-name={OUTPUT_BASENAME}"]
    args += [f"--format-{fmt}=True" for fmt in formats]
    args.append("--format-threadlist=True")
    args.append(str(svg_path))
    return args


def _child_env(job_dir: Path) -> dict[str, str]:
    # Minimal environment: no inherited secrets (API keys, DB URLs) reach the engine.
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": str(job_dir),
        "TMPDIR": str(job_dir),
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if os.environ.get("DISPLAY"):
        env["DISPLAY"] = os.environ["DISPLAY"]
    return env


def extract_allowed(zip_bytes: bytes, out_dir: Path) -> dict[str, Path]:
    """Extract allow-listed members by basename only (no path traversal)."""
    if len(zip_bytes) > MAX_ZIP_BYTES:
        raise EngineError("output_too_large", "engine output exceeds size limit")
    try:
        archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise EngineError("bad_engine_output", "engine did not return a ZIP archive") from exc

    files: dict[str, Path] = {}
    with archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            name = Path(info.filename.replace("\\", "/")).name
            suffix = Path(name).suffix.lower()
            if suffix not in ALLOWED_SUFFIXES or suffix in files:
                continue
            if info.file_size > MAX_MEMBER_BYTES:
                raise EngineError("output_too_large", f"{name} exceeds size limit")
            target = out_dir / f"{OUTPUT_BASENAME}{suffix}"
            with archive.open(info) as src:
                data = src.read(MAX_MEMBER_BYTES + 1)
            if len(data) > MAX_MEMBER_BYTES:
                raise EngineError("output_too_large", f"{name} exceeds size limit")
            target.write_bytes(data)
            files[suffix] = target
    return files


def compile_svg(svg_path: Path, out_dir: Path, timeout_s: int = DEFAULT_TIMEOUT_S,
                formats: tuple[str, ...] = ("dst", "pes")) -> CompileResult:
    """Compile an Ink/Stitch-parameterised SVG into embroidery files in `out_dir`."""
    cmd = inkstitch_command()
    out_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="inkstitch-job-") as tmp:
        job_dir = Path(tmp)
        # Copy the input under a fixed name so user file names never reach argv.
        local_svg = job_dir / "design.svg"
        shutil.copyfile(svg_path, local_svg)
        try:
            proc = subprocess.run(
                [*cmd, *build_zip_args(local_svg, formats)],
                cwd=job_dir,
                env=_child_env(job_dir),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=timeout_s,
                shell=False,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise EngineError("engine_timeout", f"Ink/Stitch exceeded {timeout_s}s") from exc

        stderr = proc.stderr.decode("utf-8", "replace")[-8000:]
        if proc.returncode != 0:
            raise EngineError("engine_failed", f"Ink/Stitch exited with {proc.returncode}", stderr)
        if not proc.stdout:
            raise EngineError("empty_engine_output", "Ink/Stitch produced no output", stderr)

        files = extract_allowed(proc.stdout, out_dir)

    missing = [f for f in formats if f".{f}" not in files]
    if missing:
        raise EngineError("missing_outputs", f"missing outputs: {', '.join(missing)}", stderr)
    return CompileResult(files=files, stderr=stderr)
