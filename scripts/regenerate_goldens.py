"""Rewrite every golden from the CLI's current output.

Run after an *intentional* change to what the renderers emit. Running it twice
must leave the tree clean: if the second run produces a diff, the output is not
deterministic and that is the bug to fix first.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tests.conftest import SCENARIOS, golden_path  # noqa: E402

FORMATS = ("puml", "d2")


def regenerate() -> int:
    """Write every scenario in every format; return how many files were written."""
    written = 0
    for scenario in SCENARIOS:
        for fmt in FORMATS:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "arch_blueprint",
                    str(scenario.project),
                    *scenario.args,
                    "-f",
                    fmt,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=True,
                cwd=REPO_ROOT,
            )
            golden_path(fmt, scenario.name).write_text(
                result.stdout,
                encoding="utf-8",
            )
            written += 1
    return written


if __name__ == "__main__":
    count = regenerate()
    sys.stdout.write(f"regenerated {count} goldens\n")
