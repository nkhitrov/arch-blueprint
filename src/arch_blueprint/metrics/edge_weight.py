from __future__ import annotations

from collections.abc import Mapping
from typing import Optional

from arch_blueprint.domain.graph import BlueprintGraph, MetricValue
from arch_blueprint.domain.node import NodeKind
from arch_blueprint.metrics.base import MetricKey
from arch_blueprint.metrics.render import MetricTarget


class EdgeWeightMetric:
    """Number of underlying node edges aggregated into a namespace link.

    A LINK metric: it labels each connection with how many imports it represents.
    """

    name = "edge_weight"
    target = MetricTarget.LINK
    applies_to: frozenset[NodeKind] = frozenset()
    render: Optional[str] = "edge_label"

    def compute(self, graph: BlueprintGraph) -> Mapping[MetricKey, MetricValue]:
        return {
            (link.source_namespace, link.target_namespace): len(link.edges)
            for link in graph.links
        }
