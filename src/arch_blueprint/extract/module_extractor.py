from __future__ import annotations

from collections.abc import Iterator

from arch_blueprint.domain.graph import BlueprintGraph, Edge
from arch_blueprint.domain.node import Node, NodeKind
from arch_blueprint.extract.focus import follows_in, follows_out
from arch_blueprint.extract.levels import LinkLevel, ancestors, namespace_level
from arch_blueprint.extract.source import GrimpSource


class ModuleExtractor:
    """Extracts a graph whose nodes are modules from the import graph (the default).

    Each selected module becomes a node; an edge is drawn when a module imports
    another selected module across a boundary of the link ``level`` — by default
    a namespace boundary (see ``extract/levels.py``). The own imports of package
    facades above the nodes become ``facade_edges``: never drawn, they close the
    cycles that run through a package's ``__init__.py``.

    With ``--deps`` (``source.deps``), the modules next to the selection are
    drawn too, as neighbor nodes: with ``out`` every module a selected one
    imports, with ``in`` every module importing a selected one (or the package
    a ``pkg.*`` pattern selects the insides of). A neighbor holds no other:
    when both ``pkg.a`` and ``pkg.a.b`` are next to the selection, ``pkg.a.b``
    is the node and ``pkg.a`` an endpoint, as a package facade is for the
    focus. Every edge between the focus and a neighbor is drawn, either way.
    """

    def __init__(self, source: GrimpSource, level: LinkLevel = namespace_level) -> None:
        self.source = source
        self.level = level

    def extract(self) -> BlueprintGraph:
        modules = self.source.selected_modules()
        nodes = [Node(id=name, kind=NodeKind.MODULE) for name in modules]

        selected = frozenset(modules)
        above = {ancestor for name in modules for ancestor in ancestors(name)}
        imports = {name: self.source.imports_of(name) for name in modules}
        deps = self.source.deps
        targets = self._focus_targets(modules) if deps is not None else frozenset()
        outside = (
            frozenset(
                dep
                for found in imports.values()
                for dep in found
                if not self._is_selected(dep, selected, above)
            )
            if follows_out(deps)
            else frozenset()
        )
        importers = (
            self._importers(targets, selected, above)
            if follows_in(deps)
            else frozenset()
        )
        beside = outside | importers
        neighbors = sorted(GrimpSource.leaves(beside))
        nodes += [Node(id=name, kind=NodeKind.MODULE) for name in neighbors]
        ids = selected | frozenset(neighbors)
        edges = {
            edge
            for name in modules
            for edge in self._edges(name, imports[name], ids, above, outside)
        }
        edges.update(self._edges_into(neighbors, beside, targets, ids))
        # A facade's own imports: importing ``pkg`` runs ``pkg/__init__.py``, so
        # they sit on every cycle through ``pkg``. Kept apart — cycles are found
        # through them, but they are not drawn.
        facade_edges = {
            edge
            for facade in above
            for edge in self._edges(
                facade,
                self.source.own_imports_of(facade),
                selected,
                above,
            )
        }
        return BlueprintGraph(
            nodes=nodes,
            edges=frozenset(edges),
            facade_edges=frozenset(facade_edges),
            neighbors=frozenset(neighbors),
        )

    def _focus_targets(self, modules: list[str]) -> frozenset[str]:
        """The modules an import of which is an import of the focus.

        A selected module, one below it, or the package a ``pkg.*`` pattern
        selects the insides of.
        """
        targets = set(modules) | set(self.source.pattern_stems())
        for name in modules:
            targets.update(self.source.modules_under(name))
        return frozenset(targets)

    def _importers(
        self,
        targets: frozenset[str],
        selected: frozenset[str],
        above: set[str],
    ) -> frozenset[str]:
        """The modules outside the selection that import the focus.

        A package facade above the focus is not one of them: its imports are
        ``facade_edges``.
        """
        return frozenset(
            importer
            for target in targets
            for importer in self.source.importers_of(target)
            if not self._is_selected(importer, selected, above)
        )

    def _edges_into(
        self,
        neighbors: list[str],
        beside: frozenset[str],
        targets: frozenset[str],
        ids: frozenset[str],
    ) -> Iterator[Edge]:
        """Every edge from the neighbor side into the focus (``targets``).

        A neighbor node stands for its subtree, as a focus node does; a module
        ``beside`` the focus holding a neighbor is an endpoint, a package
        facade importing only for itself. Nothing a neighbor imports outside
        the focus is read.
        """
        sources = [(name, self.source.imports_of(name)) for name in neighbors]
        sources += [
            (name, self.source.own_imports_of(name))
            for name in sorted(beside.difference(neighbors))
        ]
        for name, found in sources:
            for dep in found & targets:
                pair = self.level(name, dep, ids)
                if pair is not None:
                    yield Edge(
                        source=name,
                        target=dep,
                        source_endpoint=pair[0],
                        target_endpoint=pair[1],
                    )

    def _edges(
        self,
        name: str,
        imports: set[str],
        nodes: frozenset[str],
        above: set[str],
        outside: frozenset[str] = frozenset(),
    ) -> Iterator[Edge]:
        """Edges from ``name`` to what it imports among ``nodes`` and ``outside``.

        ``outside`` is what ``--deps`` draws beyond the selection — the modules
        the neighbor ``nodes`` were picked from, facades among them.
        """
        for dep in imports:
            if dep not in outside and not self._is_selected(dep, nodes, above):
                continue
            pair = self.level(name, dep, nodes)
            if pair is not None:
                yield Edge(
                    source=name,
                    target=dep,
                    source_endpoint=pair[0],
                    target_endpoint=pair[1],
                )

    @staticmethod
    def _is_selected(dep: str, selected: frozenset[str], above: set[str]) -> bool:
        """True when ``dep`` belongs to the selected set, in either direction.

        Downward: ``dep`` is a selected module or lives under one.

        Upward: ``dep`` is a package whose children were selected. Selecting
        ``pkg.*`` never selects ``pkg`` itself, and ``GrimpSource.leaves``
        removes it when it is, so a package that re-exports its children could
        never be matched — and every import of that facade vanished.

        Both directions are set lookups over the dependency's own depth; neither
        scans the selected names.
        """
        if dep in selected or dep in above:
            return True
        return any(parent in selected for parent in ancestors(dep))
