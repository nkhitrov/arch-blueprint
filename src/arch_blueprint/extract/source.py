from __future__ import annotations

import importlib.util
import sys
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from importlib.machinery import ModuleSpec
from pathlib import Path
from typing import Optional

import grimp
from grimp import ImportGraph


class GrimpSource:
    """Builds and exposes a grimp import graph for the selected target packages.

    Encapsulates all the sys.path / package-resolution mechanics so extractors
    can work against a clean interface (the selected modules and their imports).

    Resolution never executes the target project's code: packages are located
    through ``importlib.util.find_spec``, and the interpreter state borrowed to
    do it (``sys.path``, ``sys.modules``) is handed back afterwards.
    """

    def __init__(
        self,
        project_dir: str,
        target_names: Sequence[str],
    ) -> None:
        self.project_dir = project_dir
        self.target_names = target_names
        self._graph: Optional[ImportGraph] = None

    @property
    def graph(self) -> ImportGraph:
        if self._graph is None:
            self._graph = self._build()
        return self._graph

    def _build(self) -> ImportGraph:
        with self._project_importable():
            packages = self._resolve_grimp_packages()
            if not packages:
                raise ImportError(
                    "None of the given --modules patterns resolve to an analyzable "
                    "source package.",
                )
            return grimp.build_graph(*packages)

    @contextmanager
    def _project_importable(self) -> Iterator[None]:
        """Put the project on ``sys.path``, then undo every trace of it.

        Without the undo, a second run in the same process resolves against the
        first project's leftovers: ``sys.modules`` is consulted before
        ``sys.path``, so restoring the path alone would not be enough.
        """
        added = self.project_dir not in sys.path
        if added:
            sys.path.append(self.project_dir)
        imported_before = set(sys.modules)
        try:
            yield
        finally:
            if added and self.project_dir in sys.path:
                sys.path.remove(self.project_dir)
            for name in set(sys.modules) - imported_before:
                del sys.modules[name]

    def selected_modules(self) -> list[str]:
        """Modules matching the target patterns, with parents of others removed."""
        module_names: set[str] = set()
        for name in self.target_names:
            module_names.update(self.graph.find_matching_modules(name))
        return sorted(self._exclude_sub_modules(module_names))

    def imports_of(self, module: str) -> set[str]:
        """All modules imported by ``module`` or any of its descendants.

        ``find_descendants`` excludes the module itself, so a package's own
        ``__init__.py`` imports have to be unioned in explicitly — dropping them
        hides every dependency a re-exporting package declares.
        """
        result = set(self.graph.find_modules_directly_imported_by(module))
        for descendant in self.graph.find_descendants(module):
            result.update(self.graph.find_modules_directly_imported_by(descendant))
        return result

    def _resolve_grimp_packages(self) -> list[str]:
        packages: list[str] = []
        for name in self.target_names:
            top_level = self._get_top_level_package(name)
            for graphable in self._expand_to_graphable(top_level):
                if graphable not in packages:
                    packages.append(graphable)
        return packages

    @classmethod
    def _get_top_level_package(cls, module_name: str) -> str:
        components = module_name.split(".")
        for level in range(len(components)):
            candidate_name = ".".join(components[: level + 1])
            spec = cls._find_spec(candidate_name)
            if spec is not None and (
                spec.origin is not None or spec.submodule_search_locations is not None
            ):
                return candidate_name
        raise ImportError(
            f"Can't import module '{module_name}'. Is it on the Python path?",
        )

    @classmethod
    def _expand_to_graphable(cls, package: str) -> list[str]:
        graphable = cls._find_graphable_packages(package)
        if not graphable:
            sys.stderr.write(
                f"warning: '{package}' is a namespace package with no analyzable "
                f"source; skipping.\n",
            )
        return graphable

    @classmethod
    def _find_graphable_packages(cls, package: str) -> list[str]:
        spec = cls._find_spec(package)
        if spec is None:
            return []
        if spec.origin is not None:
            return [package]  # regular package: grimp can build it directly

        # PEP 420 namespace package — grimp can't build it. Descend through its
        # directories (including nested namespace dirs) to reach regular packages.
        graphable: list[str] = []
        for child in cls._child_package_dirs(spec.submodule_search_locations or ()):
            graphable.extend(cls._find_graphable_packages(f"{package}.{child}"))
        return graphable

    @staticmethod
    def _find_spec(name: str) -> Optional[ModuleSpec]:
        """Locate ``name`` without executing it, or None if it isn't importable."""
        try:
            return importlib.util.find_spec(name)
        except (ImportError, ValueError):
            return None

    @staticmethod
    def _child_package_dirs(search_paths: Iterable[str]) -> list[str]:
        names: list[str] = []
        seen: set[str] = set()
        for path in search_paths:
            try:
                entries = sorted(Path(path).iterdir())
            except OSError:
                continue
            for entry in entries:
                name = entry.name
                if name in seen or name == "__pycache__" or not name.isidentifier():
                    continue
                if entry.is_dir():
                    seen.add(name)
                    names.append(name)
        return names

    @staticmethod
    def _exclude_sub_modules(modules: set[str]) -> set[str]:
        """Filter out names that are namespaces of other modules in the set."""
        sorted_names = sorted(modules, key=len, reverse=True)
        result: set[str] = set()
        for name in sorted_names:
            is_namespace = any(
                longer_name.startswith(name + ".") for longer_name in result
            )
            if not is_namespace:
                result.add(name)
        return result
