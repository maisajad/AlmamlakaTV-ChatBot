import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "static"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
@pytest.mark.parametrize("script", sorted(p.name for p in STATIC.glob("*.js")))
def test_front_end_scripts_parse(script):
    """A syntax error in one script silently disables everything it defines."""
    result = subprocess.run(["node", "--check", str(STATIC / script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
