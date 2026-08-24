from __future__ import annotations

import sys
from pathlib import Path

import pytest

from arch_blueprint.analyze.cycles import CycleAnalyzer
from arch_blueprint.domain.node import NodeKind
from arch_blueprint.extract.base import common_depth_namespaces
from arch_blueprint.extract.module_extractor import ModuleExtractor
from arch_blueprint.extract.source import GrimpSource
from tests.conftest import (
    ANCESTOR_DEP_PROJECT,
    CYCLIC_PROJECT,
    EXAMPLE_PROJECT,
    INIT_IMPORTS_PROJECT,
)


def _edges_of(project: Path, patterns: list[str]) -> set[tuple[str, str]]:
    source = GrimpSource(str(project), patterns)
    graph = ModuleExtractor(source).extract()
    return {(edge.source, edge.target) for edge in graph.edges}


# --- naming helpers -------------------------------------------------------


def test_common_depth_namespaces() -> None:
    assert common_depth_namespaces("app2.service", "app1.models") == ("app2", "app1")
    assert common_depth_namespaces("a.b.c", "a.b.d") == ("a.b.c", "a.b.d")
    assert common_depth_namespaces("a.b", "a.c") == ("a.b", "a.c")


# --- interpreter state ----------------------------------------------------


def test_source_restores_sys_path() -> None:
    before = list(sys.path)
    GrimpSource(str(CYCLIC_PROJECT), ["pkg_a.*"]).selected_modules()
    assert sys.path == before


def test_source_leaves_no_modules_behind() -> None:
    """Restoring sys.path is not enough: sys.modules is consulted first."""
    before = set(sys.modules)
    GrimpSource(str(CYCLIC_PROJECT), ["pkg_a.*"]).selected_modules()
    assert set(sys.modules) - before == set()


def test_two_projects_in_one_process() -> None:
    """A leaked module would make the second project resolve to the first."""
    cyclic = GrimpSource(str(CYCLIC_PROJECT), ["pkg_a.*"]).selected_modules()
    example = GrimpSource(str(EXAMPLE_PROJECT), ["app1.*"]).selected_modules()
    assert cyclic == ["pkg_a.core", "pkg_a.services"]
    assert example == ["app1.models"]


# --- package resolution ---------------------------------------------------


def test_namespace_package_is_expanded() -> None:
    """PEP 420 packages cannot be graphed directly; grimp gets the real ones."""
    source = GrimpSource(str(EXAMPLE_PROJECT), ["plugins.**"])
    assert source.selected_modules() == ["plugins.auth.backend"]


def test_unresolvable_pattern_is_rejected() -> None:
    source = GrimpSource(str(CYCLIC_PROJECT), ["no_such_package.*"])
    with pytest.raises(ImportError, match="no_such_package"):
        source.selected_modules()


def test_namespace_package_without_source_warns(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "hollow" / "inner").mkdir(parents=True)
    sys.path.append(str(tmp_path))
    try:
        assert GrimpSource._expand_to_graphable("hollow") == []
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("hollow", None)
    assert "no analyzable source" in capsys.readouterr().err


# --- extraction -----------------------------------------------------------


def test_module_extractor_builds_cycle() -> None:
    source = GrimpSource(str(CYCLIC_PROJECT), ["pkg_a.*", "pkg_b.*"])
    graph = ModuleExtractor(source).extract()
    ids = {node.id for node in graph.nodes}
    assert ids == {"pkg_a.core", "pkg_a.services", "pkg_b.util"}
    assert all(node.kind is NodeKind.MODULE for node in graph.nodes)
    assert len(CycleAnalyzer.detect_cycles(graph.links)) == 1


def test_package_init_imports_become_edges() -> None:
    """``writer/__init__.py`` imports storage.backend; ``writer`` has a submodule."""
    edges = _edges_of(INIT_IMPORTS_PROJECT, ["writer", "storage.*"])
    assert ("writer", "storage.backend") in edges


def test_import_of_package_facade_becomes_edge() -> None:
    """``api.handlers`` imports the ``services`` package, whose child is selected."""
    edges = _edges_of(ANCESTOR_DEP_PROJECT, ["api.*", "services.*"])
    assert ("api.handlers", "services") in edges
