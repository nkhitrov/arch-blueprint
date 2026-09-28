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

from arch_blueprint.extract.layout import detect_roots


class PackageNotFoundError(ImportError):
    """A pattern's top-level package is nowhere to be found.

    Carries the pattern so the caller can say what to do about it; the wording
    is the caller's, this layer knows nothing of command lines.
    """

    def __init__(self, pattern: str) -> None:
        super().__init__(f"Can't import module '{pattern}'. Is it on the Python path?")
        self.pattern = pattern
        self.package = pattern.split(".", 1)[0]


def _lies_in(spec: ModuleSpec, directory: Path) -> bool:
    """Whether the module ``spec`` locates has its code in ``directory``."""
    places = [*(spec.submodule_search_locations or ())]
    if spec.origin is not None:
        places.append(spec.origin)
    return any(Path(place).resolve().is_relative_to(directory) for place in places)


class GrimpSource:
    """Builds and exposes a grimp import graph for the selected target packages.

    Encapsulates all the sys.path / package-resolution mechanics so extractors
    can work against a clean interface (the selected modules and their imports).

    Resolution never executes the target project's code: packages are located
    through ``importlib.util.find_spec``, and the interpreter state borrowed to
    do it (``sys.path``, ``sys.modules``) is handed back afterwards.

    ``deps`` (a ``--deps`` direction, ``extract/focus.py``) makes the patterns
    a focus whose dependencies or dependents are drawn too. They can lie in any
    package of the project, so every package in ``project_dir`` is built then,
    not only the patterns' own; what the patterns select does not change.
    """

    def __init__(
        self,
        project_dir: str,
        target_names: Sequence[str],
        deps: Optional[str] = None,
    ) -> None:
        self.project_dir = project_dir
        self.target_names = target_names
        self.deps = deps
        self._graph: Optional[ImportGraph] = None
        # Per run, like the graph: module names, located files, top-level specs.
        self._modules: Optional[frozenset[str]] = None
        self._module_files: dict[str, Optional[Path]] = {}
        self._top_level_specs: dict[str, Optional[ModuleSpec]] = {}

    @property
    def graph(self) -> ImportGraph:
        if self._graph is None:
            self._graph = self._build()
        return self._graph

    def _build(self) -> ImportGraph:
        """Build grimp's graph from source, never from grimp's cache.

        That cache lives in the working directory and is keyed by module *name*
        and mtime, not by path: another directory holding the same package —
        a ``git archive`` checkout stamps every file with its commit's time —
        or a concurrent run writing its two cache files in between would hand
        this project someone else's imports, drawn without a word.
        """
        with self._project_importable():
            packages = self._resolve_grimp_packages()
            if not packages:
                raise ImportError(
                    "None of the given --modules patterns resolve to an analyzable "
                    "source package.",
                )
            return grimp.build_graph(*packages, cache_dir=None)

    @contextmanager
    def _project_importable(self) -> Iterator[None]:
        """Put the project on ``sys.path``, then undo every trace of it.

        Without the undo, a second run in the same process resolves against the
        first project's leftovers: ``sys.modules`` is consulted before
        ``sys.path``, so restoring the path alone would not be enough.

        The directory goes to the *front*: the project is usually installed in
        the venv as well, and an older checkout of it (``diff --base``) must not
        resolve to the installed, current copy.
        """
        added = self.project_dir not in sys.path
        if added:
            sys.path.insert(0, self.project_dir)
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
        return sorted(self.leaves(self.matching_modules()))

    def matching_modules(self) -> list[str]:
        """Every module a target pattern matches, sorted — parents of others too.

        ``pkg.**`` matches ``pkg.sub`` as well as ``pkg.sub.x``: a module node
        stands for its whole subtree, so :meth:`selected_modules` keeps only the
        leaves, but the classes in ``pkg/sub/__init__.py`` are nodes of their own.
        """
        module_names: set[str] = set()
        for name in self.target_names:
            module_names.update(self.graph.find_matching_modules(name))
        return sorted(module_names)

    def pattern_stems(self) -> list[str]:
        """The packages a ``pkg.*`` or ``pkg.**`` pattern selects the insides of.

        Neither pattern matches ``pkg`` itself. A module node does not need it —
        ``pkg`` stands for its subtree — but the classes and functions in
        ``pkg/__init__.py`` are nodes of their own.
        """
        stems: set[str] = set()
        for name in self.target_names:
            stem, dot, last = name.rpartition(".")
            if dot and last in {"*", "**"}:
                stems.update(self.graph.find_matching_modules(stem))
        return sorted(stems)

    def own_imports_of(self, module: str) -> set[str]:
        """What ``module`` itself imports — for a package, its ``__init__.py``.

        Empty for a name the graph does not hold, such as a PEP 420 namespace
        package: it has no ``__init__.py`` to import anything.
        """
        if module not in self.graph.modules:
            return set()
        return set(self.graph.find_modules_directly_imported_by(module))

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

    def importers_of(self, module: str) -> set[str]:
        """The modules that import ``module`` itself — not one below it."""
        return set(self.graph.find_modules_that_directly_import(module))

    def downstream_of(self, module: str) -> set[str]:
        """Every module that imports ``module``, directly or through others."""
        return set(self.graph.find_downstream_modules(module))

    def modules_under(self, name: str) -> list[str]:
        """``name`` and every module below it that the graph holds, sorted.

        Read off the graph's module names rather than ``find_descendants``,
        which refuses a name the graph does not hold — a PEP 420 namespace
        package above the packages grimp built.
        """
        prefix = f"{name}."
        return sorted(
            module
            for module in self._known_modules()
            if module == name or module.startswith(prefix)
        )

    def module_file(self, name: str) -> Optional[Path]:
        """The file holding module ``name`` — ``x.py`` or ``x/__init__.py``.

        None for a module the graph does not hold (the standard library, a
        third-party package) and for a namespace package, which has no file.
        Only the top-level package goes through ``find_spec``: on a dotted name
        it imports every parent package, i.e. runs the project's code. Below
        it, the files are looked up across the package's search locations,
        several of them for a namespace package.
        """
        if name not in self._module_files:
            self._module_files[name] = self._locate(name)
        return self._module_files[name]

    def _known_modules(self) -> frozenset[str]:
        """The graph's module names, copied once: grimp builds a new set per call."""
        if self._modules is None:
            self._modules = frozenset(self.graph.modules)
        return self._modules

    def _top_level_spec(self, name: str) -> Optional[ModuleSpec]:
        if name not in self._top_level_specs:
            with self._project_importable():
                self._top_level_specs[name] = self._find_spec(name)
        return self._top_level_specs[name]

    def _locate(self, name: str) -> Optional[Path]:
        if name not in self._known_modules():
            return None
        top, *rest = name.split(".")
        spec = self._top_level_spec(top)
        if spec is None:
            return None
        if spec.submodule_search_locations is None:
            return Path(spec.origin) if spec.origin and not rest else None
        for location in spec.submodule_search_locations:
            directory = Path(location).joinpath(*rest)
            candidates = [directory / "__init__.py"]
            if rest:
                candidates.append(directory.with_name(f"{directory.name}.py"))
            for candidate in candidates:
                if candidate.is_file():
                    return candidate
        return None

    def _resolve_grimp_packages(self) -> list[str]:
        packages: list[str] = []
        for name in self.target_names:
            top_level = self._get_top_level_package(name)
            for graphable in self._expand_to_graphable(top_level):
                if graphable not in packages:
                    packages.append(graphable)
        if self.deps is not None:
            packages.extend(
                graphable
                for graphable in self._project_packages()
                if graphable not in packages
            )
        return packages

    def _project_packages(self) -> list[str]:
        """Every package of the project, for dependencies outside the patterns.

        Only the ones found in ``project_dir`` itself: a directory named like a
        module found first elsewhere (``sys.modules``, the standard library)
        would build that one instead. One with no analyzable source is skipped
        without a word — nobody asked for it.
        """
        project = Path(self.project_dir).resolve()
        packages: list[str] = []
        for root in detect_roots(self.project_dir):
            spec = self._find_spec(root)
            if spec is None or not _lies_in(spec, project):
                continue
            packages.extend(self._find_graphable_packages(root))
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
        raise PackageNotFoundError(module_name)

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
    def leaves(modules: Iterable[str]) -> set[str]:
        """The names no other name in ``modules`` lies under.

        A module node stands for its whole subtree, so no node may lie under
        another: of ``pkg`` and ``pkg.sub``, ``pkg.sub`` is kept.
        """
        sorted_names = sorted(modules, key=len, reverse=True)
        result: set[str] = set()
        for name in sorted_names:
            is_namespace = any(
                longer_name.startswith(name + ".") for longer_name in result
            )
            if not is_namespace:
                result.add(name)
        return result
