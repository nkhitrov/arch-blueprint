from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from arch_blueprint.analyze.cycles import CycleAnalyzer
from arch_blueprint.domain.graph import BlueprintGraph
from arch_blueprint.domain.node import NodeKind
from arch_blueprint.extract.base import common_depth_namespaces
from arch_blueprint.extract.layout import detect_roots
from arch_blueprint.extract.levels import module_level, namespace_level
from arch_blueprint.extract.module_extractor import ModuleExtractor
from arch_blueprint.extract.registry import LINK_LEVELS
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


def test_source_is_not_fooled_by_an_equal_mtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Grimp's cache is keyed by module *name* and mtime, not by path.

    ``git archive`` stamps every file with its commit's time, so two revisions
    committed within one second look identical to it and the second one would
    silently be read from the first one's cache — in ``draw`` as in a diff.
    """
    monkeypatch.chdir(tmp_path)
    old, new = tmp_path / "old", tmp_path / "new"
    for root, body in ((old, ""), (new, "from pkg_a import core\n")):
        shutil.copytree(CYCLIC_PROJECT, root)
        (root / "pkg_b" / "util.py").write_text(body)
        for path in root.rglob("*.py"):
            os.utime(path, (1_000_000_000, 1_000_000_000))

    def edges(root: Path) -> set[tuple[str, str]]:
        source = GrimpSource(str(root), ["pkg_a.*", "pkg_b.*"])
        return {(e.source, e.target) for e in ModuleExtractor(source).extract().edges}

    assert ("pkg_b.util", "pkg_a.core") not in edges(old)
    assert ("pkg_b.util", "pkg_a.core") in edges(new)
    assert not (tmp_path / ".grimp_cache").exists()


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


# --- definition extraction ------------------------------------------------

#: A shop whose classes and functions reference each other across modules, a
#: package facade re-export and a package ``__init__.py`` that defines a class.
_SHOP = {
    "shop/__init__.py": "from shop.models import User\n",
    "shop/models.py": (
        "class User:\n"
        "    @classmethod\n"
        "    def create(cls) -> 'User':\n"
        "        return cls()\n"
        "\n"
        "class Order:\n"
        "    owner: User\n"
        "\n"
        "def make_user() -> User:\n"
        "    return User.create()\n"
    ),
    "shop/service.py": (
        "from shop import User\n"
        "from shop.models import Order, make_user\n"
        "\n"
        "class Service:\n"
        "    def run(self) -> None:\n"
        "        make_user()\n"
        "\n"
        "class Checkout:\n"
        "    def __init__(self, user: User) -> None:\n"
        "        self.order = Order()\n"
        "\n"
        "def report():\n"
        "    return Checkout\n"
    ),
    "shop/sub/__init__.py": "class Base:\n    pass\n",
    "shop/sub/worker.py": (
        "from shop.sub import Base\n"
        "import json\n"
        "\n"
        "class Worker(Base):\n"
        "    def dump(self) -> str:\n"
        "        return json.dumps({})\n"
    ),
}


def _shop(root: Path) -> GrimpSource:
    for name, text in _SHOP.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return GrimpSource(str(root), ["shop.**"])


def _extract(root: Path) -> BlueprintGraph:
    """The shop at the class level: classes and module-level functions."""
    return LINK_LEVELS["class"].extractor(_shop(root)).extract()


def test_class_extractor_nodes_are_the_definitions_sorted_by_id(
    tmp_path: Path,
) -> None:
    """Sorted, as module nodes are: a diff declares its nodes in id order."""
    graph = _extract(tmp_path)
    assert [(node.id, node.kind) for node in graph.nodes] == [
        ("shop.models.Order", NodeKind.CLASS),
        ("shop.models.User", NodeKind.CLASS),
        ("shop.models.make_user", NodeKind.FUNCTION),
        ("shop.service.Checkout", NodeKind.CLASS),
        ("shop.service.Service", NodeKind.CLASS),
        ("shop.service.report", NodeKind.FUNCTION),
        # a package `pkg.**` matches holds definitions of its own
        ("shop.sub.Base", NodeKind.CLASS),
        ("shop.sub.worker.Worker", NodeKind.CLASS),
    ]


def test_class_extractor_links_definition_to_definition(tmp_path: Path) -> None:
    """Resolved through the facade; no self-reference, nothing outside the project.

    ``Service`` only calls ``make_user``, a function that uses ``User``: the
    function is a node, so the chain is two arrows through it.
    """
    graph = _extract(tmp_path)
    assert {(edge.source, edge.target) for edge in graph.edges} == {
        ("shop.models.Order", "shop.models.User"),
        ("shop.models.make_user", "shop.models.User"),
        ("shop.service.Service", "shop.models.make_user"),
        ("shop.service.Checkout", "shop.models.User"),
        ("shop.service.Checkout", "shop.models.Order"),
        ("shop.service.report", "shop.service.Checkout"),
        ("shop.sub.worker.Worker", "shop.sub.Base"),
    }
    assert all(
        (edge.source_endpoint, edge.target_endpoint) == (edge.source, edge.target)
        for edge in graph.edges
    )
    assert graph.facade_edges == frozenset()


def test_definition_extractor_leaves_no_modules_behind(tmp_path: Path) -> None:
    (tmp_path / "shop").mkdir()
    (tmp_path / "shop" / "boom.py").write_text("raise RuntimeError\n")
    before = set(sys.modules)
    _extract(tmp_path)
    assert not any(name.startswith("shop") for name in set(sys.modules) - before)


@pytest.mark.parametrize("pattern", ["app.*", "app.**"])
def test_definitions_of_the_root_facade_are_nodes(tmp_path: Path, pattern: str) -> None:
    """``app.*`` never matches ``app``, but ``app/__init__.py`` defines things."""
    (tmp_path / "app" / "config").mkdir(parents=True)
    (tmp_path / "app" / "__init__.py").write_text(
        "from app.config.core import Config\ndef settings() -> Config:\n    pass\n",
    )
    (tmp_path / "app" / "config" / "__init__.py").write_text("")
    (tmp_path / "app" / "config" / "core.py").write_text("class Config:\n    pass\n")
    source = GrimpSource(str(tmp_path), [pattern])
    graph = LINK_LEVELS["class"].extractor(source).extract()
    assert [node.id for node in graph.nodes] == [
        "app.config.core.Config",
        "app.settings",
    ]
    assert {(e.source, e.target) for e in graph.edges} == {
        ("app.settings", "app.config.core.Config"),
    }


def test_definition_named_like_a_submodule_is_no_frame(tmp_path: Path) -> None:
    """``pkg.mod`` cannot be a box and the frame of ``pkg/mod.py``'s classes."""
    (tmp_path / "pkg" / "sub").mkdir(parents=True)
    (tmp_path / "pkg" / "__init__.py").write_text(
        "from pkg.mod import X\n"
        "class mod:\n"
        "    def f(self) -> X:\n"
        "        pass\n"
        "def sub() -> 'mod':\n"
        "    pass\n",
    )
    (tmp_path / "pkg" / "mod.py").write_text(
        "import pkg\nclass X:\n    pass\nclass Y(X):\n    x: pkg.mod\n",
    )
    (tmp_path / "pkg" / "sub" / "__init__.py").write_text("")
    source = GrimpSource(str(tmp_path), ["pkg"])
    graph = LINK_LEVELS["class"].extractor(source).extract()
    assert [node.id for node in graph.nodes] == [
        "pkg.__init__.mod",
        "pkg.__init__.sub",  # a package without a definition is still a module
        "pkg.mod.X",
        "pkg.mod.Y",
    ]
    assert {(e.source, e.target) for e in graph.edges} == {
        ("pkg.__init__.mod", "pkg.mod.X"),
        ("pkg.__init__.sub", "pkg.__init__.mod"),
        ("pkg.mod.Y", "pkg.mod.X"),
        ("pkg.mod.Y", "pkg.__init__.mod"),
    }


def test_libcst_is_loaded_only_at_a_definition_level() -> None:
    """A module in ``sys.modules`` is what ``find_spec`` finds first.

    Loading libcst at startup would draw the installed copy for a project named
    ``libcst`` at every level, as the running ``arch_blueprint`` is (CLAUDE.md).
    """
    code = "import sys, arch_blueprint.__main__; print('libcst' in sys.modules)"
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "False"


# --- registered levels ----------------------------------------------------


@pytest.mark.parametrize(
    ("level", "kinds", "nested"),
    [
        ("class", {NodeKind.CLASS, NodeKind.FUNCTION}, False),
        ("class-grouped", {NodeKind.CLASS, NodeKind.FUNCTION}, True),
    ],
)
def test_definition_levels(
    tmp_path: Path,
    level: str,
    kinds: set[NodeKind],
    *,
    nested: bool,
) -> None:
    registered = LINK_LEVELS[level]
    graph = registered.extractor(_shop(tmp_path)).extract()
    assert {node.kind for node in graph.nodes} == kinds
    assert registered.nested == nested


@pytest.mark.parametrize(
    ("level", "nested"),
    [("namespace", True), ("module", False)],
)
def test_module_levels_are_unchanged(level: str, *, nested: bool) -> None:
    registered = LINK_LEVELS[level]
    source = GrimpSource(str(EXAMPLE_PROJECT), ["app1.*", "app2.*"])
    graph = registered.extractor(source).extract()
    assert {node.kind for node in graph.nodes} == {NodeKind.MODULE}
    assert registered.nested == nested
