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
    """

    def __init__(self, source: GrimpSource, level: LinkLevel = namespace_level) -> None:
        self.source = source
        self.level = level

    def extract(self) -> BlueprintGraph:
        modules = self.source.selected_modules()
        nodes = [Node(id=name, kind=NodeKind.MODULE) for name in modules]

        selected = frozenset(modules)
        above = {ancestor for name in modules for ancestor in ancestors(name)}
        edges = {
            edge
            for name in modules
            for edge in self._edges(name, self.source.imports_of(name), selected, above)
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
        )

    def _edges(
        self,
        name: str,
        imports: set[str],
        selected: frozenset[str],
        above: set[str],
    ) -> Iterator[Edge]:
        for dep in imports:
            if not self._is_selected(dep, selected, above):
                continue
            pair = self.level(name, dep, selected)
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
        ``pkg.*`` never selects ``pkg`` itself, and ``_exclude_sub_modules``
        removes it when it is, so a package that re-exports its children could
        never be matched — and every import of that facade vanished.

        Both directions are set lookups over the dependency's own depth; neither
        scans the selected names.
        """
        if dep in selected or dep in above:
            return True
        return any(parent in selected for parent in ancestors(dep))
