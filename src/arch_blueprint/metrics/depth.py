from __future__ import annotations

from collections.abc import Mapping
from typing import Optional

from arch_blueprint.domain.graph import BlueprintGraph, MetricValue
from arch_blueprint.domain.node import NodeKind
from arch_blueprint.metrics.base import MetricKey
from arch_blueprint.metrics.render import MetricTarget

_ALL_KINDS = frozenset(NodeKind)


class DepthMetric:
    """Dotted-path depth of a node. Drives node fill color; never displayed."""

    name = "depth"
    target = MetricTarget.NODE
    applies_to = _ALL_KINDS
    render: Optional[str] = None

    def compute(self, graph: BlueprintGraph) -> Mapping[MetricKey, MetricValue]:
        return {node.id: len(node.id.split(".")) for node in graph.nodes}
