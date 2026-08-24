from __future__ import annotations

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
        edges: set[Edge] = set()
        for name in modules:
            for dep in self.source.imports_of(name):
                if not self._is_selected(dep, selected):
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
    def _is_selected(dep: str, selected: set[str]) -> bool:
        """True when ``dep`` is a selected module or lives under one.

        Walking ``dep``'s own dotted ancestors costs its depth, rather than a
        scan of every selected name.
        """
        if dep in selected:
            return True
        cutoff = dep.rfind(".")
        while cutoff != -1:
            dep = dep[:cutoff]
            if dep in selected:
                return True
            cutoff = dep.rfind(".")
        return False
