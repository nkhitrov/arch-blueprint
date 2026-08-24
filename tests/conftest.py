from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
EXAMPLE_PROJECT = REPO_ROOT / "examples" / "project_root"
_FIXTURES = Path(__file__).resolve().parent / "fixtures"
CYCLIC_PROJECT = _FIXTURES / "cyclic"
DEEP_PROJECT = _FIXTURES / "deep_ns"

EXAMPLE_MODULES = ["-m", "app1.*", "-m", "app2.*", "-m", "plugins.**"]
CYCLIC_MODULES = ["-m", "pkg_a.*", "-m", "pkg_b.*"]
SHOW_METRICS = ["--metric", "fan_in", "--metric", "fan_out", "--metric", "instability"]
SHOW_LINK_METRIC = ["--metric", "edge_weight"]
DEEP_MODULES = ["-m", "deep.**"]
# Deliberately not the order metrics are registered in ``default_registry`` — this pins
# that metric blocks follow CLI argument order, which ``SHOW_METRICS`` cannot detect
# because it happens to match registration order.
SHOW_METRICS_REORDERED = [
    "--metric",
    "instability",
    "--metric",
    "fan_out",
    "--metric",
    "fan_in",
]


@dataclass(frozen=True)
class Scenario:
    """A format-agnostic CLI scenario shared by every renderer's golden tests.

    The golden file for a scenario lives at ``golden/<fmt>/<name>.<fmt>`` and is
    produced by appending ``-f <fmt>`` to ``args``.
    """

    name: str
    project: Path
    args: list[str] = field(default_factory=list)


SCENARIOS = [
    Scenario("example", EXAMPLE_PROJECT, EXAMPLE_MODULES),
    Scenario("cyclic", CYCLIC_PROJECT, CYCLIC_MODULES),
    Scenario(
        "cyclic_nodetails", CYCLIC_PROJECT, [*CYCLIC_MODULES, "--no-cycle-details"]
    ),
    Scenario("metrics", CYCLIC_PROJECT, [*CYCLIC_MODULES, *SHOW_METRICS]),
    Scenario("link_metrics", EXAMPLE_PROJECT, [*EXAMPLE_MODULES, *SHOW_LINK_METRIC]),
    Scenario(
        "metrics_reordered",
        CYCLIC_PROJECT,
        [*CYCLIC_MODULES, *SHOW_METRICS_REORDERED],
    ),
    # Single root with deep namespaces: link endpoints collide byte-for-byte with node
    # ids and nest inside one another — the two cases that break naive grouping.
    Scenario("deep", DEEP_PROJECT, DEEP_MODULES),
]


def golden_path(fmt: str, name: str) -> Path:
    """Path to the golden output for a scenario in a given format."""
    return GOLDEN_DIR / fmt / f"{name}.{fmt}"


def run_cli(project_dir: Path, *args: str) -> str:
    """Run the arch-blueprint CLI end-to-end and return stdout.

    Invoked as a subprocess so each render is isolated from sys.path / import
    cache side effects that ``ArchBlueprint.run`` produces.
    """
    result = subprocess.run(
        [sys.executable, "-m", "arch_blueprint", str(project_dir), *args],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO_ROOT,
    )
    return result.stdout


def assert_scenario_matches_golden(scenario: Scenario, fmt: str) -> None:
    """Render ``scenario`` in ``fmt`` and assert it equals the stored golden."""
    expected = golden_path(fmt, scenario.name).read_text()
    actual = run_cli(scenario.project, *scenario.args, "-f", fmt)
    assert actual == expected
