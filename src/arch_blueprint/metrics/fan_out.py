from __future__ import annotations

from collections.abc import Mapping
from typing import Optional

from arch_blueprint.domain.graph import BlueprintGraph, MetricValue
from arch_blueprint.metrics._degrees import degree_counts
from arch_blueprint.metrics.base import ALL_KINDS


class FanOutMetric:
    """Number of distinct nodes a given node depends on (outgoing edges)."""

    name = "fan_out"
    applies_to = ALL_KINDS
    render: Optional[str] = "text_row"

    def compute(self, graph: BlueprintGraph) -> Mapping[str, MetricValue]:
        _, fan_out = degree_counts(graph)
        return fan_out
