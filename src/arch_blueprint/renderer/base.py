from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import ClassVar, Final, Optional, final

from arch_blueprint.domain.graph import (
    BlueprintGraph,
    Cycle,
    Group,
    MetricValue,
    Tangle,
    cycle_metric_values,
)
from arch_blueprint.domain.node import Node, NodeKind
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
    #: Draw nodes inside the namespaces of their dotted names; off, each node is
    #: a flat box under its full name (the link level decides, ``Level.nested``).
    nested: bool = True

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


def flat_nodes(
    rendered: Sequence[tuple[str, str]],
    endpoints: Iterable[str],
    format_facade: Callable[[str], str],
) -> list[str]:
    """Rendered ``(node_id, text)`` pairs, plus every endpoint no node carries.

    Flat, nothing contains anything, so a package an arrow ends on (its facade,
    ``__init__.py``) is declared as a node of its own. It goes before the first
    node under it, shallower first — where its container would have been — and
    last when no drawn node lies under it. From the endpoints, not the groups: a
    group needs members of its own, which a facade above another facade lacks.
    """
    facades = sorted(set(endpoints) - {node_id for node_id, _ in rendered})
    result: list[str] = []
    emitted: set[str] = set()
    for node_id, text in rendered:
        for facade in facades:  # sorted: a prefix before the names under it
            if facade not in emitted and node_id.startswith(f"{facade}."):
                emitted.add(facade)
                result.append(format_facade(facade))
        result.append(text)
    result += [format_facade(facade) for facade in facades if facade not in emitted]
    return result


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


def metric_rows(
    plan: RenderPlan,
    kind: NodeKind,
    values: Mapping[str, MetricValue],
) -> list[str]:
    """The node metrics ``plan`` shows, as rows for a node of ``kind``.

    Shared by every renderer that draws nodes, diagram and diff alike: a diff
    passes each value already written as its change.
    """
    ctx = RenderContext(fmt=plan.fmt)
    rows: list[str] = []
    for item in plan.node_items:
        if kind not in item.applies_to or item.name not in values:
            continue
        fragment = item.plugin.render(ctx, item.name, values[item.name])
        if fragment is not None and fragment.text:
            rows.append(fragment.text)
    return rows


def decorate_link(
    plan: RenderPlan,
    values: Mapping[str, MetricValue],
) -> LinkDecoration:
    """The link metrics ``plan`` shows, as one connection's labels and styles."""
    ctx = RenderContext(fmt=plan.fmt)
    labels: list[str] = []
    styles: list[str] = []
    for item in plan.link_items:
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


class BlueprintRenderer(ABC):
    """ABC using Template Method pattern for rendering architecture diagrams."""

    #: Output format id (``"puml"`` / ``"d2"``) passed to render plugins.
    #: Concrete renderers must set this; it is what a plan is built against.
    fmt: ClassVar[str] = ""

    #: Style payloads marking a one-way link that lies on a longer cycle (a
    #: :class:`Tangle`). Empty draws it as any other link, so a renderer written
    #: outside this package keeps working without knowing about tangles.
    cyclic_link_styles: ClassVar[tuple[str, ...]] = ()

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
        if self.options.nested:
            return wrap_groups(graph.groups, rendered, self._format_group)
        endpoints = {end for link in graph.links for end in (link.source, link.target)}
        endpoints.update(
            member for tangle in graph.tangles for member in tangle.members
        )
        return flat_nodes(rendered, endpoints, self._format_facade)

    def _format_facade(self, namespace: str) -> str:
        """A package an arrow ends on, drawn flat: a node like any other.

        Importing ``pkg`` runs ``pkg/__init__.py``, a module like any other, so
        drawing it as a box beside the modules under it is what the import means.
        """
        color = self.options.get_color_for_depth(len(namespace.split(".")))
        return self._format_node(Node(namespace, NodeKind.MODULE), color, [])

    def _render_metric_blocks(
        self,
        node: Node,
        metrics: Mapping[str, MetricValue],
    ) -> list[str]:
        return metric_rows(self.plan, node.kind, metrics)

    def _render_links(self, graph: BlueprintGraph) -> tuple[list[str], list[str]]:
        all_links = graph.links
        cycle_map = {
            frozenset({c.endpoint_from, c.endpoint_to}): c for c in graph.cycles
        }
        # A pair inside a longer cycle is listed in that cycle's note, once.
        in_tangle = {
            frozenset({link.source, link.target})
            for tangle in graph.tangles
            for link in tangle.links
        }

        links: list[str] = []
        deferred: list[str] = []
        processed: set[tuple[str, str]] = set()

        for link in sorted(
            all_links,
            key=lambda x: (x.source, x.target),
        ):
            pair = (link.source, link.target)
            if pair in processed:
                continue

            cycle_key = frozenset(pair)
            if cycle_key in cycle_map:
                cycle = cycle_map[cycle_key]
                rendered = self._format_cycle(
                    cycle,
                    self._cycle_decoration(graph, cycle),
                    details=self.options.show_cycle_details
                    and cycle_key not in in_tangle,
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

        notes, deferred_notes = self._render_tangle_notes(graph)
        return [*links, *notes], [*deferred, *deferred_notes]

    def _render_tangle_notes(
        self,
        graph: BlueprintGraph,
    ) -> tuple[list[str], list[str]]:
        """Each longer cycle's note, after every link: it belongs to no one arrow."""
        inline: list[str] = []
        deferred: list[str] = []
        if not self.options.show_cycle_details:
            return inline, deferred
        for tangle in graph.tangles:
            note = self._format_tangle(tangle)
            if note is None:
                continue
            if note.inline:
                inline.append(note.inline)
            if note.deferred is not None:
                deferred.append(note.deferred)
        return inline, deferred

    def _link_decoration(
        self,
        graph: BlueprintGraph,
        pair: tuple[str, str],
    ) -> LinkDecoration:
        decoration = self._decorate(graph.link_metrics.get(pair, {}))
        on_cycle = any(
            (link.source, link.target) == pair
            for tangle in graph.tangles
            for link in tangle.links
        )
        if not on_cycle:
            return decoration
        return LinkDecoration(
            labels=decoration.labels,
            styles=(*self.cyclic_link_styles, *decoration.styles),
        )

    def _cycle_decoration(
        self,
        graph: BlueprintGraph,
        cycle: Cycle,
    ) -> LinkDecoration:
        """Both directions' values on one connection: ``cycle_metric_values``."""
        return self._decorate(
            cycle_metric_values(
                graph.link_metrics,
                cycle.endpoint_from,
                cycle.endpoint_to,
            ),
        )

    def _decorate(self, values: Mapping[str, MetricValue]) -> LinkDecoration:
        return decorate_link(self.plan, values)

    def _format_group(self, namespace: str, nodes: list[str]) -> list[str]:
        """Wrap the nodes belonging to one namespace; by default, do not wrap.

        Deliberately concrete rather than abstract: a format whose own syntax
        already nests by dotted name (D2 does) needs no container, and adding an
        abstract method would break every renderer outside this package — the
        extension point the docs advertise.
        """
        return nodes

    def _format_tangle(self, tangle: Tangle) -> Optional[CycleRender]:
        """The note listing a longer cycle's imports; by default, none.

        Concrete for the same reason as ``_format_group``: the cycle is still
        marked on its links through ``cyclic_link_styles``.
        """
        return None

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
        """Format a unidirectional link between endpoints, with any decoration."""
        ...

    @abstractmethod
    def _format_cycle(
        self,
        cycle: Cycle,
        decoration: LinkDecoration,
        *,
        details: bool,
    ) -> CycleRender:
        """Format a bidirectional cycle between endpoints, with any decoration.

        ``details`` says whether to list the cycle's imports: off without cycle
        details, and off for a pair on a longer cycle, whose note lists them.
        """
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
