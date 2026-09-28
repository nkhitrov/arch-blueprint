from __future__ import annotations

from collections.abc import Iterator

from arch_blueprint.domain.graph import BlueprintGraph, Edge
from arch_blueprint.domain.node import Node, NodeKind
from arch_blueprint.extract.levels import LinkLevel, ancestors, namespace_level
from arch_blueprint.extract.source import GrimpSource


class ModuleExtractor:
    """Extracts a graph whose nodes are modules from the import graph (the default).

    Each selected module becomes a node; an edge is drawn when a module imports
    another selected module across a boundary of the link ``level`` — by default
    a namespace boundary (see ``extract/levels.py``). The own imports of package
    facades above the nodes become ``facade_edges``: never drawn, they close the
    cycles that run through a package's ``__init__.py``.

    With ``--deps`` (``source.deps``), an import of a module outside the
    selection is not dropped: the module becomes a neighbor node, and the edge
    runs to it at the same level. A neighbor holds no other: when both
    ``pkg.a`` and ``pkg.a.b`` are imported, ``pkg.a.b`` is the node and
    ``pkg.a`` stays its package facade — an endpoint, as for the focus.
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
        outside = (
            frozenset(
                dep
                for deps in imports.values()
                for dep in deps
                if not self._is_selected(dep, selected, above)
            )
            if self.source.deps is not None
            else frozenset()
        )
        neighbors = sorted(GrimpSource.leaves(outside))
        nodes += [Node(id=name, kind=NodeKind.MODULE) for name in neighbors]
        ids = selected | frozenset(neighbors)
        edges = {
            edge
            for name in modules
            for edge in self._edges(name, imports[name], ids, above, outside)
        }
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
