"""What the D2 compiler makes of our goldens, not just what they say.

Byte-exact goldens prove the text we emit; they cannot see a box drawn smaller
than the text inside it. D2 0.9 sizes a markdown block about 17px short, which
silently cut the last legend row from every rendered diagram while the source
held it in full. Skipped when the ``d2`` binary is absent — most runs, CI's
included — so it is a guard for whoever has it, not a dependency.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.conftest import GOLDEN_DIR

_D2 = shutil.which("d2")

#: A rendered markdown box: its size, then the text D2 laid out inside it.
_MD_BLOCK = re.compile(
    r'<rect width="([\d.]+)" height="([\d.]+)"[^>]*/>\s*<g class="md[^"]*">(.*?)</g>',
    re.S,
)
_TEXT_Y = re.compile(r'<text[^>]*y="([\d.]+)"')

_GOLDENS = sorted(GOLDEN_DIR.glob("d2/*.d2")) + sorted(GOLDEN_DIR.glob("diff/d2/*.d2"))


@pytest.mark.skipif(_D2 is None, reason="the d2 binary is not installed")
@pytest.mark.parametrize("golden", _GOLDENS, ids=lambda p: p.stem)
def test_every_markdown_block_fits_the_box_d2_drew_for_it(golden: Path) -> None:
    rendered = subprocess.run(
        [str(_D2), str(golden), "-"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    for block in _MD_BLOCK.finditer(rendered):
        height = float(block.group(2))
        baselines = [float(y) for y in _TEXT_Y.findall(block.group(3))]
        if not baselines:
            continue
        assert max(baselines) <= height, (
            f"{golden.name}: text reaches y={max(baselines):.0f} in a box "
            f"{height:.0f} tall — the bottom row is cut from the render"
        )
