from __future__ import annotations

from arch_blueprint.domain.graph import BlueprintGraph, Edge
from arch_blueprint.domain.node import Node, NodeKind
from arch_blueprint.extract.base import common_depth_namespaces, parent_namespace
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
        nodes = [
            Node(id=name, kind=NodeKind.MODULE, namespace=parent_namespace(name))
            for name in modules
        ]

        prefixes = [(name, name + ".") for name in modules]
        edges: set[Edge] = set()
        for name in modules:
            for dep in self.source.imports_of(name):
                if not self._is_selected(dep, prefixes):
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
    def _is_selected(dep: str, prefixes: list[tuple[str, str]]) -> bool:
        return any(
            dep == selected or dep.startswith(prefix) for selected, prefix in prefixes
        )
