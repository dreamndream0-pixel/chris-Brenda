"""Stand-in for the Ink/Stitch CLI in unit tests.

argv: fake_inkstitch.py <mode> <payload> [ink/stitch args...]
  mode=zip    -> write <payload> (a ZIP file) to stdout
  mode=sleep  -> sleep <payload> seconds
  mode=fail   -> print to stderr and exit 3
"""
import sys
import time

mode, payload = sys.argv[1], sys.argv[2]
if mode == "zip":
    with open(payload, "rb") as f:
        sys.stdout.buffer.write(f.read())
elif mode == "sleep":
    time.sleep(float(payload))
elif mode == "fail":
    print("Traceback: boom", file=sys.stderr)
    sys.exit(3)
