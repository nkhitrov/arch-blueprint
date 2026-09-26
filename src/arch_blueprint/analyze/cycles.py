from __future__ import annotations

from collections.abc import Iterable

import networkx as nx

from arch_blueprint.domain.graph import Cycle, Link, Tangle


class CycleAnalyzer:
    """Detects bidirectional dependencies between link endpoints.

    Operates purely on Link endpoint strings, so it is agnostic to whether the
    underlying nodes are modules or classes, and to the link level.
    """

    @staticmethod
    def detect_cycles(links: Iterable[Link]) -> list[Cycle]:
        # build_links already guarantees one Link per endpoint pair.
        links_by_pair = {(link.source, link.target): link for link in links}

        cycles: list[Cycle] = []
        processed: set[tuple[str, str]] = set()

        for (src, tgt), forward_link in sorted(links_by_pair.items()):
            if (src, tgt) in processed:
                continue

            reverse_key = (tgt, src)
            if reverse_key in links_by_pair:
                backward_link = links_by_pair[reverse_key]
                cycles.append(
                    Cycle(
                        endpoint_from=src,
                        endpoint_to=tgt,
                        forward_edges=forward_link.edges,
                        backward_edges=backward_link.edges,
                    ),
                )
                processed.add((src, tgt))
                processed.add(reverse_key)

        return cycles

    @staticmethod
    def detect_tangles(links: Iterable[Link], hidden: Iterable[Link]) -> list[Tangle]:
        """Every cycle of any length: the strongly connected components.

        ``hidden`` links (package facade imports) take part in the search but
        are not drawn, so a cycle closed by a facade is still found. A component
        that is just one mutual pair is left to :meth:`detect_cycles`.
        """
        drawn = {(link.source, link.target): link for link in links}
        facade = list(hidden)
        graph = nx.DiGraph()
        graph.add_edges_from(drawn)
        graph.add_edges_from((link.source, link.target) for link in facade)

        tangles: list[Tangle] = []
        for component in nx.strongly_connected_components(graph):
            if len(component) < 2:
                continue
            inside = sorted(
                pair for pair in drawn if pair[0] in component and pair[1] in component
            )
            if len(component) == 2 and len(inside) == 2:
                continue  # a mutual pair, drawn as one two-headed Cycle arrow
            tangles.append(
                Tangle(
                    members=tuple(sorted(component)),
                    links=tuple(drawn[pair] for pair in inside),
                    hidden_edges=frozenset(
                        edge
                        for link in facade
                        if link.source in component and link.target in component
                        for edge in link.edges
                    ),
                ),
            )
        return sorted(tangles, key=lambda tangle: tangle.members)
