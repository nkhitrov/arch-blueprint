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

INIT_IMPORTS_MODULES = ["-m", "writer", "-m", "storage.*"]
ANCESTOR_DEP_MODULES = ["-m", "api.*", "-m", "services.*"]

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
class Selection:
    """What to graph: a project and its ``-m`` patterns — one snapshot golden each.

    Its snapshot lives at ``golden/json/<name>.json``; every scenario drawn from
    the same selection renders from that one snapshot.
    """

    name: str
    project: Path
    modules: list[str]


EXAMPLE = Selection("example", EXAMPLE_PROJECT, EXAMPLE_MODULES)
CYCLIC = Selection("cyclic", CYCLIC_PROJECT, CYCLIC_MODULES)
# Single root with deep namespaces: link endpoints collide byte-for-byte with node
# ids and nest inside one another — the two cases that break naive grouping.
DEEP = Selection("deep", DEEP_PROJECT, DEEP_MODULES)
# A package whose __init__.py imports a sibling: the edge exists only if a
# module's own imports survive alongside its descendants'.
INIT_IMPORTS = Selection("init_imports", INIT_IMPORTS_PROJECT, INIT_IMPORTS_MODULES)
# An import of a package facade whose children are selected: the edge exists
# only if selection matches upward as well as down.
ANCESTOR_DEP = Selection("ancestor_dep", ANCESTOR_DEP_PROJECT, ANCESTOR_DEP_MODULES)

SELECTIONS = [EXAMPLE, CYCLIC, DEEP, INIT_IMPORTS, ANCESTOR_DEP]


@dataclass(frozen=True)
class Scenario:
    """A format-agnostic CLI scenario shared by every renderer's golden tests.

    The golden file for a scenario lives at ``golden/<fmt>/<name>.<fmt>`` and is
    produced by appending ``-f <fmt>`` to ``args``. ``render_args`` are the
    options that apply to drawing only, so they apply unchanged to ``render``.
    """

    name: str
    selection: Selection
    render_args: list[str] = field(default_factory=list)

    @property
    def project(self) -> Path:
        return self.selection.project

    @property
    def args(self) -> list[str]:
        return [*self.selection.modules, *self.render_args]


SCENARIOS = [
    Scenario("example", EXAMPLE),
    Scenario("cyclic", CYCLIC),
    Scenario("cyclic_nodetails", CYCLIC, ["--no-cycle-details"]),
    Scenario("metrics", CYCLIC, SHOW_METRICS),
    Scenario("link_metrics", EXAMPLE, SHOW_LINK_METRIC),
    Scenario("metrics_reordered", CYCLIC, SHOW_METRICS_REORDERED),
    Scenario("deep", DEEP),
    # A link metric on a connection that is a cycle: two directions, two values.
    Scenario("cyclic_link_metrics", CYCLIC, SHOW_LINK_METRIC),
    Scenario("init_imports", INIT_IMPORTS),
    Scenario("ancestor_dep", ANCESTOR_DEP),
]


_DIFF_FIXTURES = _FIXTURES / "diff"


@dataclass(frozen=True)
class DiffCase:
    """Two snapshots and the diff between them, pinned per format.

    The golden lives at ``golden/diff/<fmt>/<name>.<fmt>``. The inputs are
    golden snapshots or small edits of them under ``fixtures/diff``.
    """

    name: str
    old: Path
    new: Path


DIFF_CASES = [
    # Removed module with its link, added module with its link, one unchanged
    # link hidden, and the unchanged module the new link points at as context.
    DiffCase(
        "changes",
        GOLDEN_DIR / "json" / "example.json",
        _DIFF_FIXTURES / "example_changed.json",
    ),
    DiffCase(
        "new_cycle",
        _DIFF_FIXTURES / "cyclic_one_way.json",
        GOLDEN_DIR / "json" / "cyclic.json",
    ),
    DiffCase(
        "resolved_cycle",
        GOLDEN_DIR / "json" / "cyclic.json",
        _DIFF_FIXTURES / "cyclic_one_way.json",
    ),
    # Nested namespaces: the changed link's endpoints need containers.
    DiffCase(
        "nested",
        _DIFF_FIXTURES / "deep_unlinked.json",
        GOLDEN_DIR / "json" / "deep.json",
    ),
    DiffCase(
        "no_changes",
        GOLDEN_DIR / "json" / "example.json",
        GOLDEN_DIR / "json" / "example.json",
    ),
]


def golden_path(fmt: str, name: str) -> Path:
    """Path to the golden output for a scenario in a given format."""
    return GOLDEN_DIR / fmt / f"{name}.{fmt}"


def diff_golden_path(fmt: str, name: str) -> Path:
    """Path to the golden diff output for a diff case in a given format."""
    return GOLDEN_DIR / "diff" / fmt / f"{name}.{fmt}"


def snapshot_path(name: str) -> Path:
    """Path to the golden snapshot of a selection."""
    return GOLDEN_DIR / "json" / f"{name}.json"


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
    """Run the arch-blueprint CLI end-to-end on a project directory."""
    return run_command(str(project_dir), *args, check=check, extra_env=extra_env)


def run_command(
    *args: str,
    check: bool = True,
    extra_env: Optional[dict[str, str]] = None,
    cwd: Optional[Path] = None,
) -> CliResult:
    """Run the arch-blueprint CLI with arbitrary arguments (subcommands too).

    Invoked as a subprocess so a run is isolated from whatever the CLI does to
    the interpreter, and decoded as UTF-8 explicitly so the assertions do not
    depend on the machine's locale — diagram output contains arrows.
    """
    result = subprocess.run(
        [sys.executable, "-m", "arch_blueprint", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=check,
        cwd=cwd or REPO_ROOT,
        env={**os.environ, **extra_env} if extra_env else None,
    )
    return CliResult(
        stdout=result.stdout,
        stderr=result.stderr,
        returncode=result.returncode,
    )


def git(repo: Path, *args: str) -> None:
    """Run git in ``repo`` as a throwaway identity, failing the test on error."""
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],  # noqa: S607
        cwd=repo,
        check=True,
        capture_output=True,
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
