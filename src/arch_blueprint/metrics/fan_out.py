from __future__ import annotations

from collections.abc import Mapping
from typing import Optional

from arch_blueprint.domain.graph import BlueprintGraph, MetricValue
from arch_blueprint.domain.node import NodeKind
from arch_blueprint.metrics.base import BlockBuilder

_ALL_KINDS = frozenset(NodeKind)


class FanOutMetric:
    """Number of distinct nodes a given node depends on (outgoing edges)."""

    name = "fan_out"
    applies_to = _ALL_KINDS

    def compute(self, graph: BlueprintGraph) -> Mapping[str, MetricValue]:
        counts: dict[str, MetricValue] = {node.id: 0 for node in graph.nodes}
        for edge in graph.edges:
            if edge.source in counts:
                counts[edge.source] = int(counts[edge.source]) + 1
        return counts

    def render_block(self, value: MetricValue, builder: BlockBuilder) -> Optional[str]:
        return builder.row("fan_out", str(value))
