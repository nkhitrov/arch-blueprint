from __future__ import annotations

import json
import shlex
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from arch_blueprint.analyze import analyze
from arch_blueprint.blueprint import build_graph
from arch_blueprint.domain.graph import BlueprintGraph
from arch_blueprint.extract import LINK_LEVELS
from arch_blueprint.extract.levels import module_level
from arch_blueprint.extract.module_extractor import ModuleExtractor
from arch_blueprint.extract.source import GrimpSource
from arch_blueprint.metrics import default_registry
from arch_blueprint.renderer.layout import Layout
from arch_blueprint.serve.fold import fold
from arch_blueprint.serve.view import (
    NoModulesError,
    ViewRequest,
    build_view,
    cli_command,
)
from tests.conftest import (
    ANCESTOR_DEP_PROJECT,
    CLASSES_PROJECT,
    CYCLIC_PROJECT,
    DEEP_PROJECT,
    EXAMPLE_PROJECT,
    INIT_IMPORTS_PROJECT,
    run_command,
)

EXAMPLE_ROOTS = ["app1.**", "app2.**", "plugins.**"]


def _modules(project: Path, patterns: Sequence[str]) -> BlueprintGraph:
    source = GrimpSource(str(project), patterns)
    return ModuleExtractor(source, level=module_level).extract()


def _ids(graph: BlueprintGraph) -> list[str]:
    return [node.id for node in graph.nodes]


def _pairs(graph: BlueprintGraph) -> set[tuple[str, str]]:
    return {(link.source, link.target) for link in graph.links}


def test_fold_nothing_is_identity() -> None:
    graph = _modules(EXAMPLE_PROJECT, EXAMPLE_ROOTS)
    folded = fold(graph, frozenset())
    assert _ids(folded) == _ids(graph)
    assert folded.edges == graph.edges
    assert folded.facade_edges == graph.facade_edges


def test_fold_root_keeps_cross_links() -> None:
    graph = _modules(EXAMPLE_PROJECT, EXAMPLE_ROOTS)
    folded = fold(graph, {"app1", "app2", "plugins"})
    assert _ids(folded) == ["app1", "app2", "plugins"]
    assert _pairs(folded) == {("app2", "app1"), ("app2", "plugins")}
    real = {(edge.source, edge.target) for edge in graph.edges}
    assert {(edge.source, edge.target) for edge in folded.edges} == real


def test_fold_unknown_prefix_ignored() -> None:
    graph = _modules(EXAMPLE_PROJECT, EXAMPLE_ROOTS)
    folded = fold(graph, {"nope", "app"})
    assert _ids(folded) == _ids(graph)
    assert folded.edges == graph.edges


def test_fold_nested_prefixes_take_the_outermost() -> None:
    graph = _modules(EXAMPLE_PROJECT, EXAMPLE_ROOTS)
    folded = fold(graph, {"plugins", "plugins.auth"})
    assert "plugins" in _ids(folded)
    assert "plugins.auth" not in _ids(folded)


def test_fold_matches_bare_selection() -> None:
    """A folded package draws what selecting it whole (``-m pkg``) draws."""
    graph = _modules(INIT_IMPORTS_PROJECT, ["writer.**", "storage.**"])
    folded = fold(graph, {"writer"})
    bare = _modules(INIT_IMPORTS_PROJECT, ["writer", "storage.**"])
    assert sorted(_ids(folded)) == sorted(_ids(bare))
    assert _pairs(folded) == _pairs(bare)
    assert ("writer", "storage.backend") in _pairs(folded)


def test_fold_keeps_arrow_on_facade() -> None:
    graph = _modules(ANCESTOR_DEP_PROJECT, ["api.**", "services.**"])
    assert ("api.handlers", "services") in _pairs(graph)
    assert ("api", "services") in _pairs(fold(graph, {"api"}))
    assert ("api.handlers", "services") in _pairs(fold(graph, {"services"}))


def test_fold_drops_imports_inside_the_folded_package() -> None:
    graph = _modules(ANCESTOR_DEP_PROJECT, ["api.**", "services.**"])
    folded = fold(graph, {"services"})
    assert all(link.source != link.target for link in folded.links)
    assert ("services", "services.engine") not in _pairs(folded)


def test_fold_cycle_between_folded_packages() -> None:
    graph = _modules(CYCLIC_PROJECT, ["pkg_a.**", "pkg_b.**"])
    folded = analyze(fold(graph, {"pkg_a", "pkg_b"}))
    assert [{cycle.endpoint_from, cycle.endpoint_to} for cycle in folded.cycles] == [
        {"pkg_a", "pkg_b"},
    ]


# --- build_view ---------------------------------------------------------------


def _view(
    project: Path,
    patterns: Sequence[str],
    folded: Sequence[str] = (),
    links: str = "module",
) -> dict[str, Any]:
    request = ViewRequest(tuple(patterns), frozenset(folded), links)
    return build_view(GrimpSource(str(project), patterns), request, default_registry())


def _view_pairs(view: dict[str, Any]) -> set[frozenset[str]]:
    pairs = {frozenset((link["source"], link["target"])) for link in view["links"]}
    return pairs | {frozenset((cycle["a"], cycle["b"])) for cycle in view["cycles"]}


def test_view_unfolded_matches_module_level() -> None:
    view = _view(CYCLIC_PROJECT, ["pkg_a.**", "pkg_b.**"])
    graph = build_graph(
        str(CYCLIC_PROJECT),
        ["pkg_a.**", "pkg_b.**"],
        LINK_LEVELS["module"].extractor,
    )
    assert _view_pairs(view) == {
        frozenset((link.source, link.target)) for link in graph.links
    }
    assert [{c["a"], c["b"]} for c in view["cycles"]] == [
        {c.endpoint_from, c.endpoint_to} for c in graph.cycles
    ]
    cyclic = {frozenset((c["a"], c["b"])) for c in view["cycles"]}
    assert not any(
        frozenset((link["source"], link["target"])) in cyclic for link in view["links"]
    )


def test_view_frames_nest() -> None:
    view = _view(DEEP_PROJECT, ["deep.**"])
    frames = {frame["id"]: frame for frame in view["frames"]}
    assert frames
    for item in [*view["nodes"], *view["frames"]]:
        assert item["parent"] is None or item["parent"] in frames
    ids = [node["id"] for node in view["nodes"]]
    ends = {end for link in view["links"] for end in (link["source"], link["target"])}
    layout = Layout.build(ids, ends, nested=True)
    assert {node["id"]: node["label"] for node in view["nodes"]} == {
        node_id: layout.label(node_id) for node_id in ids
    }
    assert ends <= set(ids) | set(frames)


def test_view_link_lists_imports() -> None:
    view = _view(EXAMPLE_PROJECT, EXAMPLE_ROOTS)
    imports = {tuple(pair) for link in view["links"] for pair in link["imports"]}
    assert ("app2.service", "app1.models") in imports
    assert all(link["metrics"]["edge_weight"] >= 1 for link in view["links"])


def test_view_folded_node_flagged() -> None:
    view = _view(EXAMPLE_PROJECT, EXAMPLE_ROOTS, folded=["app1"])
    flags = {node["id"]: node["folded"] for node in view["nodes"]}
    assert flags["app1"] is True
    assert flags["app2.service"] is False
    assert "fan_in" in view["metrics"]["node"]
    assert "depth" not in view["metrics"]["node"]


def test_view_class_level() -> None:
    view = _view(CLASSES_PROJECT, ["refs.**"], folded=["refs"], links="class")
    assert {node["kind"] for node in view["nodes"]} == {"C", "F"}


def test_view_no_modules() -> None:
    with pytest.raises(NoModulesError, match="no modules matched"):
        _view(EXAMPLE_PROJECT, ["app1.nothing.*"])


def test_cli_command_roundtrip() -> None:
    request = ViewRequest(("app1.**", "app2.**", "plugins.**"))
    command = cli_command(str(EXAMPLE_PROJECT), request, "fan_in")
    args = shlex.split(command)
    assert args[:2] == ["arch-blueprint", "draw"]
    assert args[-2:] == ["--metric", "fan_in"]
    snapshot = run_command(*args[1:-2], "-f", "json").stdout
    nodes = {node["id"] for node in json.loads(snapshot)["nodes"]}
    view = _view(EXAMPLE_PROJECT, EXAMPLE_ROOTS)
    assert nodes == {node["id"] for node in view["nodes"]}


def test_cli_command_class_level_is_grouped() -> None:
    command = cli_command("src", ViewRequest(("refs.**",), links="class"), None)
    assert command == "arch-blueprint draw src -m 'refs.**' --links class-grouped"


def test_cli_command_folded_note() -> None:
    request = ViewRequest(("app1.**",), frozenset({"app1"}))
    first, second = cli_command("src", request, None).splitlines()
    assert first == "# folded packages have no CLI equivalent; this draws them unfolded"
    assert second.startswith("arch-blueprint draw src")


@pytest.mark.parametrize(
    "data",
    [
        {"patterns": "app1.**"},
        {"patterns": ["app1.**"], "links": "namespace"},
        {"patterns": ["app1.**"], "folded": "app1"},
        {"patterns": []},
        {},
    ],
)
def test_request_from_json_rejects(data: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        ViewRequest.from_json(data)


def test_request_from_json() -> None:
    request = ViewRequest.from_json(
        {"patterns": ["a.**"], "folded": ["a.b"], "links": "class"},
    )
    assert request == ViewRequest(("a.**",), frozenset({"a.b"}), "class")
