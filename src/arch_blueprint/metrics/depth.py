from __future__ import annotations

from collections.abc import Mapping
from typing import Optional

from arch_blueprint.domain.graph import BlueprintGraph, MetricValue
from arch_blueprint.metrics.base import (
    ALL_KINDS,
    NO_OPTIONS,
    MetricOption,
    MetricOptions,
)


class DepthMetric:
    """Dotted-path depth of a node. Drives node fill color; never displayed."""

    name = "depth"
    title = "depth"
    description = "how deep the module sits in the package tree"
    applies_to = ALL_KINDS
    render: Optional[str] = None
    #: No knobs: this metric measures, it does not judge.
    options: tuple[MetricOption, ...] = ()

    def compute(
        self,
        graph: BlueprintGraph,
        options: MetricOptions = NO_OPTIONS,
    ) -> Mapping[str, MetricValue]:
        return {node.id: len(node.id.split(".")) for node in graph.nodes}
