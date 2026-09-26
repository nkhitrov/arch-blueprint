"""A graph snapshot: the one intermediate format every diagram is drawn from.

A snapshot holds only *primary* data — nodes, edges, package facade edges and
the metrics computed on them. ``links``, ``cycles``, ``tangles`` and ``groups``
are derived from the edges and are
re-derived on load, for the same reason ``BlueprintGraph.edges`` is a frozenset:
a stored copy of derived data is a copy that can disagree with its source.

Rendering and diffing read snapshots, never rendered diagrams, so a new output
format needs a renderer and nothing else.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final, cast

from arch_blueprint.analyze import analyze
from arch_blueprint.domain.graph import BlueprintGraph, Edge, MetricValue
from arch_blueprint.domain.node import Node, NodeKind
from arch_blueprint.extract.levels import LINK_LEVELS

SNAPSHOT_FORMAT: Final = "arch-blueprint-graph"
SNAPSHOT_VERSION: Final = 2

_EDGE_FIELDS: Final = ("source", "target", "source_endpoint", "target_endpoint")


class SnapshotError(ValueError):
    """The input is not a snapshot this version can read."""


@dataclass(frozen=True)
class Snapshot:
    """A loaded graph, the names of the metrics computed into it, its link level.

    The names are stored rather than inferred from the values: a graph with no
    links has no link-metric values, yet ``edge_weight`` was still computed and
    a render asking for it is not an error. The link level (``--links``) is
    stored for the same reason: edge endpoints alone cannot tell a module-level
    graph from a namespace-level one whose namespaces happen to be modules, and
    a diff of two graphs built at different levels compares nothing real.
    """

    graph: BlueprintGraph
    metrics: frozenset[str]
    links: str


def dump(graph: BlueprintGraph, metrics: Iterable[str], links: str) -> str:
    """Serialize ``graph`` deterministically: the same code gives the same bytes.

    Node order is kept as the extractor produced it — renderers draw nodes in
    that order, so sorting here would make a render from the snapshot differ
    from a direct one. Everything unordered is sorted.
    """
    document = {
        "format": SNAPSHOT_FORMAT,
        "version": SNAPSHOT_VERSION,
        "links": links,
        "metrics": sorted(metrics),
        "nodes": [{"id": node.id, "kind": node.kind.value} for node in graph.nodes],
        "edges": _dump_edges(graph.edges),
        "facade_edges": _dump_edges(graph.facade_edges),
        "node_metrics": {
            node_id: dict(sorted(values.items()))
            for node_id, values in sorted(graph.node_metrics.items())
        },
        "link_metrics": [
            {"source": source, "target": target, "values": dict(sorted(values.items()))}
            for (source, target), values in sorted(graph.link_metrics.items())
        ],
    }
    return json.dumps(document, indent=2, ensure_ascii=False)


def load(text: str) -> Snapshot:
    """Parse and validate a snapshot, then re-derive cycles and groups."""
    try:
        document = json.loads(text)
    except json.JSONDecodeError as error:
        msg = f"not a JSON document: {error}"
        raise SnapshotError(msg) from error
    root = _mapping(document, "snapshot")
    if root.get("format") != SNAPSHOT_FORMAT:
        msg = f"not an arch-blueprint snapshot (format {root.get('format')!r})"
        raise SnapshotError(msg)
    if root.get("version") != SNAPSHOT_VERSION:
        msg = (
            f"unsupported snapshot version {root.get('version')!r}; "
            f"this arch-blueprint reads version {SNAPSHOT_VERSION}"
        )
        raise SnapshotError(msg)

    graph = BlueprintGraph(
        nodes=[_node(item) for item in _list(root, "nodes")],
        edges=frozenset(_edge(item) for item in _list(root, "edges")),
        facade_edges=frozenset(_edge(item) for item in _list(root, "facade_edges")),
    )
    for node_id, values in _mapping(
        _field(root, "node_metrics"),
        "node_metrics",
    ).items():
        graph.node_metrics[node_id] = _metric_values(values, f"node_metrics.{node_id}")
    for item in _list(root, "link_metrics"):
        entry = _mapping(item, "link_metrics[]")
        pair = (_str(entry, "source"), _str(entry, "target"))
        graph.link_metrics[pair] = _metric_values(
            _field(entry, "values"),
            f"link_metrics.{pair[0]}->{pair[1]}",
        )
    metrics = frozenset(_as_str(name, "metrics[]") for name in _list(root, "metrics"))
    links = _str(root, "links")
    if links not in LINK_LEVELS:
        msg = f"unknown link level {links!r}"
        raise SnapshotError(msg)
    return Snapshot(graph=analyze(graph), metrics=metrics, links=links)


def _dump_edges(edges: frozenset[Edge]) -> list[dict[str, str]]:
    return [
        {name: getattr(edge, name) for name in _EDGE_FIELDS}
        for edge in sorted(
            edges,
            key=lambda e: tuple(getattr(e, name) for name in _EDGE_FIELDS),
        )
    ]


def _node(item: object) -> Node:
    entry = _mapping(item, "nodes[]")
    kind = _str(entry, "kind")
    try:
        return Node(id=_str(entry, "id"), kind=NodeKind(kind))
    except ValueError as error:
        msg = f"unknown node kind {kind!r}"
        raise SnapshotError(msg) from error


def _edge(item: object) -> Edge:
    entry = _mapping(item, "edges[]")
    return Edge(**{name: _str(entry, name) for name in _EDGE_FIELDS})


def _metric_values(value: object, where: str) -> dict[str, MetricValue]:
    values: dict[str, MetricValue] = {}
    for name, metric in _mapping(value, where).items():
        # bool is an int to isinstance, but no metric produces one.
        if isinstance(metric, bool) or not isinstance(metric, (int, float, str)):
            msg = f"{where}.{name}: expected a number or a string"
            raise SnapshotError(msg)
        values[name] = metric
    return values


def _field(entry: Mapping[str, object], key: str) -> object:
    if key not in entry:
        msg = f"missing field {key!r}"
        raise SnapshotError(msg)
    return entry[key]


def _mapping(value: object, where: str) -> dict[str, object]:
    if not isinstance(value, dict):
        msg = f"{where}: expected an object"
        raise SnapshotError(msg)
    return cast("dict[str, object]", value)


def _list(entry: Mapping[str, object], key: str) -> list[object]:
    value = _field(entry, key)
    if not isinstance(value, list):
        msg = f"{key}: expected a list"
        raise SnapshotError(msg)
    return cast("list[object]", value)


def _str(entry: Mapping[str, object], key: str) -> str:
    return _as_str(_field(entry, key), key)


def _as_str(value: object, where: str) -> str:
    if not isinstance(value, str):
        msg = f"{where}: expected a string"
        raise SnapshotError(msg)
    return value
