from __future__ import annotations

from collections.abc import Mapping
from typing import Optional

from arch_blueprint.domain.graph import BlueprintGraph, MetricValue
from arch_blueprint.metrics.base import ALL_KINDS


class DepthMetric:
    """Dotted-path depth of a node. Drives node fill color; never displayed."""

    name = "depth"
    applies_to = ALL_KINDS
    render: Optional[str] = None

    def compute(self, graph: BlueprintGraph) -> Mapping[str, MetricValue]:
        return {node.id: len(node.id.split(".")) for node in graph.nodes}
