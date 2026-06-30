from __future__ import annotations

from collections.abc import Iterable

from .models import CyclicDependency, ModuleEdge, NamespaceLink


class CycleAnalyzer:
    """Detects cyclic dependencies between namespaces."""

    @staticmethod
    def detect_cycles(links: Iterable[NamespaceLink]) -> list[CyclicDependency]:
        """Detect bidirectional dependencies between namespaces.

        Returns CyclicDependency objects containing the module-level edges
        that contribute to each cycle.
        """
        links_by_pair: dict[tuple[str, str], NamespaceLink] = {}
        for link in links:
            key = (link.source_namespace, link.target_namespace)
            if key in links_by_pair:
                merged_edges = links_by_pair[key].edges | link.edges
                links_by_pair[key] = NamespaceLink(
                    source_namespace=link.source_namespace,
                    target_namespace=link.target_namespace,
                    edges=merged_edges,
                )
            else:
                links_by_pair[key] = link

        cycles: list[CyclicDependency] = []
        processed: set[tuple[str, str]] = set()

        for (src, tgt), forward_link in sorted(links_by_pair.items()):
            if (src, tgt) in processed:
                continue

            reverse_key = (tgt, src)
            if reverse_key in links_by_pair:
                backward_link = links_by_pair[reverse_key]
                cycles.append(
                    CyclicDependency(
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
    def collect_all_edges(links: Iterable[NamespaceLink]) -> set[ModuleEdge]:
        result: set[ModuleEdge] = set()
        for link in links:
            result.update(link.edges)
        return result
