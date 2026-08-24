from __future__ import annotations

from collections.abc import Mapping
from typing import Optional, Protocol, Union, cast, runtime_checkable

from arch_blueprint.domain.graph import BlueprintGraph, MetricValue
from arch_blueprint.domain.node import NodeKind
from arch_blueprint.metrics.render import MetricTarget

# A node id, or a ``(source_namespace, target_namespace)`` pair for links.
MetricKey = Union[str, tuple[str, str]]


@runtime_checkable
class Metric(Protocol):
    """A self-contained metric plugin: it computes its value(s) over the graph.

    A metric carries *no* rendering logic — it names a render plugin (``render``)
    that the renderer resolves and invokes. Adding a metric is one new class
    registered in :func:`default_registry`; the extractor and renderer cores
    never change.
    """

    name: str
    target: MetricTarget
    applies_to: frozenset[NodeKind]
    render: Optional[str]

    def compute(self, graph: BlueprintGraph) -> Mapping[MetricKey, MetricValue]:
        """Return ``{key: value}``: node id for NODE, ``(src, tgt)`` for LINK."""
        ...


class MetricRegistry:
    """Registration-based lookup of metrics, keyed by name."""

    def __init__(self) -> None:
        self._metrics: dict[str, Metric] = {}

    def register(self, metric: Metric) -> None:
        self._metrics[metric.name] = metric

    def get(self, name: str) -> Optional[Metric]:
        return self._metrics.get(name)

    def all(self) -> list[Metric]:
        return list(self._metrics.values())

    def compute_all(self, graph: BlueprintGraph) -> None:
        """Compute every registered metric and store results on the graph.

        Results are routed by the metric's ``target``: NODE metrics land in
        ``graph.node_metrics`` (keyed by node id), LINK metrics in
        ``graph.link_metrics`` (keyed by namespace pair).
        """
        for metric in self._metrics.values():
            results = metric.compute(graph)
            if metric.target is MetricTarget.NODE:
                for key, value in results.items():
                    node_id = cast("str", key)
                    graph.node_metrics.setdefault(node_id, {})[metric.name] = value
            else:
                for key, value in results.items():
                    pair = cast("tuple[str, str]", key)
                    graph.link_metrics.setdefault(pair, {})[metric.name] = value
