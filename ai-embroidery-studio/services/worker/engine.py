"""Ink/Stitch CLI runner.

Runs the pinned Ink/Stitch build as a subprocess (never through a shell),
inside a per-job working directory, with a timeout, and extracts only
allow-listed files from the ZIP it writes to stdout.
"""
from __future__ import annotations

import io
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

# Command that starts Ink/Stitch, e.g. "/opt/venv/bin/python /opt/inkstitch/inkstitch.py"
# or the path of a packaged "inkstitch" binary. Set in the worker image.
INKSTITCH_CMD_ENV = "INKSTITCH_CMD"

DEFAULT_TIMEOUT_S = int(os.environ.get("INKSTITCH_TIMEOUT_S", "300"))
CACHE_SIZE_MB = 20  # per cache dir (per project); Ink/Stitch default is 100
MAX_ZIP_BYTES = 50 * 1024 * 1024
MAX_MEMBER_BYTES = 20 * 1024 * 1024
ALLOWED_SUFFIXES = {".dst", ".pes", ".txt", ".svg"}
OUTPUT_BASENAME = "design"
# Ink/Stitch shows a blocking "update document?" dialog for SVGs without this
# version tag, which hangs a headless worker. Every compiled SVG must carry it.
INKSTITCH_SVG_VERSION = 4
_SVG_VERSION_RE = re.compile(rb"<(?:\w+:)?inkstitch_svg_version>\s*(\d+)\s*<")


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
    lexer = shlex.shlex(raw, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    if os.name == "nt":
        lexer.escape = ""  # Windows path separators are not POSIX escape characters
    argv = list(lexer)
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


def check_svg_version(svg_bytes: bytes) -> None:
    match = _SVG_VERSION_RE.search(svg_bytes)
    if not match or int(match.group(1)) != INKSTITCH_SVG_VERSION:
        raise EngineError(
            "unsupported_svg_version",
            f"SVG must contain <inkstitch:inkstitch_svg_version>{INKSTITCH_SVG_VERSION}</...> metadata",
        )


def _run(argv: list[str], cwd: Path, env: dict[str, str], timeout_s: int) -> subprocess.CompletedProcess:
    """Run in its own process group so a timeout also kills wrappers' children (xvfb-run, Xvfb)."""
    group = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
             if os.name == "nt" else {"start_new_session": True})
    proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            shell=False, **group)
    try:
        stdout, stderr = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(["taskkill.exe", "/PID", str(proc.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=subprocess.CREATE_NO_WINDOW, check=False)
            if proc.poll() is None:
                proc.kill()
        else:
            os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        raise
    return subprocess.CompletedProcess(argv, proc.returncode, stdout, stderr)


def prepare_cache_dir(cache_dir: Path) -> Path:
    """Ink/Stitch keeps its stitch-plan cache under $XDG_CONFIG_HOME/inkstitch. Reusing one directory
    per project lets a recompile skip regions whose geometry and parameters did not change."""
    settings = cache_dir / "inkstitch" / "settings.json"
    if not settings.exists():
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(json.dumps({"cache_size": CACHE_SIZE_MB}))
    return cache_dir


def _child_env(job_dir: Path, cache_dir: Path | None = None) -> dict[str, str]:
    # Minimal environment: no inherited secrets (API keys, DB URLs) reach the engine.
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": str(job_dir),
        "TMPDIR": str(job_dir),
        "XDG_CONFIG_HOME": str(cache_dir or job_dir),
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if os.environ.get("DISPLAY"):
        env["DISPLAY"] = os.environ["DISPLAY"]
    if os.name == "nt":
        for key in ("SystemRoot", "WINDIR"):
            if os.environ.get(key):
                env[key] = os.environ[key]
        env.update(TEMP=str(job_dir), TMP=str(job_dir), USERPROFILE=str(job_dir))
        env["PATH"] = os.defpath
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
                formats: tuple[str, ...] = ("dst", "pes"), cache_dir: Path | None = None) -> CompileResult:
    """Compile an Ink/Stitch-parameterised SVG into embroidery files in `out_dir`."""
    cmd = inkstitch_command()
    out_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="inkstitch-job-") as tmp:
        job_dir = Path(tmp)
        # Copy the input under a fixed name so user file names never reach argv.
        svg_bytes = svg_path.read_bytes()
        check_svg_version(svg_bytes)
        local_svg = job_dir / "design.svg"
        local_svg.write_bytes(svg_bytes)
        try:
            proc = _run([*cmd, *build_zip_args(local_svg, formats)], job_dir,
                        _child_env(job_dir, prepare_cache_dir(cache_dir) if cache_dir else None), timeout_s)
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
