import shutil
import subprocess
from pathlib import Path

import pytest


def test_frontend_state_regressions():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is required for frontend state regressions')
    result = subprocess.run(
        [node, '--test', str(Path(__file__).with_name('frontend_state.test.cjs')),
         str(Path(__file__).with_name('autotrack_state.test.cjs')),
         str(Path(__file__).with_name('metro_usability.test.cjs'))],
        capture_output=True, text=True, encoding='utf-8', timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
