from __future__ import annotations

from collections.abc import Iterable

from arch_blueprint.domain.graph import Cycle, Edge, Link


class CycleAnalyzer:
    """Detects bidirectional dependencies between namespaces.

    Operates purely on Link/Edge namespace strings, so it is agnostic to whether
    the underlying nodes are modules or classes.
    """

    @staticmethod
    def detect_cycles(links: Iterable[Link]) -> list[Cycle]:
        links_by_pair: dict[tuple[str, str], Link] = {}
        for link in links:
            key = (link.source_namespace, link.target_namespace)
            if key in links_by_pair:
                merged_edges = links_by_pair[key].edges | link.edges
                links_by_pair[key] = Link(
                    source_namespace=link.source_namespace,
                    target_namespace=link.target_namespace,
                    edges=merged_edges,
                )
            else:
                links_by_pair[key] = link

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
                        namespace_from=src,
                        namespace_to=tgt,
                        forward_edges=forward_link.edges,
                        backward_edges=backward_link.edges,
                    ),
                )
                processed.add((src, tgt))
                processed.add(reverse_key)

        return cycles

    @staticmethod
    def collect_all_edges(links: Iterable[Link]) -> set[Edge]:
        result: set[Edge] = set()
        for link in links:
            result.update(link.edges)
        return result
