from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

from arch_blueprint.analyze.cycles import CycleAnalyzer
from arch_blueprint.domain.node import NodeKind
from arch_blueprint.extract.base import common_depth_namespaces
from arch_blueprint.extract.layout import detect_roots
from arch_blueprint.extract.levels import module_level, namespace_level
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


_NODES = frozenset({"a.b.c", "a.d", "x.y.z"})


@pytest.mark.parametrize(
    ("source", "target", "expected"),
    [
        pytest.param("a.b.c", "a.d.e", ("a.b", "a.d"), id="diverging_paths"),
        pytest.param("a.b.c", "a.b", None, id="own_package"),
    ],
)
def test_namespace_level(
    source: str,
    target: str,
    expected: tuple[str, str] | None,
) -> None:
    assert namespace_level(source, target, _NODES) == expected


@pytest.mark.parametrize(
    ("source", "target", "expected"),
    [
        pytest.param("x.y.z", "a.b.c", ("x.y.z", "a.b.c"), id="node_to_node"),
        # The import lands inside a selected package: the arrow ends on it.
        pytest.param("a.b.c", "a.d.e", ("a.b.c", "a.d"), id="inside_a_node"),
        # A facade above the nodes stays itself: it is drawn as their container.
        pytest.param("x.y.z", "a.b", ("x.y.z", "a.b"), id="facade"),
        pytest.param("a.d", "a.d.e", None, id="own_descendant"),
        pytest.param("a.b.c", "a.b", None, id="own_package"),
    ],
)
def test_module_level(
    source: str,
    target: str,
    expected: tuple[str, str] | None,
) -> None:
    assert module_level(source, target, _NODES) == expected


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


def test_project_dir_wins_over_a_same_named_package_already_on_the_path(
    tmp_path: Path,
) -> None:
    """An installed copy of the project must not shadow the directory asked for.

    ``uv sync`` installs the project into the venv, so when ``diff --base`` graphs
    an older checkout, the installed (current) copy is already importable. If the
    project directory only went to the end of ``sys.path``, the old side would
    silently be built from the current code and the diff would come out empty.
    """
    shadow = tmp_path / "pkg_a"
    shadow.mkdir()
    (shadow / "__init__.py").write_text("")
    (shadow / "impostor.py").write_text("")
    sys.path.insert(0, str(tmp_path))
    try:
        selected = GrimpSource(str(CYCLIC_PROJECT), ["pkg_a.*"]).selected_modules()
    finally:
        sys.path.remove(str(tmp_path))
    assert selected == ["pkg_a.core", "pkg_a.services"]


def test_uncached_source_is_not_fooled_by_an_equal_mtime(tmp_path: Path) -> None:
    """Grimp's cache is keyed by module *name* and mtime, not by path.

    ``git archive`` stamps every file with its commit's time, so two revisions
    committed within one second look identical to it and the second diff side
    is silently read from the first one's cache.
    """
    old, new = tmp_path / "old", tmp_path / "new"
    for root, body in ((old, ""), (new, "from pkg_a import core\n")):
        shutil.copytree(CYCLIC_PROJECT, root)
        (root / "pkg_b" / "util.py").write_text(body)
        for path in root.rglob("*.py"):
            os.utime(path, (1_000_000_000, 1_000_000_000))

    def edges(root: Path) -> set[tuple[str, str]]:
        source = GrimpSource(str(root), ["pkg_a.*", "pkg_b.*"], use_cache=False)
        return {(e.source, e.target) for e in ModuleExtractor(source).extract().edges}

    assert ("pkg_b.util", "pkg_a.core") not in edges(old)
    assert ("pkg_b.util", "pkg_a.core") in edges(new)


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


@pytest.mark.parametrize(
    ("layout", "expected"),
    [
        pytest.param(
            {"b/__init__.py": "", "a/__init__.py": ""},
            ["a", "b"],
            id="sorted",
        ),
        pytest.param({"ns/inner/__init__.py": ""}, ["ns"], id="namespace_package"),
        pytest.param({"docs/notes.txt": "", "tool.py": ""}, [], id="no_package"),
        pytest.param({".venv/pkg/__init__.py": ""}, [], id="hidden_dir"),
        pytest.param({"my-app/__init__.py": ""}, [], id="not_an_identifier"),
    ],
)
def test_detect_roots(
    tmp_path: Path,
    layout: dict[str, str],
    expected: list[str],
) -> None:
    for name, text in layout.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text)
    assert detect_roots(str(tmp_path)) == expected


def test_module_level_links_node_to_node() -> None:
    """The level changes the aggregation key only: the edge keeps the real import."""
    source = GrimpSource(str(EXAMPLE_PROJECT), ["app1.*", "app2.*", "plugins.**"])
    graph = ModuleExtractor(source, module_level).extract()
    assert {(link.source, link.target) for link in graph.links} == {
        ("app2.service", "app1.models"),
        ("app2.service", "plugins.auth.backend"),
    }
