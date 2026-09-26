from __future__ import annotations

from collections.abc import Mapping
from typing import Optional

from arch_blueprint.domain.graph import BlueprintGraph, MetricValue
from arch_blueprint.metrics._coupling import link_distances
from arch_blueprint.metrics.base import NO_OPTIONS, MetricOption, MetricOptions


class NamespaceDistanceMetric:
    """How far apart in the package tree the modules a connection joins sit.

    The distance dimension of the balanced-coupling model: the farther two
    components are, the more a change spanning both of them costs.

    Measured between **modules**, and reported as the farthest pair the
    connection aggregates -- not between the two names on the arrow. Those are
    siblings by construction, so measuring them would return 2 for every
    connection in every project. The wording below has to say so: a reader who
    takes "the two ends" to mean the arrow's ends cannot make sense of a 6 on a
    connection whose ends are two steps apart.
    """

    name = "namespace_distance"
    title = "distance"
    description = (
        "steps through the package tree between the farthest two modules "
        "this connection joins"
    )
    render: Optional[str] = "edge_label"
    #: No knobs: this metric measures, it does not judge.
    options: tuple[MetricOption, ...] = ()

    def compute(
        self,
        graph: BlueprintGraph,
        options: MetricOptions = NO_OPTIONS,
    ) -> Mapping[tuple[str, str], MetricValue]:
        return dict(link_distances(graph))
