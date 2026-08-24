from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from tests.conftest import SCENARIOS, golden_path

_PLANTUML = shutil.which("plantuml")

#: ``plantuml -checkonly`` exits 0 when every diagram it was given parses.
_SYNTAX_OK = 0


def _check(paths: list[Path]) -> subprocess.CompletedProcess[str]:
    """Parse-check diagrams without generating images.

    ``-checkonly`` takes file arguments, so every golden goes through a single
    invocation — each JVM start costs more than a second. It is used in
    preference to ``-syntax``, which reads stdin and whose behaviour differs
    between the distro builds this runs on.
    """
    return subprocess.run(
        [str(_PLANTUML), "-checkonly", *(str(p) for p in paths)],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.skipif(_PLANTUML is None, reason="plantuml binary not installed")
def test_puml_goldens_are_parseable() -> None:
    """Every stored PlantUML golden must be a diagram PlantUML can actually parse.

    Byte-comparison alone cannot tell a valid diagram from a broken one — it only
    pins whatever the renderer currently emits.
    """
    goldens = [golden_path("puml", scenario.name) for scenario in SCENARIOS]
    if _check(goldens).returncode == _SYNTAX_OK:
        return

    # Slow path only: re-check one at a time to name the offenders.
    broken = {}
    for golden in goldens:
        result = _check([golden])
        if result.returncode != _SYNTAX_OK:
            broken[golden.name] = (result.stdout + result.stderr).strip()
    pytest.fail(f"plantuml rejected {len(broken)} golden(s): {broken}")
