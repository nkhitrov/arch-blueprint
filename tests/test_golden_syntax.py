from __future__ import annotations

import shutil
import subprocess

import pytest

from tests.conftest import SCENARIOS, golden_path

_PLANTUML = shutil.which("plantuml")

#: ``plantuml -syntax`` exits 0 when every diagram on stdin parses.
_SYNTAX_OK = 0


def _syntax_check(diagrams: str) -> subprocess.CompletedProcess[str]:
    """Parse-check one or more concatenated diagrams.

    ``-syntax`` reads stdin and ignores file arguments, so every diagram is fed
    through a single invocation — each JVM start costs more than a second.
    """
    return subprocess.run(
        [str(_PLANTUML), "-syntax"],
        input=diagrams,
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
    sources = {
        scenario.name: golden_path("puml", scenario.name).read_text(encoding="utf-8")
        for scenario in SCENARIOS
    }
    if _syntax_check("".join(sources.values())).returncode == _SYNTAX_OK:
        return

    # Slow path only: re-check one at a time to name the offenders.
    broken = {}
    for name, source in sources.items():
        result = _syntax_check(source)
        if result.returncode != _SYNTAX_OK:
            broken[name] = result.stdout.strip()
    pytest.fail(f"plantuml rejected {len(broken)} golden(s): {broken}")
