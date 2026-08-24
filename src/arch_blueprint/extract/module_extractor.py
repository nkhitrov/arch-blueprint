from __future__ import annotations

from collections.abc import Iterator

from arch_blueprint.domain.graph import BlueprintGraph, Edge
from arch_blueprint.domain.node import Node, NodeKind
from arch_blueprint.extract.base import common_depth_namespaces
from arch_blueprint.extract.source import GrimpSource


class ModuleExtractor:
    """Extracts a module-level graph from the import graph (the default).

    Each selected module becomes a node; an edge is drawn when a module imports
    another selected module across a namespace boundary.
    """

    def __init__(self, source: GrimpSource) -> None:
        self.source = source

    def extract(self) -> BlueprintGraph:
        modules = self.source.selected_modules()
        nodes = [Node(id=name, kind=NodeKind.MODULE) for name in modules]

        selected = set(modules)
        ancestors = {ancestor for name in modules for ancestor in self._ancestors(name)}
        edges: set[Edge] = set()
        for name in modules:
            for dep in self.source.imports_of(name):
                if not self._is_selected(dep, selected, ancestors):
                    continue
                source_ns, target_ns = common_depth_namespaces(name, dep)
                if source_ns != target_ns:
                    edges.add(
                        Edge(
                            source=name,
                            target=dep,
                            source_namespace=source_ns,
                            target_namespace=target_ns,
                        ),
                    )

        return BlueprintGraph(nodes=nodes, edges=frozenset(edges))

    @staticmethod
    def _ancestors(module: str) -> Iterator[str]:
        """Every dotted prefix of ``module``, longest first, excluding itself."""
        cutoff = module.rfind(".")
        while cutoff != -1:
            module = module[:cutoff]
            yield module
            cutoff = module.rfind(".")

    @classmethod
    def _is_selected(cls, dep: str, selected: set[str], ancestors: set[str]) -> bool:
        """True when ``dep`` belongs to the selected set, in either direction.

        Downward: ``dep`` is a selected module or lives under one.

        Upward: ``dep`` is a package whose children were selected. Selecting
        ``pkg.*`` never selects ``pkg`` itself, and ``_exclude_sub_modules``
        removes it when it is, so a package that re-exports its children could
        never be matched — and every import of that facade vanished.

        Both directions are set lookups over the dependency's own depth; neither
        scans the selected names.
        """
        if dep in selected or dep in ancestors:
            return True
        return any(parent in selected for parent in cls._ancestors(dep))
