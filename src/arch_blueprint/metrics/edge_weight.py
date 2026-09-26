from __future__ import annotations

from collections.abc import Mapping
from typing import Optional

from arch_blueprint.domain.graph import BlueprintGraph, MetricValue


class EdgeWeightMetric:
    """Number of underlying node edges aggregated into a link.

    A link metric: it labels each connection with how many imports it represents.
    """

    name = "edge_weight"
    description = "how many module imports a connection stands for"
    render: Optional[str] = "edge_label"

    def compute(
        self,
        graph: BlueprintGraph,
    ) -> Mapping[tuple[str, str], MetricValue]:
        return {(link.source, link.target): len(link.edges) for link in graph.links}
