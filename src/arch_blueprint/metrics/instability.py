from __future__ import annotations

from collections.abc import Mapping
from typing import Optional

from arch_blueprint.domain.graph import BlueprintGraph, MetricValue
from arch_blueprint.domain.node import NodeKind
from arch_blueprint.metrics.base import BlockBuilder

_ALL_KINDS = frozenset(NodeKind)


class InstabilityMetric:
    """Martin instability ``fan_out / (fan_in + fan_out)`` in ``[0, 1]``.

    0 = maximally stable (only depended upon), 1 = maximally unstable (only
    depends on others).
    """

    name = "instability"
    applies_to = _ALL_KINDS

    def compute(self, graph: BlueprintGraph) -> Mapping[str, MetricValue]:
        fan_in: dict[str, int] = {node.id: 0 for node in graph.nodes}
        fan_out: dict[str, int] = {node.id: 0 for node in graph.nodes}
        for edge in graph.edges:
            if edge.source in fan_out:
                fan_out[edge.source] += 1
            if edge.target in fan_in:
                fan_in[edge.target] += 1

        result: dict[str, MetricValue] = {}
        for node in graph.nodes:
            total = fan_in[node.id] + fan_out[node.id]
            result[node.id] = round(fan_out[node.id] / total, 2) if total else 0.0
        return result

    def render_block(self, value: MetricValue, builder: BlockBuilder) -> Optional[str]:
        return builder.row("instability", str(value))
