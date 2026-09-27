from arch_blueprint.analyze.cycles import CycleAnalyzer
from arch_blueprint.domain.graph import BlueprintGraph, build_links


def analyze(graph: BlueprintGraph) -> BlueprintGraph:
    """Fill the structure derived from edges: cycles, then tangles.

    One function for every place a graph comes from — a fresh extraction or a
    loaded snapshot — so the two can never derive it differently. How a drawing
    frames the nodes is the renderer's (``renderer/layout.py``): it depends on
    what is drawn, a diff's nodes included.
    """
    graph.cycles = CycleAnalyzer.detect_cycles(graph.links)
    graph.tangles = CycleAnalyzer.detect_tangles(
        graph.links,
        build_links(graph.facade_edges),
    )
    return graph


__all__ = ["CycleAnalyzer", "analyze"]
