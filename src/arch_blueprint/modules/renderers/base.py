from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, final

from arch_blueprint.modules.analyzer import CycleAnalyzer
from arch_blueprint.modules.models import CyclicDependency, ModuleEdge, NamespaceLink
from arch_blueprint.modules.module import BlueprintModule

CYCLE_HIGHLIGHT_COLOR: Final = "#E74C3C"


@dataclass(frozen=True)
@final
class RendererOptions:
    """Configuration options for diagram renderers."""

    depth_colors: Sequence[str]
    show_cycle_details: bool = False

    def __post_init__(self) -> None:
        if not self.depth_colors:
            msg = "depth_colors must not be empty"
            raise ValueError(msg)

    def get_color_for_depth(self, depth: int) -> str:
        """Return color for given depth, cycling through available colors."""
        return self.depth_colors[depth % len(self.depth_colors)]


DEFAULT_OPTIONS: Final = RendererOptions(
    depth_colors=[
        "#E74C3C",
        "#3498DB",
        "#2ECC71",
        "#1ABC9C",
        "#F39C12",
        "#9B59B6",
        "#27AE60",
        "#34495E",
        "#E67E22",
        "#8E44AD",
    ],
)


class BlueprintModuleRenderer(ABC):
    """ABC using Template Method pattern for rendering architecture diagrams."""

    def __init__(self, options: RendererOptions | None = None) -> None:
        self.options = options or DEFAULT_OPTIONS

    def render(self, target_modules: list[BlueprintModule]) -> str:
        """Template method: orchestrates the rendering algorithm."""
        modules_output = self._render_modules(target_modules)
        links_output = self._render_links(target_modules)
        return self._combine_output(modules_output, links_output)

    def _render_modules(self, modules: list[BlueprintModule]) -> list[str]:
        return [
            self._format_module(m, self.options.get_color_for_depth(m.depth))
            for m in modules
        ]

    def _render_links(self, modules: list[BlueprintModule]) -> list[str]:
        all_links = self._collect_links(modules)
        cycles = CycleAnalyzer.detect_cycles(all_links)
        cycle_map = self._build_cycle_map(cycles)

        result: list[str] = []
        processed: set[tuple[str, str]] = set()

        for link in sorted(
            all_links,
            key=lambda x: (x.source_namespace, x.target_namespace),
        ):
            pair = (link.source_namespace, link.target_namespace)
            if pair in processed:
                continue

            cycle_key = frozenset(pair)
            if cycle_key in cycle_map:
                result.append(self._format_cycle(cycle_map[cycle_key]))
                processed.add(pair)
                processed.add((pair[1], pair[0]))
            else:
                result.append(self._format_link(pair[0], pair[1]))
                processed.add(pair)

        return result

    def _collect_links(self, modules: list[BlueprintModule]) -> set[NamespaceLink]:
        all_links: set[NamespaceLink] = set()
        for module in modules:
            all_links.update(module.find_namespace_links())
        return all_links

    def _build_cycle_map(
        self,
        cycles: list[CyclicDependency],
    ) -> dict[frozenset[str], CyclicDependency]:
        return {frozenset({c.namespace_from, c.namespace_to}): c for c in cycles}

    def _format_edges(self, edges: frozenset[ModuleEdge]) -> list[str]:
        """Format module edges for cycle details (shared implementation)."""
        lines = []
        for edge in sorted(edges, key=lambda e: (e.source_module, e.target_module)):
            src_short = edge.source_module.removeprefix(edge.source_namespace + ".")
            tgt_short = edge.target_module.removeprefix(edge.target_namespace + ".")
            lines.append(f"- {src_short} → {tgt_short}")
        return lines

    @abstractmethod
    def _format_module(self, module: BlueprintModule, color: str) -> str: ...

    @abstractmethod
    def _format_link(self, source: str, target: str) -> str:
        """Format a unidirectional link between namespaces."""
        ...

    @abstractmethod
    def _format_cycle(self, cycle: CyclicDependency) -> str:
        """Format a bidirectional cycle between namespaces."""
        ...

    @abstractmethod
    def _combine_output(
        self,
        modules: list[str],
        links: list[str],
    ) -> str:
        """Combine all parts into final output with header/footer."""
        ...
