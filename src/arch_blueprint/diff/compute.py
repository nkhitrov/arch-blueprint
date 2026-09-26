from __future__ import annotations

from collections.abc import Iterable

from arch_blueprint.analyze.groups import GroupAnalyzer
from arch_blueprint.diff.model import (
    ChangeStatus,
    CycleChange,
    CycleDelta,
    GraphDiff,
    TangleDelta,
    shadowed_id,
)
from arch_blueprint.domain.graph import BlueprintGraph, Cycle, Edge, Link, Tangle
from arch_blueprint.domain.node import Node


def diff_graphs(
    old: BlueprintGraph,
    new: BlueprintGraph,
    *,
    changes_only: bool = False,
) -> GraphDiff:
    """Compare two analyzed graphs at the level a diagram shows them.

    Links compare by endpoint pair, directed, so ``A→B`` becoming ``A↔B`` is a
    new cycle rather than nothing. A change to the individual imports inside a
    link present on both sides is not a link change.

    The changes are drawn against the whole of both graphs: every node, link and
    cycle that did not change is context. With ``changes_only`` the context is
    exact rather than "everything": the unchanged nodes the changed links'
    imports actually connect, and no unchanged link.
    """
    old_links = _links_by_pair(old)
    new_links = _links_by_pair(new)
    cycle_changes = _cycle_changes(old, new, new_links.keys())
    old_cycles, new_cycles = _cycles_by_key(old), _cycles_by_key(new)
    context_cycles = (
        ()
        if changes_only
        else tuple(
            sorted(
                (new_cycles[key] for key in new_cycles.keys() & old_cycles.keys()),
                key=lambda c: (c.endpoint_from, c.endpoint_to),
            ),
        )
    )
    # Every pair a cycle connection stands for, changed or not.
    cycle_keys = {_key(delta.cycle) for delta in cycle_changes}
    cycle_keys |= {_key(cycle) for cycle in context_cycles}

    link_status: dict[tuple[str, str], ChangeStatus] = {}
    edges: set[Edge] = set()
    groups = [
        (new_links.keys() - old_links.keys(), new_links, ChangeStatus.ADDED),
        (old_links.keys() - new_links.keys(), old_links, ChangeStatus.REMOVED),
    ]
    if not changes_only:
        groups.append(
            (new_links.keys() & old_links.keys(), new_links, ChangeStatus.CONTEXT),
        )
    for pairs, links, status in groups:
        for pair in pairs:
            if frozenset(pair) not in cycle_keys:
                link_status[pair] = status
                edges |= links[pair].edges
    for cycle in (*(delta.cycle for delta in cycle_changes), *context_cycles):
        edges |= cycle.forward_edges | cycle.backward_edges

    tangle_changes, context_tangles = _tangle_changes(old, new, changes_only)
    for delta in tangle_changes:
        for link in delta.tangle.links:
            pair = (link.source, link.target)
            unchanged = pair in old_links and pair in new_links
            if (
                unchanged
                and pair not in link_status
                and frozenset(pair) not in cycle_keys
            ):
                link_status[pair] = ChangeStatus.CONTEXT
                edges |= new_links[pair].edges

    kinds = {node.id: node.kind for node in (*old.nodes, *new.nodes)}
    shown = _node_status(old, new, edges, everything=not changes_only)
    node_status = {_drawn_id(node_id, shown): st for node_id, st in shown.items()}
    graph = BlueprintGraph(
        nodes=[
            Node(id=_drawn_id(node_id, shown), kind=kinds[node_id])
            for node_id in sorted(shown)
        ],
        edges=frozenset(edges),
    )
    # Groups only: cycle detection over this partial edge set would report a
    # resolved cycle as present. Cycles live in ``cycle_changes`` and
    # ``context_cycles``.
    graph.groups = GroupAnalyzer.build(graph)
    return GraphDiff(
        graph=graph,
        node_status=node_status,
        link_status=dict(sorted(link_status.items())),
        cycle_changes=cycle_changes,
        context_cycles=context_cycles,
        tangle_changes=tangle_changes,
        context_tangles=context_tangles,
    )


def _tangle_changes(
    old: BlueprintGraph,
    new: BlueprintGraph,
    changes_only: bool,
) -> tuple[tuple[TangleDelta, ...], tuple[Tangle, ...]]:
    """Tangles that appeared or went, and — unless ``changes_only`` — the rest."""
    old_tangles = {frozenset(t.members): t for t in old.tangles}
    new_tangles = {frozenset(t.members): t for t in new.tangles}
    deltas = [
        TangleDelta(CycleChange.NEW, new_tangles[key])
        for key in new_tangles.keys() - old_tangles.keys()
    ] + [
        TangleDelta(CycleChange.RESOLVED, old_tangles[key])
        for key in old_tangles.keys() - new_tangles.keys()
    ]
    context: tuple[Tangle, ...] = ()
    if not changes_only:
        context = tuple(
            sorted(
                (new_tangles[key] for key in new_tangles.keys() & old_tangles.keys()),
                key=lambda t: t.members,
            ),
        )
    ordered = sorted(deltas, key=lambda d: (d.tangle.members, d.change.value))
    return tuple(ordered), context


def _drawn_id(node_id: str, shown: Iterable[str]) -> str:
    """``node_id``, or its shadowed form when another shown node lies under it.

    Within one graph no node lies under another (the extractor keeps leaves),
    but a diff joins two: a module ``pkg.py`` removed and a package ``pkg/``
    added with it are both drawn, and ``pkg`` cannot be both a class and the
    container of ``pkg.child``.
    """
    prefix = f"{node_id}."
    if any(other.startswith(prefix) for other in shown):
        return shadowed_id(node_id)
    return node_id


def _links_by_pair(graph: BlueprintGraph) -> dict[tuple[str, str], Link]:
    return {(link.source, link.target): link for link in graph.links}


def _cycles_by_key(graph: BlueprintGraph) -> dict[frozenset[str], Cycle]:
    return {_key(cycle): cycle for cycle in graph.cycles}


def _key(cycle: Cycle) -> frozenset[str]:
    return frozenset({cycle.endpoint_from, cycle.endpoint_to})


def _cycle_changes(
    old: BlueprintGraph,
    new: BlueprintGraph,
    new_pairs: Iterable[tuple[str, str]],
) -> tuple[CycleDelta, ...]:
    old_cycles, new_cycles = _cycles_by_key(old), _cycles_by_key(new)
    deltas = [
        CycleDelta(CycleChange.NEW, new_cycles[key])
        for key in new_cycles.keys() - old_cycles.keys()
    ]
    surviving = set(new_pairs)
    for key in old_cycles.keys() - new_cycles.keys():
        cycle = old_cycles[key]
        # At most one direction survives, or it would still be a cycle.
        remaining = next(
            (
                pair
                for pair in (
                    (cycle.endpoint_from, cycle.endpoint_to),
                    (cycle.endpoint_to, cycle.endpoint_from),
                )
                if pair in surviving
            ),
            None,
        )
        deltas.append(CycleDelta(CycleChange.RESOLVED, cycle, remaining))
    return tuple(
        sorted(
            deltas,
            key=lambda d: (d.cycle.endpoint_from, d.cycle.endpoint_to),
        ),
    )


def _node_status(
    old: BlueprintGraph,
    new: BlueprintGraph,
    edges: set[Edge],
    *,
    everything: bool,
) -> dict[str, ChangeStatus]:
    old_ids = {node.id for node in old.nodes}
    new_ids = {node.id for node in new.nodes}
    status = dict.fromkeys(new_ids - old_ids, ChangeStatus.ADDED)
    status.update(dict.fromkeys(old_ids - new_ids, ChangeStatus.REMOVED))
    unchanged = old_ids & new_ids
    if everything:
        status.update(dict.fromkeys(unchanged, ChangeStatus.CONTEXT))
        return dict(sorted(status.items()))
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
