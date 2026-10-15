"""Real Ink/Stitch run over the fixed fixtures. Runs only where INKSTITCH_CMD is set (worker image / CI)."""
import os
from pathlib import Path

import pytest

from services.worker import gate_a

pytestmark = pytest.mark.skipif(not os.environ.get("INKSTITCH_CMD"), reason="INKSTITCH_CMD not set")
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_all_fixtures_pass(tmp_path):
    assert gate_a.main(["--fixtures", str(FIXTURES), "--out", str(tmp_path)]) == 0
    assert (tmp_path / "preview.html").exists()
