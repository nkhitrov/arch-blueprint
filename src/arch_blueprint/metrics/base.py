from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Protocol, Union, runtime_checkable

from arch_blueprint.domain.graph import BlueprintGraph, MetricValue
from arch_blueprint.domain.node import NodeKind


@dataclass(frozen=True)
class MetricOption:
    """One number a metric takes from the caller, declared so it can be checked.

    Declared rather than read loosely from a bag: a misspelled key is then a
    reported error instead of a threshold that silently never applies.
    """

    name: str
    description: str


#: One metric's options, already parsed and validated: ``{option name: number}``.
#: An option the caller did not give is absent, never defaulted here — what a
#: missing value means belongs to the metric.
MetricOptions = Mapping[str, float]

#: Every metric's options, keyed by metric name.
AllMetricOptions = Mapping[str, MetricOptions]

#: What a metric with no options declares, and what one receives when given none.
NO_OPTIONS: MetricOptions = {}


class MetricTarget(Enum):
    """What a metric is computed and rendered on."""

    NODE = "node"
    LINK = "link"


#: Every node kind there is — the default for a metric that cares about none.
ALL_KINDS = frozenset(NodeKind)


@runtime_checkable
class NodeMetric(Protocol):
    """A metric computed per node, keyed by node id.

    A metric carries *no* rendering logic — it names a render plugin (``render``)
    that the renderer resolves and invokes. Adding one is a new class registered
    in :func:`default_registry`; the extractor and renderer cores never change.
    """

    name: str
    title: str
    description: str
    applies_to: frozenset[NodeKind]
    render: Optional[str]
    options: tuple[MetricOption, ...]

    def compute(
        self,
        graph: BlueprintGraph,
        options: MetricOptions,
    ) -> Mapping[str, MetricValue]:
        """Return ``{node id: value}``, or nothing when it has nothing to say."""
        ...


@runtime_checkable
class LinkMetric(Protocol):
    """A metric computed per link, keyed by ``(source_ns, target_ns)``.

    There is no ``applies_to``: a link connects namespaces, not node kinds.
    """

    name: str
    title: str
    description: str
    render: Optional[str]
    options: tuple[MetricOption, ...]

    def compute(
        self,
        graph: BlueprintGraph,
        options: MetricOptions,
    ) -> Mapping[tuple[str, str], MetricValue]:
        """Return ``{(source, target) namespace pair: value}``, or nothing."""
        ...


Metric = Union[NodeMetric, LinkMetric]


class MetricRegistry:
    """Registration-based lookup of metrics, keyed by name.

    Node and link metrics are held apart rather than tagged with a target field:
    the collection a metric sits in *is* its target, which is what lets results
    be routed to the right side of the graph without a cast.
    """

    def __init__(self) -> None:
        self._node: dict[str, NodeMetric] = {}
        self._link: dict[str, LinkMetric] = {}

    def register_node(self, metric: NodeMetric) -> None:
        self._node[metric.name] = metric

    def register_link(self, metric: LinkMetric) -> None:
        self._link[metric.name] = metric

    def node_metric(self, name: str) -> Optional[NodeMetric]:
        return self._node.get(name)

    def link_metric(self, name: str) -> Optional[LinkMetric]:
        return self._link.get(name)

    def names(self) -> frozenset[str]:
        return frozenset(self._node) | frozenset(self._link)

    def options_of(self, name: str) -> tuple[MetricOption, ...]:
        """The options the named metric declares; empty for an unknown name."""
        metric = self._node.get(name) or self._link.get(name)
        return () if metric is None else metric.options

    def compute(
        self,
        graph: BlueprintGraph,
        names: Optional[Iterable[str]] = None,
        options: Optional[AllMetricOptions] = None,
    ) -> None:
        """Compute the named metrics (all of them by default) onto ``graph``.

        NODE results land in ``graph.node_metrics`` (keyed by node id), LINK
        results in ``graph.link_metrics`` (keyed by namespace pair). Each metric
        is handed its own options and nobody else's.
        """
        wanted = self.names() if names is None else frozenset(names)
        given = options or {}
        for name, node_metric in self._node.items():
            if name not in wanted:
                continue
            values = node_metric.compute(graph, given.get(name, NO_OPTIONS))
            for node_id, value in values.items():
                graph.node_metrics.setdefault(node_id, {})[name] = value
        for name, link_metric in self._link.items():
            if name not in wanted:
                continue
            link_values = link_metric.compute(graph, given.get(name, NO_OPTIONS))
            for pair, value in link_values.items():
                graph.link_metrics.setdefault(pair, {})[name] = value

    def compute_all(self, graph: BlueprintGraph) -> None:
        """Compute every registered metric onto ``graph``."""
        self.compute(graph, None)
