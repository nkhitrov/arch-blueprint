from __future__ import annotations

from arch_blueprint.domain.graph import BlueprintGraph


def degree_counts(graph: BlueprintGraph) -> tuple[dict[str, int], dict[str, int]]:
    """Return ``(fan_in, fan_out)`` edge counts per node id.

    Three metrics need the same two counters, so the traversal lives in one place
    instead of being repeated (and, for instability, repeated twice over).
    """
    fan_in = {node.id: 0 for node in graph.nodes}
    fan_out = {node.id: 0 for node in graph.nodes}
    for edge in graph.edges:
        if edge.source in fan_out:
            fan_out[edge.source] += 1
        if edge.target in fan_in:
            fan_in[edge.target] += 1
    return fan_in, fan_out
