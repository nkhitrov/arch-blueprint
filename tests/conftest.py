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
TANGLE_PROJECT = _FIXTURES / "tangle"

INIT_IMPORTS_MODULES = ["-m", "writer", "-m", "storage.*"]
ANCESTOR_DEP_MODULES = ["-m", "api.*", "-m", "services.*"]
TANGLE_MODULES = ["-m", "api.*", "-m", "services.*", "-m", "ring.*", "-m", "nest.*"]

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
    """What to graph: a project, its ``-m`` patterns and ``--links`` level.

    One snapshot golden each; ``build_args`` are the options that shape the
    graph itself, so ``render`` never takes them.

    Its snapshot lives at ``golden/json/<name>.json``; every scenario drawn from
    the same selection renders from that one snapshot.
    """

    name: str
    project: Path
    modules: list[str]
    build_args: list[str] = field(default_factory=list)

    @property
    def args(self) -> list[str]:
        return [*self.modules, *self.build_args]


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

# The same projects linked node to node: every arrow ends on a declared node, a
# cycle is between two modules, and a package facade stays a container.
MODULE_LINKS = ["--links", "module"]
EXAMPLE_MODULE_LINKS = Selection(
    "example_module_links",
    EXAMPLE_PROJECT,
    EXAMPLE_MODULES,
    MODULE_LINKS,
)
CYCLIC_MODULE_LINKS = Selection(
    "cyclic_module_links",
    CYCLIC_PROJECT,
    CYCLIC_MODULES,
    MODULE_LINKS,
)
DEEP_MODULE_LINKS = Selection(
    "deep_module_links",
    DEEP_PROJECT,
    DEEP_MODULES,
    MODULE_LINKS,
)
ANCESTOR_DEP_MODULE_LINKS = Selection(
    "ancestor_dep_module_links",
    ANCESTOR_DEP_PROJECT,
    ANCESTOR_DEP_MODULES,
    MODULE_LINKS,
)

# Longer cycles: a ring of three modules, a cycle closed only by a package
# facade's own imports (found, not drawn), and a pair through a nested package.
TANGLE = Selection("tangle", TANGLE_PROJECT, TANGLE_MODULES)
TANGLE_MODULE_LINKS = Selection(
    "tangle_module_links",
    TANGLE_PROJECT,
    TANGLE_MODULES,
    MODULE_LINKS,
)
# Package nodes at the module level: every import lands inside a node.
DEEP_PACKAGES_MODULE_LINKS = Selection(
    "deep_packages_module_links",
    DEEP_PROJECT,
    ["-m", "deep.*"],
    MODULE_LINKS,
)

SELECTIONS = [
    EXAMPLE,
    CYCLIC,
    DEEP,
    INIT_IMPORTS,
    ANCESTOR_DEP,
    EXAMPLE_MODULE_LINKS,
    CYCLIC_MODULE_LINKS,
    DEEP_MODULE_LINKS,
    ANCESTOR_DEP_MODULE_LINKS,
    TANGLE,
    TANGLE_MODULE_LINKS,
    DEEP_PACKAGES_MODULE_LINKS,
]


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
        return [*self.selection.args, *self.render_args]


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
    Scenario("example_module_links", EXAMPLE_MODULE_LINKS),
    Scenario("cyclic_module_links", CYCLIC_MODULE_LINKS),
    Scenario("cyclic_module_links_metrics", CYCLIC_MODULE_LINKS, SHOW_LINK_METRIC),
    Scenario("deep_module_links", DEEP_MODULE_LINKS),
    Scenario("ancestor_dep_module_links", ANCESTOR_DEP_MODULE_LINKS),
    Scenario("tangle", TANGLE),
    Scenario("tangle_module_links", TANGLE_MODULE_LINKS),
    Scenario("tangle_nodetails", TANGLE_MODULE_LINKS, ["--no-cycle-details"]),
    Scenario("deep_packages_module_links", DEEP_PACKAGES_MODULE_LINKS),
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
    args: tuple[str, ...] = ()


DIFF_CASES = [
    # Removed module with its link, added module with its link, drawn over the
    # rest of the graph as a plain diagram shows it.
    DiffCase(
        "changes",
        GOLDEN_DIR / "json" / "example.json",
        _DIFF_FIXTURES / "example_changed.json",
    ),
    # The same with --changes-only: unchanged links hidden, and only the
    # unchanged modules the changed links touch shown.
    DiffCase(
        "changes_only",
        GOLDEN_DIR / "json" / "example.json",
        _DIFF_FIXTURES / "example_changed.json",
        ("--changes-only",),
    ),
    DiffCase(
        "new_cycle",
        _DIFF_FIXTURES / "cyclic_one_way.json",
        GOLDEN_DIR / "json" / "cyclic.json",
    ),
    # The import notes are opt-in for a diff: pinned once, on the new cycle.
    DiffCase(
        "new_cycle_details",
        _DIFF_FIXTURES / "cyclic_one_way.json",
        GOLDEN_DIR / "json" / "cyclic.json",
        ("--cycle-details",),
    ),
    DiffCase(
        "new_cycle_changes_only",
        _DIFF_FIXTURES / "cyclic_one_way.json",
        GOLDEN_DIR / "json" / "cyclic.json",
        ("--changes-only",),
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
    # A ring of three closed by one new import: a new longer cycle, marked on
    # every link of it, with the notes on request.
    DiffCase(
        "new_tangle",
        _DIFF_FIXTURES / "tangle_open_ring.json",
        GOLDEN_DIR / "json" / "tangle_module_links.json",
        ("--cycle-details",),
    ),
    DiffCase(
        "resolved_tangle",
        GOLDEN_DIR / "json" / "tangle_module_links.json",
        _DIFF_FIXTURES / "tangle_open_ring.json",
    ),
    # Only a facade's own imports changed: no drawn link did, yet a cycle
    # appeared, so the diff is not empty.
    DiffCase(
        "facade_closes_cycle",
        _DIFF_FIXTURES / "tangle_no_facade_import.json",
        GOLDEN_DIR / "json" / "tangle_module_links.json",
        ("--changes-only",),
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


def make_edge(source: str, target: str, src: str, tgt: str) -> Edge:
    """Build an Edge without repeating four keyword arguments in every test."""
    return Edge(
        source=source,
        target=target,
        source_endpoint=src,
        target_endpoint=tgt,
    )


def make_graph(node_ids: Iterable[str], edges: Iterable[Edge]) -> BlueprintGraph:
    """A graph of MODULE nodes, for tests that do not need a real project."""
    return BlueprintGraph(
        nodes=[Node(id=node_id, kind=NodeKind.MODULE) for node_id in node_ids],
        edges=frozenset(edges),
    )
