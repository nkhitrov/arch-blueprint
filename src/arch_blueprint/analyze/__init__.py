from arch_blueprint.analyze.cycles import CycleAnalyzer
from arch_blueprint.analyze.groups import GroupAnalyzer
from arch_blueprint.domain.graph import BlueprintGraph, build_links


def analyze(graph: BlueprintGraph) -> BlueprintGraph:
    """Fill the structure derived from edges: cycles, tangles, then groups.

    One function for every place a graph comes from — a fresh extraction or a
    loaded snapshot — so the two can never derive it differently.
    """
    graph.cycles = CycleAnalyzer.detect_cycles(graph.links)
    graph.tangles = CycleAnalyzer.detect_tangles(
        graph.links,
        build_links(graph.facade_edges),
    )
    graph.groups = GroupAnalyzer.build(graph)
    return graph


__all__ = ["CycleAnalyzer", "GroupAnalyzer", "analyze"]
