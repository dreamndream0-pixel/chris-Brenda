"""Gate A smoke run: fixed SVG -> Ink/Stitch ZIP -> DST/PES -> re-read -> stitch preview.

Usage:
    INKSTITCH_CMD="/opt/venv/bin/python /opt/inkstitch/inkstitch.py" \
        python -m services.worker.gate_a --fixtures fixtures --out out/gate-a

Exits non-zero if any fixture fails. Writes per-fixture files, report.json
and preview.html (open it in a browser to play the decoded stitches).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .engine import EngineError, compile_svg
from .preview import write_preview
from .validate import compare_exports, validate_file

ROOT = Path(__file__).resolve().parents[2]
VIEWER_TEMPLATE = ROOT / "tools" / "stitch_viewer.html"


def run_fixture(svg: Path, out_dir: Path, expected: dict | None) -> dict:
    result: dict = {"fixture": svg.name, "ok": False, "errors": [], "warnings": []}
    try:
        compiled = compile_svg(svg, out_dir)
    except EngineError as exc:
        result["errors"].append(f"{exc.code}: {exc}")
        if exc.stderr:
            result["stderr"] = exc.stderr
        return result

    dst = validate_file(compiled.files[".dst"], expected)
    pes = validate_file(compiled.files[".pes"], expected)
    result["dst"] = dst.to_dict()
    result["pes"] = pes.to_dict()
    result["errors"] += [f"dst.{e}" for e in dst.errors] + [f"pes.{e}" for e in pes.errors]
    # DST and PES encode long stitches/trims differently, so differences are warnings.
    result["warnings"] += sorted(set(dst.warnings + pes.warnings)) + compare_exports(dst, pes)

    if dst.summary:
        preview = write_preview(compiled.files[".dst"], out_dir / "stitches.json", compiled.files[".pes"])
        # The player must replay exactly the decoded file: same number of stitch points.
        played = sum(1 for i in range(2, len(preview["points"]), 4) if preview["points"][i] == 0)
        if played != dst.summary.stitches:
            result["errors"].append(f"preview_mismatch: preview={played} dst={dst.summary.stitches}")
        result["preview"] = preview

    result["ok"] = not result["errors"]
    return result


def write_viewer(results: list[dict], out: Path) -> None:
    payload = [
        {"fixture": r["fixture"], "ok": r["ok"], "errors": r["errors"], **r["preview"]}
        for r in results if "preview" in r
    ]
    html = VIEWER_TEMPLATE.read_text(encoding="utf-8")
    data = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    out.write_text(html.replace("/*__GATE_A_DATA__*/[]", data), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fixtures", type=Path, default=ROOT / "fixtures")
    parser.add_argument("--out", type=Path, default=ROOT / "out" / "gate-a")
    parser.add_argument("--only", nargs="*", help="fixture file names to run")
    args = parser.parse_args(argv)

    expected_all = json.loads((args.fixtures / "expected.json").read_text(encoding="utf-8"))
    svgs = sorted(args.fixtures.glob("fixture_*.svg"))
    if args.only:
        svgs = [s for s in svgs if s.name in set(args.only)]
    if not svgs:
        print("no fixtures found", file=sys.stderr)
        return 2

    results = []
    for svg in svgs:
        res = run_fixture(svg, args.out / svg.stem, expected_all.get(svg.name))
        results.append(res)
        s = (res.get("dst") or {}).get("summary") or {}
        status = "PASS" if res["ok"] else "FAIL"
        print(f"[{status}] {svg.name}: stitches={s.get('stitches')} "
              f"size={s.get('width_mm')}x{s.get('height_mm')}mm colors={s.get('color_blocks')} "
              f"jumps={s.get('jumps')} {'; '.join(res['errors'])}")

    args.out.mkdir(parents=True, exist_ok=True)
    report = [{k: v for k, v in r.items() if k != "preview"} for r in results]
    (args.out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_viewer(results, args.out / "preview.html")
    print(f"report: {args.out / 'report.json'}\npreview: {args.out / 'preview.html'}")
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
