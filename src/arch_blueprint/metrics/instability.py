from __future__ import annotations

from collections.abc import Mapping
from typing import Optional

from arch_blueprint.domain.graph import BlueprintGraph, MetricValue
from arch_blueprint.metrics._degrees import degree_counts
from arch_blueprint.metrics.base import (
    ALL_KINDS,
    NO_OPTIONS,
    MetricOption,
    MetricOptions,
)


class InstabilityMetric:
    """Martin instability ``fan_out / (fan_in + fan_out)`` in ``[0, 1]``.

    0 = maximally stable (only depended upon), 1 = maximally unstable (only
    depends on others).
    """

    name = "instability"
    title = "instability"
    description = "fan-out / (fan-in + fan-out): 0 is stable, 1 is unstable"
    applies_to = ALL_KINDS
    render: Optional[str] = "text_row"
    #: No knobs: this metric measures, it does not judge.
    options: tuple[MetricOption, ...] = ()

    def compute(
        self,
        graph: BlueprintGraph,
        options: MetricOptions = NO_OPTIONS,
    ) -> Mapping[str, MetricValue]:
        fan_in, fan_out = degree_counts(graph)
        result: dict[str, MetricValue] = {}
        for node in graph.nodes:
            total = fan_in[node.id] + fan_out[node.id]
            result[node.id] = round(fan_out[node.id] / total, 2) if total else 0.0
        return result
