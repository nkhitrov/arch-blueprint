from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Union

from arch_blueprint.domain.node import Node

MetricValue = Union[int, float, str]


@dataclass(frozen=True)
class Edge:
    """A single directed dependency between two nodes, with namespace context.

    ``source``/``target`` are node ids; ``source_namespace``/``target_namespace``
    are the grouping namespaces the link layer aggregates on.
    """

    source: str
    target: str
    source_namespace: str
    target_namespace: str


@dataclass(frozen=True)
class Link:
    """A namespace-level link aggregating all contributing node edges."""

    source_namespace: str
    target_namespace: str
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
    """A bidirectional dependency between two namespaces with both directions."""

    namespace_from: str
    namespace_to: str
    forward_edges: frozenset[Edge]
    backward_edges: frozenset[Edge]


def build_links(edges: frozenset[Edge]) -> set[Link]:
    """Aggregate edges into one Link per (source_namespace, target_namespace)."""
    edges_by_pair: dict[tuple[str, str], set[Edge]] = defaultdict(set)
    for edge in edges:
        edges_by_pair[(edge.source_namespace, edge.target_namespace)].add(edge)
    return {
        Link(source_namespace=src, target_namespace=tgt, edges=frozenset(group))
        for (src, tgt), group in edges_by_pair.items()
    }


@dataclass
class BlueprintGraph:
    """The renderable graph: nodes, their edges, derived links, and metrics.

    Metrics are stored beside identity (keyed by node id / namespace pair) so new
    metrics never change node/edge hashing or the extractor.

    ``links``, ``cycles`` and ``groups`` are derived: ``links`` is aggregated
    from ``edges`` once at construction, the other two are filled by the analyze
    step of the pipeline. ``edges`` is a frozenset so those derivations cannot
    silently go stale behind a mutation.
    """

    nodes: list[Node]
    edges: frozenset[Edge]
    links: set[Link] = field(init=False)
    cycles: list[Cycle] = field(init=False, default_factory=list)
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
