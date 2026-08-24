from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import Enum
from typing import Optional, Protocol, Union, runtime_checkable

from arch_blueprint.domain.graph import BlueprintGraph, MetricValue
from arch_blueprint.domain.node import NodeKind


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
    applies_to: frozenset[NodeKind]
    render: Optional[str]

    def compute(self, graph: BlueprintGraph) -> Mapping[str, MetricValue]:
        """Return ``{node id: value}``."""
        ...


@runtime_checkable
class LinkMetric(Protocol):
    """A metric computed per link, keyed by ``(source_ns, target_ns)``.

    There is no ``applies_to``: a link connects namespaces, not node kinds.
    """

    name: str
    render: Optional[str]

    def compute(
        self,
        graph: BlueprintGraph,
    ) -> Mapping[tuple[str, str], MetricValue]:
        """Return ``{(source_namespace, target_namespace): value}``."""
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

    def compute(
        self,
        graph: BlueprintGraph,
        names: Optional[Iterable[str]] = None,
    ) -> None:
        """Compute the named metrics (all of them by default) onto ``graph``.

        NODE results land in ``graph.node_metrics`` (keyed by node id), LINK
        results in ``graph.link_metrics`` (keyed by namespace pair).
        """
        wanted = self.names() if names is None else frozenset(names)
        for name, node_metric in self._node.items():
            if name not in wanted:
                continue
            for node_id, value in node_metric.compute(graph).items():
                graph.node_metrics.setdefault(node_id, {})[name] = value
        for name, link_metric in self._link.items():
            if name not in wanted:
                continue
            for pair, value in link_metric.compute(graph).items():
                graph.link_metrics.setdefault(pair, {})[name] = value

    def compute_all(self, graph: BlueprintGraph) -> None:
        """Compute every registered metric onto ``graph``."""
        self.compute(graph, None)
