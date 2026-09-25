from __future__ import annotations

from arch_blueprint.analyze.groups import GroupAnalyzer
from arch_blueprint.diff.model import ChangeStatus, CycleChange, CycleDelta, GraphDiff
from arch_blueprint.domain.graph import BlueprintGraph, Cycle, Edge, Link


def diff_graphs(old: BlueprintGraph, new: BlueprintGraph) -> GraphDiff:
    """Compare two analyzed graphs at the level a diagram shows them.

    Links compare by namespace pair, directed, so ``A→B`` becoming ``A↔B`` is a
    new cycle rather than nothing. A change to the individual imports inside a
    link present on both sides is not a link change.

    Context is exact rather than "everything under the namespace": the unchanged
    nodes drawn are the ones the changed links' imports actually connect.
    """
    old_links = _links_by_pair(old)
    new_links = _links_by_pair(new)
    cycle_changes = _cycle_changes(old, new)
    cycle_keys = {_key(delta.cycle) for delta in cycle_changes}

    link_status: dict[tuple[str, str], ChangeStatus] = {}
    edges: set[Edge] = set()
    for pairs, links, status in (
        (new_links.keys() - old_links.keys(), new_links, ChangeStatus.ADDED),
        (old_links.keys() - new_links.keys(), old_links, ChangeStatus.REMOVED),
    ):
        for pair in pairs:
            if frozenset(pair) not in cycle_keys:
                link_status[pair] = status
                edges |= links[pair].edges
    for delta in cycle_changes:
        edges |= delta.cycle.forward_edges | delta.cycle.backward_edges

    node_status = _node_status(old, new, edges)
    nodes = {node.id: node for node in (*old.nodes, *new.nodes)}
    graph = BlueprintGraph(
        nodes=[nodes[node_id] for node_id in sorted(node_status)],
        edges=frozenset(edges),
    )
    # Groups only: cycle detection over this partial edge set would report a
    # resolved cycle as present. Cycles live in ``cycle_changes``.
    graph.groups = GroupAnalyzer.build(graph)
    return GraphDiff(
        graph=graph,
        node_status=node_status,
        link_status=dict(sorted(link_status.items())),
        cycle_changes=cycle_changes,
    )


def _links_by_pair(graph: BlueprintGraph) -> dict[tuple[str, str], Link]:
    return {
        (link.source_namespace, link.target_namespace): link for link in graph.links
    }


def _key(cycle: Cycle) -> frozenset[str]:
    return frozenset({cycle.namespace_from, cycle.namespace_to})


def _cycle_changes(old: BlueprintGraph, new: BlueprintGraph) -> tuple[CycleDelta, ...]:
    old_cycles = {_key(cycle): cycle for cycle in old.cycles}
    new_cycles = {_key(cycle): cycle for cycle in new.cycles}
    deltas = [
        CycleDelta(CycleChange.NEW, new_cycles[key])
        for key in new_cycles.keys() - old_cycles.keys()
    ]
    deltas += [
        CycleDelta(CycleChange.RESOLVED, old_cycles[key])
        for key in old_cycles.keys() - new_cycles.keys()
    ]
    return tuple(
        sorted(
            deltas,
            key=lambda d: (d.cycle.namespace_from, d.cycle.namespace_to),
        ),
    )


def _node_status(
    old: BlueprintGraph,
    new: BlueprintGraph,
    edges: set[Edge],
) -> dict[str, ChangeStatus]:
    old_ids = {node.id for node in old.nodes}
    new_ids = {node.id for node in new.nodes}
    status = dict.fromkeys(new_ids - old_ids, ChangeStatus.ADDED)
    status.update(dict.fromkeys(old_ids - new_ids, ChangeStatus.REMOVED))
    unchanged = old_ids & new_ids
    for endpoint in {edge.source for edge in edges} | {edge.target for edge in edges}:
        for node_id in _nodes_for(endpoint, unchanged):
            status[node_id] = ChangeStatus.CONTEXT
    return dict(sorted(status.items()))


def _nodes_for(module: str, node_ids: set[str]) -> set[str]:
    """The nodes an import endpoint stands for.

    An endpoint is rarely a node itself. With ``-m 'pkg.*.*'`` nodes are
    packages and imports name modules inside them, so the owner is the deepest
    node containing the module. An import of a package facade has no owner —
    ``pkg.*`` never makes ``pkg`` a node — and stands for the nodes under it.
    """
    owners = [
        node_id
        for node_id in node_ids
        if module == node_id or module.startswith(f"{node_id}.")
    ]
    if owners:
        return {max(owners, key=len)}
    return {node_id for node_id in node_ids if node_id.startswith(f"{module}.")}
