from __future__ import annotations

from collections.abc import Mapping
from typing import Optional

from arch_blueprint.domain.graph import BlueprintGraph, MetricValue
from arch_blueprint.metrics._coupling import link_distances
from arch_blueprint.metrics.base import NO_OPTIONS, MetricOption, MetricOptions


class NamespaceDistanceMetric:
    """How far apart in the package tree the two ends of a link sit.

    The distance dimension of the balanced-coupling model: the farther two
    components are, the more a change spanning both of them costs.
    """

    name = "namespace_distance"
    title = "distance"
    description = "steps through the package tree between the two ends"
    render: Optional[str] = "edge_label"
    #: No knobs: this metric measures, it does not judge.
    options: tuple[MetricOption, ...] = ()

    def compute(
        self,
        graph: BlueprintGraph,
        options: MetricOptions = NO_OPTIONS,
    ) -> Mapping[tuple[str, str], MetricValue]:
        return dict(link_distances(graph))
