from __future__ import annotations

import importlib
import importlib.util
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Optional

import grimp
from grimp import ImportGraph


class GrimpSource:
    """Builds and exposes a grimp import graph for the selected target packages.

    Encapsulates all the sys.path / package-resolution mechanics so extractors
    can work against a clean interface (selected modules, their imports, and the
    source file of any module).
    """

    def __init__(
        self,
        project_dir: str,
        target_names: Sequence[str],
        sys_path: Optional[list[str]] = None,
    ) -> None:
        self.project_dir = project_dir
        self.target_names = target_names
        self.sys_path = sys_path if sys_path is not None else sys.path
        self._graph: Optional[ImportGraph] = None

    @property
    def graph(self) -> ImportGraph:
        if self._graph is None:
            self._graph = self._build()
        return self._graph

    def _build(self) -> ImportGraph:
        if self.project_dir not in self.sys_path:
            self.sys_path.append(self.project_dir)
        packages = self._resolve_grimp_packages()
        if not packages:
            raise ImportError(
                "None of the given --modules patterns resolve to an analyzable "
                "source package.",
            )
        return grimp.build_graph(*packages)

    def selected_modules(self) -> list[str]:
        """Modules matching the target patterns, with parents of others removed."""
        module_names: set[str] = set()
        for name in self.target_names:
            module_names.update(self.graph.find_matching_modules(name))
        return sorted(self._exclude_sub_modules(module_names))

    def imports_of(self, module: str) -> set[str]:
        """All modules imported by ``module`` or any of its descendants."""
        descendants = self.graph.find_descendants(module)
        if not descendants:
            return set(self.graph.find_modules_directly_imported_by(module))

        result: set[str] = set()
        for descendant in descendants:
            result.update(self.graph.find_modules_directly_imported_by(descendant))
        return result

    def module_file(self, module: str) -> Optional[Path]:
        """Resolve a module's source file without importing/executing it."""
        try:
            spec = importlib.util.find_spec(module)
        except (ImportError, AttributeError, ValueError):
            return None
        if spec is None or spec.origin is None:
            return None
        return Path(spec.origin)

    def _resolve_grimp_packages(self) -> list[str]:
        packages: list[str] = []
        for name in self.target_names:
            top_level = self._get_top_level_package(name)
            for graphable in self._expand_to_graphable(top_level):
                if graphable not in packages:
                    packages.append(graphable)
        return packages

    @staticmethod
    def _get_top_level_package(module_name: str) -> str:
        components = module_name.split(".")
        for level in range(len(components)):
            candidate_name = ".".join(components[: level + 1])
            candidate = importlib.import_module(candidate_name)
            if getattr(candidate, "__file__", None) or hasattr(candidate, "__path__"):
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
        module = importlib.import_module(package)
        if getattr(module, "__file__", None):
            return [package]  # regular package: grimp can build it directly

        # PEP 420 namespace package — grimp can't build it. Descend through its
        # directories (including nested namespace dirs) to reach regular packages.
        graphable: list[str] = []
        for child in cls._child_package_dirs(module.__path__):
            graphable.extend(cls._find_graphable_packages(f"{package}.{child}"))
        return graphable

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
