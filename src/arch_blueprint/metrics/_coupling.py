from __future__ import annotations

from arch_blueprint.domain.graph import BlueprintGraph


def tree_distance(source: str, target: str) -> int:
    """Path length between two dotted names in the package tree.

    Steps up from ``source`` to the deepest shared package, then down to
    ``target``: ``pkg.sub.a`` and ``pkg.sub.b`` are 2 apart, ``pkg.sub.a`` and
    ``other.b`` are 5.
    """
    source_parts = source.split(".")
    target_parts = target.split(".")
    shared = 0
    for first, second in zip(source_parts, target_parts):
        if first != second:
            break
        shared += 1
    return len(source_parts) + len(target_parts) - 2 * shared


def link_distances(graph: BlueprintGraph) -> dict[tuple[str, str], int]:
    """Distance per link: the farthest module pair the link aggregates.

    Measured between modules, never between the link's own namespaces — a
    namespace pair shares every component but the last by construction, so it
    would score a constant 2 everywhere. The farthest pair is taken because it
    is the one a coordinated change has to travel.
    """
    return {
        (link.source_namespace, link.target_namespace): max(
            tree_distance(edge.source, edge.target) for edge in link.edges
        )
        for link in graph.links
    }
