from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from arch_blueprint.domain.graph import BlueprintGraph, Edge
from arch_blueprint.domain.node import Node, NodeKind

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
EXAMPLE_PROJECT = REPO_ROOT / "examples" / "project_root"
_FIXTURES = Path(__file__).resolve().parent / "fixtures"
CYCLIC_PROJECT = _FIXTURES / "cyclic"
DEEP_PROJECT = _FIXTURES / "deep_ns"
INIT_IMPORTS_PROJECT = _FIXTURES / "init_imports"
ANCESTOR_DEP_PROJECT = _FIXTURES / "ancestor_dep"

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
        "cyclic_nodetails",
        CYCLIC_PROJECT,
        [*CYCLIC_MODULES, "--no-cycle-details"],
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
    # A link metric on a connection that is a cycle: two directions, two values.
    Scenario(
        "cyclic_link_metrics",
        CYCLIC_PROJECT,
        [*CYCLIC_MODULES, *SHOW_LINK_METRIC],
    ),
]


def golden_path(fmt: str, name: str) -> Path:
    """Path to the golden output for a scenario in a given format."""
    return GOLDEN_DIR / fmt / f"{name}.{fmt}"


@dataclass(frozen=True)
class CliResult:
    """What a CLI run produced. stderr is kept: warnings are behaviour too."""

    stdout: str
    stderr: str
    returncode: int


def run_cli(
    project_dir: Path,
    *args: str,
    check: bool = True,
    extra_env: Optional[dict[str, str]] = None,
) -> CliResult:
    """Run the arch-blueprint CLI end-to-end.

    Invoked as a subprocess so a run is isolated from whatever the CLI does to
    the interpreter, and decoded as UTF-8 explicitly so the assertions do not
    depend on the machine's locale — diagram output contains arrows.
    """
    result = subprocess.run(
        [sys.executable, "-m", "arch_blueprint", str(project_dir), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=check,
        cwd=REPO_ROOT,
        env={**os.environ, **extra_env} if extra_env else None,
    )
    return CliResult(
        stdout=result.stdout,
        stderr=result.stderr,
        returncode=result.returncode,
    )


def assert_scenario_matches_golden(scenario: Scenario, fmt: str) -> None:
    """Render ``scenario`` in ``fmt`` and assert it equals the stored golden."""
    expected = golden_path(fmt, scenario.name).read_text(encoding="utf-8")
    actual = run_cli(scenario.project, *scenario.args, "-f", fmt)
    assert actual.stdout == expected


def make_edge(source: str, target: str, src_ns: str, tgt_ns: str) -> Edge:
    """Build an Edge without repeating four keyword arguments in every test."""
    return Edge(
        source=source,
        target=target,
        source_namespace=src_ns,
        target_namespace=tgt_ns,
    )


def make_graph(node_ids: Iterable[str], edges: Iterable[Edge]) -> BlueprintGraph:
    """A graph of MODULE nodes, for tests that do not need a real project."""
    return BlueprintGraph(
        nodes=[Node(id=node_id, kind=NodeKind.MODULE) for node_id in node_ids],
        edges=frozenset(edges),
    )
