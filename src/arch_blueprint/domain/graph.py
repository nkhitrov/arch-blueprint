from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Union

from arch_blueprint.domain.node import Node

MetricValue = Union[int, float, str]


@dataclass(frozen=True)
class Edge:
    """A single directed import, with the endpoints it is drawn between.

    ``source`` is the importing node (or, for a facade edge, the importing
    package facade) and ``target`` the imported module, as they are.
    ``source_endpoint``/``target_endpoint`` are what the link layer aggregates
    on, chosen by the link level (``extract/levels.py``): the namespaces where
    the two paths diverge, or the nodes themselves.
    """

    source: str
    target: str
    source_endpoint: str
    target_endpoint: str


@dataclass(frozen=True)
class Link:
    """A link between two endpoints aggregating all contributing node edges."""

    source: str
    target: str
    edges: frozenset[Edge]


@dataclass(frozen=True)
class Group:
    """Nodes a renderer may draw inside one namespace container.

    A group exists only for a namespace that links point at but no node is named
    after; a namespace that *is* a node id needs no container, and wrapping a
    node in a container of its own name is a PlantUML syntax error.
    """

    namespace: str
    members: tuple[str, ...]


@dataclass(frozen=True)
class Cycle:
    """A bidirectional dependency between two link endpoints, with both directions."""

    endpoint_from: str
    endpoint_to: str
    forward_edges: frozenset[Edge]
    backward_edges: frozenset[Edge]


def cycle_metric_values(
    link_metrics: Mapping[tuple[str, str], Mapping[str, MetricValue]],
    endpoint_from: str,
    endpoint_to: str,
) -> dict[str, MetricValue]:
    """A cycle connection's link-metric values: both directions, forward first.

    A cycle is one drawn connection standing for two links, so a link metric has
    two values there. Showing one of them would freeze an arbitrary choice; they
    are combined as ``forward/backward``, matching the order the cycle's own
    detail block lists them in. A direction without a value leaves the other.
    """
    forward = link_metrics.get((endpoint_from, endpoint_to), {})
    backward = link_metrics.get((endpoint_to, endpoint_from), {})
    combined: dict[str, MetricValue] = {}
    for name in sorted({*forward, *backward}):
        if name in forward and name in backward:
            combined[name] = f"{forward[name]}/{backward[name]}"
        elif name in forward:
            combined[name] = forward[name]
        else:
            combined[name] = backward[name]
    return combined


@dataclass(frozen=True)
class Tangle:
    """Link endpoints that all reach one another: a cycle of any length.

    ``links`` are the drawn links inside it, sorted by pair. ``hidden_edges``
    are package facade imports (``BlueprintGraph.facade_edges``) that close it
    without an arrow of their own: importing ``pkg`` runs ``pkg/__init__.py``,
    so what it imports is on the cycle, yet drawing every facade's imports
    would bury the diagram.

    A lone mutual pair is a :class:`Cycle` — drawn as one two-headed arrow — and
    not also a tangle; a mutual pair inside a longer cycle is both.
    """

    members: tuple[str, ...]
    links: tuple[Link, ...]
    hidden_edges: frozenset[Edge]


def build_links(edges: frozenset[Edge]) -> set[Link]:
    """Aggregate edges into one Link per ``(source_endpoint, target_endpoint)``."""
    edges_by_pair: dict[tuple[str, str], set[Edge]] = defaultdict(set)
    for edge in edges:
        edges_by_pair[(edge.source_endpoint, edge.target_endpoint)].add(edge)
    return {
        Link(source=src, target=tgt, edges=frozenset(group))
        for (src, tgt), group in edges_by_pair.items()
    }


@dataclass
class BlueprintGraph:
    """The renderable graph: nodes, their edges, derived links, and metrics.

    Metrics are stored beside identity (keyed by node id / endpoint pair) so new
    metrics never change node/edge hashing or the extractor.

    ``facade_edges`` are the own imports of package facades above the nodes
    (their ``__init__.py``): primary data, never drawn, only closing cycles.

    ``links``, ``cycles``, ``tangles`` and ``groups`` are derived: ``links`` is
    aggregated from ``edges`` once at construction, the rest are filled by the
    analyze step of the pipeline. ``edges`` is a frozenset so those derivations
    cannot silently go stale behind a mutation.
    """

    nodes: list[Node]
    edges: frozenset[Edge]
    facade_edges: frozenset[Edge] = frozenset()
    links: set[Link] = field(init=False)
    cycles: list[Cycle] = field(init=False, default_factory=list)
    tangles: list[Tangle] = field(init=False, default_factory=list)
    groups: list[Group] = field(init=False, default_factory=list)
    node_metrics: dict[str, dict[str, MetricValue]] = field(
        init=False,
        default_factory=dict,
    )
    link_metrics: dict[tuple[str, str], dict[str, MetricValue]] = field(
        init=False,
        default_factory=dict,
    )

    def __post_init__(self) -> None:
        self.links = build_links(self.edges)
