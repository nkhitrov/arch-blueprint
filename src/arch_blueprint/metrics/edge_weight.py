from __future__ import annotations

from collections.abc import Mapping
from typing import Optional

from arch_blueprint.domain.graph import BlueprintGraph, MetricValue
from arch_blueprint.metrics.base import NO_OPTIONS, MetricOption, MetricOptions


class EdgeWeightMetric:
    """Number of underlying node edges aggregated into a namespace link.

    A link metric: it labels each connection with how many imports it represents.
    """

    name = "edge_weight"
    title = "imports"
    description = "how many imports cross this boundary"
    render: Optional[str] = "edge_label"
    #: No knobs: this metric measures, it does not judge.
    options: tuple[MetricOption, ...] = ()

    def compute(
        self,
        graph: BlueprintGraph,
        options: MetricOptions = NO_OPTIONS,
    ) -> Mapping[tuple[str, str], MetricValue]:
        return {
            (link.source_namespace, link.target_namespace): len(link.edges)
            for link in graph.links
        }
