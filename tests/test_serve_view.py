from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from arch_blueprint.analyze import analyze
from arch_blueprint.domain.graph import BlueprintGraph
from arch_blueprint.extract.levels import module_level
from arch_blueprint.extract.module_extractor import ModuleExtractor
from arch_blueprint.extract.source import GrimpSource
from arch_blueprint.serve.fold import fold
from tests.conftest import (
    ANCESTOR_DEP_PROJECT,
    CYCLIC_PROJECT,
    EXAMPLE_PROJECT,
    INIT_IMPORTS_PROJECT,
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
