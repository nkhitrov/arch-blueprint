from __future__ import annotations

from collections.abc import Mapping
from typing import Optional

from arch_blueprint.domain.graph import BlueprintGraph, MetricValue
from arch_blueprint.metrics._degrees import degree_counts
from arch_blueprint.metrics.base import ALL_KINDS


class FanInMetric:
    """Number of distinct nodes that depend on a given node (incoming edges)."""

    name = "fan_in"
    applies_to = ALL_KINDS
    render: Optional[str] = "text_row"

    def compute(self, graph: BlueprintGraph) -> Mapping[str, MetricValue]:
        fan_in, _ = degree_counts(graph)
        return fan_in
