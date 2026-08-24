from __future__ import annotations

from collections.abc import Iterable

from arch_blueprint.domain.graph import Cycle, Link


class CycleAnalyzer:
    """Detects bidirectional dependencies between namespaces.

    Operates purely on Link/Edge namespace strings, so it is agnostic to whether
    the underlying nodes are modules or classes.
    """

    @staticmethod
    def detect_cycles(links: Iterable[Link]) -> list[Cycle]:
        # build_links already guarantees one Link per namespace pair.
        links_by_pair = {
            (link.source_namespace, link.target_namespace): link for link in links
        }

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
