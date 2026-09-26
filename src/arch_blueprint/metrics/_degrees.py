from __future__ import annotations

from typing import Optional

from arch_blueprint.domain.graph import BlueprintGraph


def _owner(target: str, node_ids: set[str]) -> Optional[str]:
    """The node that ``target`` is, or lies under; ``None`` when there is none.

    An edge's target is the imported module, not a node id: when the selected
    nodes are packages, it is usually a submodule of one. Within one graph no
    node lies under another, so the first match walking up the dotted name is
    the only one.
    """
    name = target
    while True:
        if name in node_ids:
            return name
        cutoff = name.rfind(".")
        if cutoff == -1:
            return None
        name = name[:cutoff]


def degree_counts(graph: BlueprintGraph) -> tuple[dict[str, int], dict[str, int]]:
    """Return ``(fan_in, fan_out)`` per node id, counted in distinct nodes.

    ``fan_out(n)`` is the number of nodes ``n`` imports from, ``fan_in(n)`` the
    number of nodes importing from ``n`` — however many of each other's
    submodules are involved, and never counting a node against itself.

    A target owned by no node — an ancestor package whose children are the
    selected nodes (a re-exporting facade) — is not a node, so it adds to no
    node's ``fan_in`` nor to its importer's ``fan_out``.

    Three metrics need the same two counters, so the traversal lives in one place
    instead of being repeated (and, for instability, repeated twice over).
    """
    node_ids = {node.id for node in graph.nodes}
    dependents: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    dependencies: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    for edge in graph.edges:
        owner = _owner(edge.target, node_ids)
        if owner is None or edge.source not in node_ids or owner == edge.source:
            continue
        dependencies[edge.source].add(owner)
        dependents[owner].add(edge.source)
    fan_in = {node.id: len(dependents[node.id]) for node in graph.nodes}
    fan_out = {node.id: len(dependencies[node.id]) for node in graph.nodes}
    return fan_in, fan_out
