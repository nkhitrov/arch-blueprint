from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Optional, final

from arch_blueprint.analyze.cycles import CycleAnalyzer
from arch_blueprint.domain.graph import BlueprintGraph, Cycle, MetricValue
from arch_blueprint.domain.node import Node
from arch_blueprint.metrics import COLOR_METRIC, BlockBuilder, MetricRegistry

# A distinct danger red for cycles; intentionally not one of DEFAULT_OPTIONS'
# depth_colors so a cycle never visually collides with a node's depth color.
CYCLE_HIGHLIGHT_COLOR: Final = "#C0392B"


@dataclass(frozen=True)
@final
class RendererOptions:
    """Configuration options for diagram renderers."""

    depth_colors: Sequence[str]
    show_cycle_details: bool = False
    color_metric: str = COLOR_METRIC
    shown_metrics: tuple[str, ...] = ()

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


@dataclass(frozen=True)
class CycleRender:
    """A rendered cycle: an ``inline`` fragment and optional ``deferred`` block.

    Renderers that draw cycle details next to the link (PlantUML) put everything
    in ``inline``; renderers that must collect details elsewhere (D2) return them
    in ``deferred``. This keeps the render algorithm stateless.
    """

    inline: str
    deferred: Optional[str] = None


class BlueprintRenderer(ABC):
    """ABC using Template Method pattern for rendering architecture diagrams."""

    def __init__(
        self,
        options: Optional[RendererOptions] = None,
        registry: Optional[MetricRegistry] = None,
    ) -> None:
        self.options = options or DEFAULT_OPTIONS
        self.registry = registry

    def render(self, graph: BlueprintGraph) -> str:
        """Template method: orchestrates the rendering algorithm."""
        nodes_output = self._render_nodes(graph)
        links_output, deferred = self._render_links(graph)
        return self._combine_output(nodes_output, links_output, deferred)

    def _render_nodes(self, graph: BlueprintGraph) -> list[str]:
        result: list[str] = []
        for node in graph.nodes:
            metrics = graph.node_metrics.get(node.id, {})
            depth = int(metrics.get(self.options.color_metric, 0))
            color = self.options.get_color_for_depth(depth)
            blocks = self._render_metric_blocks(node, metrics)
            result.append(self._format_node(node, color, blocks))
        return result

    def _render_metric_blocks(
        self,
        node: Node,
        metrics: dict[str, MetricValue],
    ) -> list[str]:
        if self.registry is None:
            return []
        builder = self._block_builder()
        blocks: list[str] = []
        for name in self.options.shown_metrics:
            metric = self.registry.get(name)
            if metric is None or node.kind not in metric.applies_to:
                continue
            if name not in metrics:
                continue
            block = metric.render_block(metrics[name], builder)
            if block is not None:
                blocks.append(block)
        return blocks

    def _render_links(self, graph: BlueprintGraph) -> tuple[list[str], list[str]]:
        all_links = graph.links
        cycles = CycleAnalyzer.detect_cycles(all_links)
        cycle_map = {frozenset({c.namespace_from, c.namespace_to}): c for c in cycles}

        links: list[str] = []
        deferred: list[str] = []
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
                rendered = self._format_cycle(cycle_map[cycle_key])
                links.append(rendered.inline)
                if rendered.deferred is not None:
                    deferred.append(rendered.deferred)
                processed.add(pair)
                processed.add((pair[1], pair[0]))
            else:
                links.append(self._format_link(pair[0], pair[1]))
                processed.add(pair)

        return links, deferred

    @abstractmethod
    def _block_builder(self) -> BlockBuilder:
        """Return the format-specific helper metrics use to render their blocks."""
        ...

    @abstractmethod
    def _format_node(self, node: Node, color: str, blocks: list[str]) -> str:
        """Format a single node, optionally embedding metric blocks."""
        ...

    @abstractmethod
    def _format_link(self, source: str, target: str) -> str:
        """Format a unidirectional link between namespaces."""
        ...

    @abstractmethod
    def _format_cycle(self, cycle: Cycle) -> CycleRender:
        """Format a bidirectional cycle between namespaces."""
        ...

    @abstractmethod
    def _combine_output(
        self,
        nodes: list[str],
        links: list[str],
        deferred: list[str],
    ) -> str:
        """Combine all parts into final output with header/footer."""
        ...
