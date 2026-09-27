from __future__ import annotations

import copy
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, Final, Optional, TypeVar, final

from arch_blueprint.domain.graph import (
    BlueprintGraph,
    Cycle,
    MetricValue,
    Tangle,
    cycle_metric_values,
)
from arch_blueprint.domain.node import Node, NodeKind
from arch_blueprint.metrics import RenderContext, RenderPlan
from arch_blueprint.renderer.layout import Frame, Layout, LayoutItem

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
    #: Draw nodes inside frames of their dotted names, chains of empty frames
    #: merged; off, each node is a flat box labelled by its full name less the
    #: prefix all share, shown as the title (the link level decides,
    #: ``Level.nested``; ``renderer/layout.py``).
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


def placed_nodes(
    layout: Layout,
    rendered: Sequence[tuple[str, str]],
    format_frame: Callable[[Frame, list[str]], list[str]],
    format_facade: Callable[[str], str],
) -> list[str]:
    """Rendered ``(node_id, text)`` pairs, placed as ``layout`` says.

    Each frame is written around what it holds; a name no node carries (a flat
    drawing's package facade) through ``format_facade``. Shared by every
    renderer that draws nodes, diagram and diff alike.
    """
    text = dict(rendered)

    def written(items: tuple[LayoutItem, ...]) -> list[str]:
        result: list[str] = []
        for item in items:
            if isinstance(item, Frame):
                result.extend(format_frame(item, written(item.items)))
            else:
                result.append(text[item] if item in text else format_facade(item))
        return result

    return written(layout.items)


class LaidOut:
    """What a renderer's hooks spell names through: the drawing's layout.

    A name's key and label in every hook depend on the layout of the drawing
    at hand, which only ``render`` knows. It draws through a copy carrying it
    (:func:`laid_out`), so the renderer a caller holds is never changed: it
    stays stateless and reusable. Read anywhere else — a hook called directly,
    a ``render`` overridden to call the steps on ``self`` — :attr:`layout`
    raises rather than drawing every name flat and unlabelled.

    Shared by ``BlueprintRenderer`` and ``DiffRenderer``, and so is the guard
    against a hook renamed under a subclass (:meth:`__init_subclass__`).
    """

    _drawing: Optional[Layout] = None

    #: Hooks renamed since; a subclass still overriding one would silently
    #: stop being called. Old name → what replaced it.
    _RENAMED_HOOKS: ClassVar[Mapping[str, str]] = {
        "_format_group": "_format_frame(frame, items)",
    }

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for old, new in LaidOut._RENAMED_HOOKS.items():
            if old in vars(cls):
                msg = (
                    f"{cls.__name__} overrides '{old}', which is never called any "
                    f"more: override '{new}' instead"
                )
                raise TypeError(msg)

    @property
    def layout(self) -> Layout:
        """How the drawing at hand places and labels names; only inside ``render``.

        A hook spells a name through it: :meth:`Layout.path`, :meth:`Layout.label`.
        """
        if self._drawing is None:
            msg = (
                f"{type(self).__name__}.layout is read outside render(): only the "
                f"copy render() draws through carries the drawing's layout"
            )
            raise RuntimeError(msg)
        return self._drawing


_R = TypeVar("_R", bound=LaidOut)


def laid_out(renderer: _R, layout: Layout) -> _R:
    """A copy of ``renderer`` that draws through ``layout``."""
    bound = copy.copy(renderer)
    bound._drawing = layout  # noqa: SLF001 - the one place it is set
    return bound


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


class BlueprintRenderer(LaidOut, ABC):
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

    @final
    def render(self, graph: BlueprintGraph) -> str:
        """Template method: orchestrates the rendering algorithm.

        Drawn by a copy laid out for ``graph`` (:func:`laid_out`), so this
        renderer itself is never changed. Final: the hooks read the layout,
        which only this sets.
        """
        # The same class: its own template, on the copy that carries the layout.
        return laid_out(self, self._layout(graph))._draw(graph)  # noqa: SLF001

    def _draw(self, graph: BlueprintGraph) -> str:
        nodes_output = self._render_nodes(graph)
        links_output, deferred = self._render_links(graph)
        return self._combine_output(nodes_output, links_output, deferred)

    def _layout(self, graph: BlueprintGraph) -> Layout:
        """Frames (nested) or the shared prefix (flat) of what ``graph`` draws."""
        endpoints = {end for link in graph.links for end in (link.source, link.target)}
        endpoints.update(
            member for tangle in graph.tangles for member in tangle.members
        )
        return Layout.build(
            [node.id for node in graph.nodes],
            endpoints,
            nested=self.options.nested,
        )

    def _render_nodes(self, graph: BlueprintGraph) -> list[str]:
        """Render every node, placed in its frame, in the order the extractor made.

        A frame takes the position of its first node, so nodes keep appearing
        in the order the extractor produced them.
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
        return placed_nodes(
            self.layout,
            rendered,
            self._format_frame,
            self._format_facade,
        )

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

    def _format_frame(self, frame: Frame, items: list[str]) -> list[str]:
        """Wrap what one frame holds (nested); by default, do not wrap.

        Deliberately concrete rather than abstract: a format whose own syntax
        already nests by key (D2 does, a key spelled through ``self.layout``)
        needs no container, and adding an abstract method would break every
        renderer outside this package — the extension point the docs advertise.
        """
        return items

    def _format_tangle(self, tangle: Tangle) -> Optional[CycleRender]:
        """The note listing a longer cycle's imports; by default, none.

        Concrete for the same reason as ``_format_frame``: the cycle is still
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
