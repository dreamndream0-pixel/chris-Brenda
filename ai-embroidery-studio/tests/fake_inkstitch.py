"""Stand-in for the Ink/Stitch CLI in unit tests.

argv: fake_inkstitch.py <mode> <payload> [ink/stitch args...]
  mode=zip    -> write <payload> (a ZIP file) to stdout
  mode=sleep  -> sleep <payload> seconds
  mode=fail   -> print to stderr and exit 3
  mode=auto   -> read the SVG (last argv) and emit a ZIP whose DST/PES span its mm size,
                 one colour block per distinct path colour
"""
import sys
import time

mode, payload = sys.argv[1], sys.argv[2]
if mode == "zip":
    with open(payload, "rb") as f:
        sys.stdout.buffer.write(f.read())
elif mode == "sleep":
    time.sleep(float(payload))
elif mode == "auto":
    import io
    import re
    import zipfile

    import pyembroidery as pe

    from svgelements import Matrix, Path

    svg = open(sys.argv[-1], encoding="utf-8").read()
    m = re.search(r'transform="matrix\(([^)]*)\)"', svg)
    matrix = Matrix(f"matrix({m.group(1)})") if m else Matrix()
    boxes = [(Path(d) * matrix).bbox() for d in re.findall(r' d="([^"]+)"', svg)]
    x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    w, h = max(b[2] for b in boxes) - x0, max(b[3] for b in boxes) - y0
    colors = []
    for c in re.findall(r"(?:fill|stroke):(#[0-9a-f]{6})", svg):
        if not colors or colors[-1] != c:
            colors.append(c)
    p = pe.EmbPattern()
    for i, c in enumerate(colors):
        p.add_thread(pe.EmbThread(c))
        if i:
            p.add_command(pe.COLOR_CHANGE)
        y = 0.0
        while y <= h * 10:
            for x in range(0, int(w * 10) + 1, 30):
                p.add_stitch_absolute(pe.STITCH, x, y)
            p.add_stitch_absolute(pe.STITCH, w * 10, y)
            y += 20
    p.add_command(pe.END)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for ext in ("dst", "pes"):
            path = f"fake.{ext}"  # cwd is the engine's per-job directory
            pe.write(p, path)
            z.write(path, f"design.{ext}")
        z.writestr("design_threadlist.txt", "fake threadlist\n")
    sys.stdout.buffer.write(buf.getvalue())
elif mode == "fail":
    print("Traceback: boom", file=sys.stderr)
    sys.exit(3)
