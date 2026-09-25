from arch_blueprint.analyze.cycles import CycleAnalyzer
from arch_blueprint.analyze.groups import GroupAnalyzer
from arch_blueprint.domain.graph import BlueprintGraph


def analyze(graph: BlueprintGraph) -> BlueprintGraph:
    """Fill the structure derived from edges: cycles, then the groups around them.

    One function for every place a graph comes from — a fresh extraction or a
    loaded snapshot — so the two can never derive it differently.
    """
    graph.cycles = CycleAnalyzer.detect_cycles(graph.links)
    graph.groups = GroupAnalyzer.build(graph)
    return graph


__all__ = ["CycleAnalyzer", "GroupAnalyzer", "analyze"]
