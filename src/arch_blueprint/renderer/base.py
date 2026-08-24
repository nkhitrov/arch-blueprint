from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import ClassVar, Final, Optional, final

from arch_blueprint.domain.graph import BlueprintGraph, Cycle, MetricValue
from arch_blueprint.domain.node import Node
from arch_blueprint.metrics import RenderContext, RenderPlan

# A distinct danger red for cycles; intentionally not one of DEFAULT_OPTIONS'
# depth_colors so a cycle never visually collides with a node's depth color.
CYCLE_HIGHLIGHT_COLOR: Final = "#C0392B"


@dataclass(frozen=True)
@final
class RendererOptions:
    """Styling options for diagram renderers.

    Which metrics are drawn — and which one drives node color — is the separate
    :class:`RenderPlan`.
    """

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


@dataclass(frozen=True)
class CycleRender:
    """A rendered cycle: an ``inline`` fragment and optional ``deferred`` block.

    Renderers that draw cycle details next to the link (PlantUML) put everything
    in ``inline``; renderers that must collect details elsewhere (D2) return them
    in ``deferred``. This keeps the render algorithm stateless.
    """

    inline: str
    deferred: Optional[str] = None


@dataclass(frozen=True)
class LinkDecoration:
    """Render-plugin output attached to a single directed link.

    ``labels`` are text fragments shown on the arrow; ``styles`` are raw,
    format-specific style payloads the renderer injects into the edge.
    """

    labels: tuple[str, ...] = ()
    styles: tuple[str, ...] = ()


class BlueprintRenderer(ABC):
    """ABC using Template Method pattern for rendering architecture diagrams."""

    #: Output format id (``"puml"`` / ``"d2"``) passed to render plugins.
    #: Concrete renderers must set this; it is what a plan is built against.
    fmt: ClassVar[str] = ""

    def __init__(
        self,
        plan: RenderPlan,
        options: Optional[RendererOptions] = None,
    ) -> None:
        if not self.fmt:
            msg = f"{type(self).__name__} must set a non-empty 'fmt'"
            raise TypeError(msg)
        if plan.fmt != self.fmt:
            msg = f"plan was built for '{plan.fmt}', but this renderer is '{self.fmt}'"
            raise ValueError(msg)
        self.plan = plan
        self.options = options or DEFAULT_OPTIONS

    def render(self, graph: BlueprintGraph) -> str:
        """Template method: orchestrates the rendering algorithm."""
        nodes_output = self._render_nodes(graph)
        links_output, deferred = self._render_links(graph)
        return self._combine_output(nodes_output, links_output, deferred)

    def _render_nodes(self, graph: BlueprintGraph) -> list[str]:
        result: list[str] = []
        for node in graph.nodes:
            metrics = graph.node_metrics.get(node.id, {})
            depth = int(metrics.get(self.plan.color_metric, 0))
            color = self.options.get_color_for_depth(depth)
            blocks = self._render_metric_blocks(node, metrics)
            result.append(self._format_node(node, color, blocks))
        return result

    def _render_metric_blocks(
        self,
        node: Node,
        metrics: Mapping[str, MetricValue],
    ) -> list[str]:
        ctx = RenderContext(fmt=self.plan.fmt)
        blocks: list[str] = []
        for item in self.plan.node_items:
            if node.kind not in item.applies_to or item.name not in metrics:
                continue
            fragment = item.plugin.render(ctx, item.name, metrics[item.name])
            if fragment is not None and fragment.text:
                blocks.append(fragment.text)
        return blocks

    def _render_links(self, graph: BlueprintGraph) -> tuple[list[str], list[str]]:
        all_links = graph.links
        cycle_map = {
            frozenset({c.namespace_from, c.namespace_to}): c for c in graph.cycles
        }

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
                cycle = cycle_map[cycle_key]
                rendered = self._format_cycle(
                    cycle,
                    self._cycle_decoration(graph, cycle),
                )
                links.append(rendered.inline)
                if rendered.deferred is not None:
                    deferred.append(rendered.deferred)
                processed.add(pair)
                processed.add((pair[1], pair[0]))
            else:
                decoration = self._link_decoration(graph, pair)
                links.append(self._format_link(pair[0], pair[1], decoration))
                processed.add(pair)

        return links, deferred

    def _link_decoration(
        self,
        graph: BlueprintGraph,
        pair: tuple[str, str],
    ) -> LinkDecoration:
        return self._decorate(graph.link_metrics.get(pair, {}))

    def _cycle_decoration(
        self,
        graph: BlueprintGraph,
        cycle: Cycle,
    ) -> LinkDecoration:
        """Decorate a cycle with both directions' values, forward first.

        A cycle is one drawn connection standing for two links, so a link metric
        has two values. Showing one of them would make the golden freeze an
        arbitrary choice; they are combined as ``forward/backward``, matching the
        order the cycle's own detail block lists them in.
        """
        forward = graph.link_metrics.get((cycle.namespace_from, cycle.namespace_to), {})
        backward = graph.link_metrics.get(
            (cycle.namespace_to, cycle.namespace_from),
            {},
        )
        combined: dict[str, MetricValue] = {}
        for name in {*forward, *backward}:
            if name in forward and name in backward:
                combined[name] = f"{forward[name]}/{backward[name]}"
            elif name in forward:
                combined[name] = forward[name]
            else:
                combined[name] = backward[name]
        return self._decorate(combined)

    def _decorate(self, values: Mapping[str, MetricValue]) -> LinkDecoration:
        ctx = RenderContext(fmt=self.plan.fmt)
        labels: list[str] = []
        styles: list[str] = []
        for item in self.plan.link_items:
            if item.name not in values:
                continue
            fragment = item.plugin.render(ctx, item.name, values[item.name])
            if fragment is None:
                continue
            if fragment.text:
                labels.append(fragment.text)
            if fragment.style:
                styles.append(fragment.style)
        return LinkDecoration(labels=tuple(labels), styles=tuple(styles))

    @abstractmethod
    def _format_node(self, node: Node, color: str, blocks: list[str]) -> str:
        """Format a single node, optionally embedding metric blocks."""
        ...

    @abstractmethod
    def _format_link(
        self,
        source: str,
        target: str,
        decoration: LinkDecoration,
    ) -> str:
        """Format a unidirectional link between namespaces, with any decoration."""
        ...

    @abstractmethod
    def _format_cycle(self, cycle: Cycle, decoration: LinkDecoration) -> CycleRender:
        """Format a bidirectional cycle between namespaces, with any decoration."""
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
