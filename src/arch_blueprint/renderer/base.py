from __future__ import annotations

from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import ClassVar, Final, Optional, final

from arch_blueprint.domain.graph import (
    BlueprintGraph,
    Cycle,
    Group,
    Link,
    MetricValue,
)
from arch_blueprint.domain.node import Node
from arch_blueprint.metrics import PlannedMetric, RenderContext, RenderPlan

# A distinct danger red for cycles; intentionally not one of DEFAULT_OPTIONS'
# depth_colors so a cycle never visually collides with a node's depth color.
CYCLE_HIGHLIGHT_COLOR: Final = "#C0392B"

#: How to read a link metric on a cycle. The convention belongs to the renderer
#: (one connection standing for two links), not to any metric, so it is shared.
CYCLE_VALUE_NOTE: Final = (
    "a/b on a cycle \u2014 a is the forward direction, b the backward one"
)


@dataclass(frozen=True)
@final
class RendererOptions:
    """Styling options for diagram renderers.

    Which metrics are drawn — and which one drives node color — is the separate
    :class:`RenderPlan`.
    """

    depth_colors: Sequence[str]
    show_cycle_details: bool = False
    show_link_details: bool = False

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


def wrap_groups(
    groups: Iterable[Group],
    rendered: Sequence[tuple[str, str]],
    format_group: Callable[[str, list[str]], list[str]],
) -> list[str]:
    """Wrap rendered ``(node_id, text)`` pairs in their groups' containers.

    A group's block takes the position of its first member, so nodes keep
    appearing in the order given. Shared by every renderer that draws nodes,
    diagram and diff alike.
    """
    group_of = {member: group.namespace for group in groups for member in group.members}
    members: dict[str, list[str]] = {}
    for node_id, text in rendered:
        namespace = group_of.get(node_id)
        if namespace is not None:
            members.setdefault(namespace, []).append(text)

    result: list[str] = []
    emitted: set[str] = set()
    for node_id, text in rendered:
        namespace = group_of.get(node_id)
        if namespace is None:
            result.append(text)
        elif namespace not in emitted:
            emitted.add(namespace)
            result.extend(format_group(namespace, members[namespace]))
    return result


#: Beyond this many distinct values a summary row elides the middle. Thresholds
#: are picked from the top of a distribution, so the top is what survives.
_MAX_DISTINCT: Final = 12

#: Legend section headings. Empty for the first: metric descriptions need none.
_OPTIONS_TITLE: Final = "options"
_VALUES_TITLE: Final = "values on this diagram"


@dataclass(frozen=True)
class LegendSection:
    """One titled block of legend rows; an empty title means no heading."""

    title: str
    rows: tuple[str, ...]


@dataclass(frozen=True)
class RenderSections:
    """Everything a renderer assembles into its final document.

    A single object rather than positional arguments: the legend is the second
    thing this hook has needed that the old three-list signature could not carry,
    and the next one should be a field, not another breaking change.
    """

    nodes: list[str]
    links: list[str]
    deferred: list[str]
    legend: tuple[LegendSection, ...]


@dataclass(frozen=True)
class RenderedLink:
    """A drawn connection: an ``inline`` fragment and an optional ``deferred`` block.

    Renderers that place detail next to the connection (PlantUML) put everything
    in ``inline``; renderers that must collect it elsewhere (D2) return it in
    ``deferred``. This keeps the render algorithm stateless.

    Returned by both :meth:`BlueprintRenderer._format_cycle` and
    :meth:`BlueprintRenderer._format_link_detail` -- a cycle is one drawn
    connection too, and both may need the two placements.
    """

    inline: str
    deferred: Optional[str] = None


@dataclass(frozen=True)
class LinkDecoration:
    """Render-plugin output attached to a single directed link.

    ``labels`` are text fragments shown on the arrow; ``styles`` are raw,
    format-specific style payloads the renderer injects into the edge. ``detail``
    is a plugin asking for the link's imports to be spelled out; the renderer
    never learns which metric raised it.
    """

    labels: tuple[str, ...] = ()
    styles: tuple[str, ...] = ()
    detail: bool = False


def _sort_key(value: MetricValue) -> tuple[bool, object]:
    """Numbers ascending, then words alphabetically; never the two compared."""
    return (isinstance(value, str), value)


def _summarize(values: Iterable[MetricValue]) -> str:
    """One row of a distribution: distinct values ascending, repeats counted.

    Elided out loud past ``_MAX_DISTINCT``: a silently truncated row would read
    as the whole picture, and the whole point of the row is to be trusted.
    """
    counts = Counter(values)
    if not counts:
        return ""
    parts = [
        f"{value}\u00d7{count}" if count > 1 else f"{value}"
        for value, count in sorted(counts.items(), key=lambda item: _sort_key(item[0]))
    ]
    if len(parts) <= _MAX_DISTINCT:
        return ", ".join(parts)
    head, tail = parts[:3], parts[-6:]
    hidden = len(parts) - len(head) - len(tail)
    return ", ".join([*head, f"\u2026 {hidden} more \u2026", *tail])


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
        return self._combine_output(
            RenderSections(
                nodes=nodes_output,
                links=links_output,
                deferred=deferred,
                legend=self._legend_sections(graph),
            ),
        )

    def _render_nodes(self, graph: BlueprintGraph) -> list[str]:
        """Render every node, wrapping those the analyzer assigned to a group.

        A group's block takes the position of its first member, so nodes keep
        appearing in the order the extractor produced them.
        """
        rendered: list[tuple[str, str]] = []
        for node in graph.nodes:
            metrics = graph.node_metrics.get(node.id, {})
            depth = int(metrics.get(self.plan.color_metric, 0))
            color = self.options.get_color_for_depth(depth)
            text = self._format_node(
                node,
                color,
                self._render_metric_blocks(node, metrics),
            )
            rendered.append((node.id, text))
        return wrap_groups(graph.groups, rendered, self._format_group)

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
            fragment = item.plugin.render(ctx, item.title, metrics[item.name])
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
                rendered_link = self._format_link(pair[0], pair[1], decoration)
                if decoration.detail and self.options.show_link_details:
                    detail = self._format_link_detail(link)
                    if detail.inline:
                        rendered_link = f"{rendered_link}\n{detail.inline}"
                    if detail.deferred is not None:
                        deferred.append(detail.deferred)
                links.append(rendered_link)
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
        detail = False
        for item in self.plan.link_items:
            if item.name not in values:
                continue
            fragment = item.plugin.render(ctx, item.title, values[item.name])
            if fragment is None:
                continue
            if fragment.text:
                labels.append(fragment.text)
            if fragment.style:
                styles.append(fragment.style)
            detail = detail or fragment.detail
        return LinkDecoration(
            labels=tuple(labels),
            styles=tuple(styles),
            detail=detail,
        )

    def _legend_sections(self, graph: BlueprintGraph) -> tuple[LegendSection, ...]:
        """What each shown metric means, how it is tuned, and what it measured.

        Concrete and shared: every word comes from the metric's own
        ``description`` and option declarations, so a new metric explains itself
        and neither renderer hardcodes any of it.
        """
        items = (*self.plan.node_items, *self.plan.link_items)
        if not items:
            return ()
        rows = [f"{item.title} \u2014 {item.description}" for item in items]
        if self.plan.link_items:
            rows.append(CYCLE_VALUE_NOTE)
        sections = [LegendSection(title="", rows=tuple(rows))]
        for title, block in (
            (_OPTIONS_TITLE, self._option_rows(items)),
            (_VALUES_TITLE, self._value_rows(graph, items)),
        ):
            if block:
                sections.append(LegendSection(title=title, rows=tuple(block)))
        return tuple(sections)

    def _option_rows(self, items: tuple[PlannedMetric, ...]) -> list[str]:
        """Name every knob a shown metric takes, and what it is set to.

        An unset one carries its description: that row is the whole path from
        "why is nothing marked" to a second run that marks the right thing.
        """
        rows: list[str] = []
        for item in items:
            given = self.plan.metric_options.get(item.name, {})
            for option in item.options:
                key = f"{item.name}.{option.name}"
                if option.name in given:
                    rows.append(f"{key} = {given[option.name]:g}")
                else:
                    rows.append(f"{key} = not set ({option.description})")
        return rows

    def _value_rows(
        self,
        graph: BlueprintGraph,
        items: tuple[PlannedMetric, ...],
    ) -> list[str]:
        """What each metric actually produced, so a threshold can be picked from it.

        A metric that computed nothing gets no row: an empty one would be noise
        on exactly the diagram meant to be read for data.
        """
        rows: list[str] = []
        for item in items:
            source = (
                graph.link_metrics.values()
                if item in self.plan.link_items
                else graph.node_metrics.values()
            )
            summary = _summarize(
                values[item.name] for values in source if item.name in values
            )
            if summary:
                rows.append(f"{item.title}: {summary}")
        return rows

    def _format_group(self, namespace: str, nodes: list[str]) -> list[str]:
        """Wrap the nodes belonging to one namespace; by default, do not wrap.

        Deliberately concrete rather than abstract: a format whose own syntax
        already nests by dotted name (D2 does) needs no container, and adding an
        abstract method would break every renderer outside this package — the
        extension point the docs advertise.
        """
        return nodes

    def _format_link_detail(self, link: Link) -> RenderedLink:
        """Spell out the imports behind one link; by default, draw nothing.

        Concrete for the same reason as :meth:`_format_group`: an abstract method
        would break every renderer outside this package. Called only for a link a
        plugin flagged, and only while ``show_link_details`` is on -- a note on
        every arrow would bury the diagram.
        """
        return RenderedLink(inline="")

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
    def _format_cycle(self, cycle: Cycle, decoration: LinkDecoration) -> RenderedLink:
        """Format a bidirectional cycle between namespaces, with any decoration."""
        ...

    @abstractmethod
    def _combine_output(self, sections: RenderSections) -> str:
        """Assemble the final document from the rendered sections."""
        ...
