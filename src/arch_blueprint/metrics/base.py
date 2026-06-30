from __future__ import annotations

from collections.abc import Mapping
from typing import Optional, Protocol, runtime_checkable

from arch_blueprint.domain.graph import BlueprintGraph, MetricValue
from arch_blueprint.domain.node import NodeKind


@runtime_checkable
class BlockBuilder(Protocol):
    """Format-neutral helper a metric uses to describe its rendered block.

    Each renderer provides a concrete builder so metrics stay format-agnostic
    while still being self-contained.
    """

    def row(self, label: str, value: str) -> str:
        """Render a single ``label: value`` row in the target format."""
        ...


@runtime_checkable
class Metric(Protocol):
    """A self-contained metric: it computes its value and renders its own block.

    Adding a metric is one new class registered in :func:`default_registry` — the
    extractor and renderer cores never change.
    """

    name: str
    applies_to: frozenset[NodeKind]

    def compute(self, graph: BlueprintGraph) -> Mapping[str, MetricValue]:
        """Return ``{node id: value}`` for every node this metric applies to."""
        ...

    def render_block(self, value: MetricValue, builder: BlockBuilder) -> Optional[str]:
        """Render this metric for one node, or ``None`` to render nothing inline."""
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
        """Compute every registered metric and store results on the graph."""
        for metric in self._metrics.values():
            for node_id, value in metric.compute(graph).items():
                graph.node_metrics.setdefault(node_id, {})[metric.name] = value
