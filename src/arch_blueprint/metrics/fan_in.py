from __future__ import annotations

from collections.abc import Mapping
from typing import Optional

from arch_blueprint.domain.graph import BlueprintGraph, MetricValue
from arch_blueprint.domain.node import NodeKind
from arch_blueprint.metrics.base import BlockBuilder

_ALL_KINDS = frozenset(NodeKind)


class FanInMetric:
    """Number of distinct nodes that depend on a given node (incoming edges)."""

    name = "fan_in"
    applies_to = _ALL_KINDS

    def compute(self, graph: BlueprintGraph) -> Mapping[str, MetricValue]:
        counts: dict[str, MetricValue] = {node.id: 0 for node in graph.nodes}
        for edge in graph.edges:
            if edge.target in counts:
                counts[edge.target] = int(counts[edge.target]) + 1
        return counts

    def render_block(self, value: MetricValue, builder: BlockBuilder) -> Optional[str]:
        return builder.row("fan_in", str(value))
