from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from typing import TypeVar

from arch_blueprint.analyze.groups import GroupAnalyzer
from arch_blueprint.diff.model import (
    ChangeStatus,
    CycleChange,
    CycleDelta,
    GraphDiff,
    MetricChange,
    MetricChanges,
    shadowed_id,
)
from arch_blueprint.domain.graph import (
    BlueprintGraph,
    Cycle,
    Edge,
    Link,
    MetricValue,
    cycle_metric_values,
)
from arch_blueprint.domain.node import Node


def diff_graphs(
    old: BlueprintGraph,
    new: BlueprintGraph,
    *,
    changes_only: bool = False,
    metrics: Collection[str] = (),
) -> GraphDiff:
    """Compare two analyzed graphs at the level a diagram shows them.

    Links compare by namespace pair, directed, so ``A→B`` becoming ``A↔B`` is a
    new cycle rather than nothing. A change to the individual imports inside a
    link present on both sides is not a link change.

    The changes are drawn against the whole of both graphs: every node, link and
    cycle that did not change is context. With ``changes_only`` the context is
    exact rather than "everything": the unchanged nodes the changed links'
    imports actually connect, and no unchanged link.

    ``metrics`` names the metrics to compare, read from each side's computed
    values: every shown node and connection gets a :class:`MetricChange` per
    metric it has a value for. A value that differs is a change too — with
    ``changes_only``, a node, link or cycle whose value changed is shown as
    context, as are the nodes such a link connects. Without ``metrics`` the
    diff is structure only.
    """
    old_links = _links_by_pair(old)
    new_links = _links_by_pair(new)
    cycle_changes = _cycle_changes(old, new, new_links.keys())
    old_cycles, new_cycles = _cycles_by_key(old), _cycles_by_key(new)
    both_cycles = sorted(
        (new_cycles[key] for key in new_cycles.keys() & old_cycles.keys()),
        key=lambda c: (c.namespace_from, c.namespace_to),
    )
    context_cycles = tuple(
        cycle
        for cycle in both_cycles
        if not changes_only or _changed(_cycle_values(old, new, cycle, metrics))
    )
    # Every pair a cycle connection stands for, changed or not.
    cycle_keys = {_key(delta.cycle) for delta in cycle_changes}
    cycle_keys |= {_key(cycle) for cycle in both_cycles}

    both_links = new_links.keys() & old_links.keys()
    link_status: dict[tuple[str, str], ChangeStatus] = {}
    edges: set[Edge] = set()
    groups = [
        (new_links.keys() - old_links.keys(), new_links, ChangeStatus.ADDED),
        (old_links.keys() - new_links.keys(), old_links, ChangeStatus.REMOVED),
        (
            {
                pair
                for pair in both_links
                if not changes_only
                or _changed(_values(old.link_metrics, new.link_metrics, pair, metrics))
            },
            new_links,
            ChangeStatus.CONTEXT,
        ),
    ]
    for pairs, links, status in groups:
        for pair in pairs:
            if frozenset(pair) not in cycle_keys:
                link_status[pair] = status
                edges |= links[pair].edges
    for cycle in (*(delta.cycle for delta in cycle_changes), *context_cycles):
        edges |= cycle.forward_edges | cycle.backward_edges

    kinds = {node.id: node.kind for node in (*old.nodes, *new.nodes)}
    shown = _node_status(
        old,
        new,
        edges,
        everything=not changes_only,
        metrics=metrics,
    )
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
        node_metrics=_non_empty(
            (
                _drawn_id(node_id, shown),
                _values(old.node_metrics, new.node_metrics, node_id, metrics),
            )
            for node_id in shown
        ),
        link_metrics=_non_empty(
            (pair, _values(old.link_metrics, new.link_metrics, pair, metrics))
            for pair in link_status
        ),
        cycle_metrics=_non_empty(
            (_key(cycle), _cycle_values(old, new, cycle, metrics))
            for cycle in (*(delta.cycle for delta in cycle_changes), *context_cycles)
        ),
    )


_Key = TypeVar("_Key", str, tuple[str, str], frozenset[str])


def _values(
    old: Mapping[_Key, Mapping[str, MetricValue]],
    new: Mapping[_Key, Mapping[str, MetricValue]],
    key: _Key,
    metrics: Collection[str],
) -> dict[str, MetricChange]:
    """Each named metric's value for ``key`` on both sides, where either has one."""
    old_values, new_values = old.get(key, {}), new.get(key, {})
    return {
        name: MetricChange(old_values.get(name), new_values.get(name))
        for name in metrics
        if name in old_values or name in new_values
    }


def _cycle_values(
    old: BlueprintGraph,
    new: BlueprintGraph,
    cycle: Cycle,
    metrics: Collection[str],
) -> dict[str, MetricChange]:
    """A cycle connection's values on both sides, directions combined.

    Oriented as ``cycle`` is, on both sides; on a side where the pair is not a
    cycle the one direction there is its value, as a plain arrow's would be. So
    a new cycle reads ``2 → 2/1`` and a resolved one ``3/1 → 4``.
    """
    pair = (cycle.namespace_from, cycle.namespace_to)
    key = _key(cycle)
    return _values(
        {key: cycle_metric_values(old.link_metrics, *pair)},
        {key: cycle_metric_values(new.link_metrics, *pair)},
        key,
        metrics,
    )


def _changed(values: Mapping[str, MetricChange]) -> bool:
    return any(change.changed for change in values.values())


def _non_empty(
    items: Iterable[tuple[_Key, dict[str, MetricChange]]],
) -> dict[_Key, MetricChanges]:
    return {key: values for key, values in items if values}


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
    return {
        (link.source_namespace, link.target_namespace): link for link in graph.links
    }


def _cycles_by_key(graph: BlueprintGraph) -> dict[frozenset[str], Cycle]:
    return {_key(cycle): cycle for cycle in graph.cycles}


def _key(cycle: Cycle) -> frozenset[str]:
    return frozenset({cycle.namespace_from, cycle.namespace_to})


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
                    (cycle.namespace_from, cycle.namespace_to),
                    (cycle.namespace_to, cycle.namespace_from),
                )
                if pair in surviving
            ),
            None,
        )
        deltas.append(CycleDelta(CycleChange.RESOLVED, cycle, remaining))
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
    *,
    everything: bool,
    metrics: Collection[str],
) -> dict[str, ChangeStatus]:
    old_ids = {node.id for node in old.nodes}
    new_ids = {node.id for node in new.nodes}
    status = dict.fromkeys(new_ids - old_ids, ChangeStatus.ADDED)
    status.update(dict.fromkeys(old_ids - new_ids, ChangeStatus.REMOVED))
    unchanged = old_ids & new_ids
    if everything:
        status.update(dict.fromkeys(unchanged, ChangeStatus.CONTEXT))
        return dict(sorted(status.items()))
    for node_id in unchanged:
        values = _values(old.node_metrics, new.node_metrics, node_id, metrics)
        if _changed(values):
            status[node_id] = ChangeStatus.CONTEXT
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
