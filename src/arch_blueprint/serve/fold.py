"""Folding: a module-level graph with some packages drawn as one node each.

A view of the viewer is the module-level graph with the packages the user
collapsed folded. Folding is a property of the view, not of the extraction, so
it is a transform of an extracted graph rather than a link level: snapshots,
``LINK_LEVELS`` and every cache stay as they are.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable

from arch_blueprint.domain.graph import BlueprintGraph, Edge
from arch_blueprint.domain.node import Node, NodeKind
from arch_blueprint.extract.levels import ancestors

#: The name a node or endpoint is drawn as once folded.
_Owner = Callable[[str], str]


def fold(graph: BlueprintGraph, folded: Collection[str]) -> BlueprintGraph:
    """``graph`` with every name under a ``folded`` prefix drawn as that prefix.

    The nodes under a prefix become one module node named by it — the shortest
    prefix, when folds nest; a prefix no node lies under draws nothing. Edge
    endpoints follow their nodes, and ``Edge.source`` / ``target`` stay the real
    import, so a link still lists the imports it stands for.

    A facade import inside a folded package is that node's own code now, so it
    becomes an ordinary edge: a folded package draws what selecting it whole
    (``-m pkg``) draws. An edge folded onto itself, or onto the package its
    source lies in, draws nothing, as at the module level.

    The result is not analyzed: metrics, cycles and tangles are computed on it.
    """
    prefixes = frozenset(folded)

    def owner(name: str) -> str:
        outermost = name if name in prefixes else None
        for ancestor in ancestors(name):
            if ancestor in prefixes:
                outermost = ancestor
        return name if outermost is None else outermost

    nodes = list(
        dict.fromkeys(
            node if owner(node.id) == node.id else Node(owner(node.id), NodeKind.MODULE)
            for node in graph.nodes
        ),
    )
    internal = {edge for edge in graph.facade_edges if owner(edge.source) in prefixes}
    return BlueprintGraph(
        nodes=nodes,
        edges=frozenset(_refold(graph.edges | internal, owner)),
        facade_edges=frozenset(_refold(graph.facade_edges - internal, owner)),
    )


def _refold(edges: Iterable[Edge], owner: _Owner) -> Iterable[Edge]:
    for edge in edges:
        source = owner(edge.source_endpoint)
        target = owner(edge.target_endpoint)
        if source == target or source.startswith(f"{target}."):
            continue
        yield Edge(
            source=edge.source,
            target=edge.target,
            source_endpoint=source,
            target_endpoint=target,
        )
