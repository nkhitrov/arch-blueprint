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


class FanInMetric:
    """Number of distinct nodes that depend on a given node (incoming edges)."""

    name = "fan_in"
    title = "fan-in"
    description = "how many modules depend on this one"
    applies_to = ALL_KINDS
    render: Optional[str] = "text_row"
    #: No knobs: this metric measures, it does not judge.
    options: tuple[MetricOption, ...] = ()

    def compute(
        self,
        graph: BlueprintGraph,
        options: MetricOptions = NO_OPTIONS,
    ) -> Mapping[str, MetricValue]:
        fan_in, _ = degree_counts(graph)
        return fan_in
