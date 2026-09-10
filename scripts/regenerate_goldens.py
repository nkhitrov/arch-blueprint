"""Rewrite every golden from the CLI's current output.

Run after an *intentional* change to what the CLI emits. Running it twice must
leave the tree clean: if the second run produces a diff, the output is not
deterministic and that is the bug to fix first.

Three families, because three things are pinned: the diagrams of every scenario,
the snapshot of every selection, and the diff of every diff case.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tests.conftest import (  # noqa: E402
    DIFF_CASES,
    SCENARIOS,
    SELECTIONS,
    diff_golden_path,
    golden_path,
    snapshot_path,
)

FORMATS = ("puml", "d2")

#: ``diff`` exits 1 when the two sides differ, which is an answer, not a failure.
_DIFF_EXIT_CODES = (0, 1)


def _cli(*args: str, allowed: tuple[int, ...] = (0,)) -> str:
    result = subprocess.run(
        [sys.executable, "-m", "arch_blueprint", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        cwd=REPO_ROOT,
    )
    if result.returncode not in allowed:
        message = f"{' '.join(args)} exited {result.returncode}\n{result.stderr}"
        raise SystemExit(message)
    return result.stdout


def regenerate() -> int:
    """Write every golden there is; return how many files were written."""
    written = 0
    for selection in SELECTIONS:
        text = _cli(str(selection.project), *selection.modules, "-f", "json")
        snapshot_path(selection.name).write_text(text, encoding="utf-8")
        written += 1
    for scenario in SCENARIOS:
        for fmt in FORMATS:
            text = _cli(str(scenario.project), *scenario.args, "-f", fmt)
            golden_path(fmt, scenario.name).write_text(text, encoding="utf-8")
            written += 1
    for case in DIFF_CASES:
        for fmt in FORMATS:
            text = _cli(
                "diff",
                str(case.old),
                str(case.new),
                *case.args,
                "-f",
                fmt,
                allowed=_DIFF_EXIT_CODES,
            )
            diff_golden_path(fmt, case.name).write_text(text, encoding="utf-8")
            written += 1
    return written


if __name__ == "__main__":
    count = regenerate()
    sys.stdout.write(f"regenerated {count} goldens\n")
