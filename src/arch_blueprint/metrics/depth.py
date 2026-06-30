from __future__ import annotations

from collections.abc import Mapping
from typing import Optional

from arch_blueprint.domain.graph import BlueprintGraph, MetricValue
from arch_blueprint.domain.node import NodeKind
from arch_blueprint.metrics.base import BlockBuilder

_ALL_KINDS = frozenset(NodeKind)


class DepthMetric:
    """Dotted-path depth of a node. Drives node fill color, so it has no block."""

    name = "depth"
    applies_to = _ALL_KINDS

    def compute(self, graph: BlueprintGraph) -> Mapping[str, MetricValue]:
        return {node.id: len(node.id.split(".")) for node in graph.nodes}

    def render_block(self, value: MetricValue, builder: BlockBuilder) -> Optional[str]:
        return None
