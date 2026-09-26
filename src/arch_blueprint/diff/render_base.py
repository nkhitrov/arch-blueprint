from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import ClassVar, Final, Optional

from arch_blueprint.diff.model import (
    ChangeStatus,
    CycleDelta,
    GraphDiff,
    MetricChange,
    MetricChanges,
    depth_of,
)
from arch_blueprint.domain.graph import Cycle, MetricValue
from arch_blueprint.domain.node import Node
from arch_blueprint.metrics import RenderPlan
from arch_blueprint.renderer.base import (
    DEFAULT_OPTIONS,
    CycleRender,
    LinkDecoration,
    RendererOptions,
    decorate_link,
    metric_rows,
    wrap_groups,
)

# One palette for every format, so a puml and a d2 diff read the same. What did
# not change looks as on a plain diagram, so these stay clear of every depth
# color and of the cycle color (a test checks). Every change is also dashed and
# carries text: a diff pasted as a grey-scale image stays legible.
ADDED_COLOR: Final = "#00C853"
REMOVED_COLOR: Final = "#FF1744"
RESOLVED_COLOR: Final = "#95A5A6"

NEW_CYCLE_LABEL: Final = "NEW CYCLE"
RESOLVED_CYCLE_LABEL: Final = "cycle resolved"
NO_CHANGES_LABEL: Final = "No architectural changes"
UNCHANGED_LABEL: Final = "unchanged: drawn as on a plain diagram"
#: Between a metric's old and new value; the same arrow the cycle notes use.
CHANGE_ARROW: Final = "→"
METRIC_CHANGE_LABEL: Final = f"metric: old {CHANGE_ARROW} new (difference)"


def format_change(change: MetricChange) -> MetricValue:
    """A metric's value as a diff shows it: ``old → new (±difference)``.

    An unchanged value is passed through as is, so it is drawn exactly as a
    plain diagram draws it; an added node or link has only its new value, a
    removed one only its old. The difference is given for numbers only — a
    cycle's ``forward/backward`` pair has none.
    """
    old, new = change.old, change.new
    if new is None:
        return "" if old is None else old
    if old is None or old == new:
        return new
    text = f"{old} {CHANGE_ARROW} {new}"
    difference = _difference(old, new)
    return text if difference is None else f"{text} ({difference})"


def _difference(old: MetricValue, new: MetricValue) -> Optional[str]:
    if isinstance(old, str) or isinstance(new, str):
        return None
    if isinstance(old, int) and isinstance(new, int):
        return f"{new - old:+d}"
    # Rounded: 0.67 - 0.5 is 0.17000000000000004 in binary floating point.
    return f"{round(new - old, 6):+g}"


class DiffRenderer(ABC):
    """Template Method for drawing a :class:`GraphDiff`, like ``BlueprintRenderer``.

    Stateless: the fixed algorithm is legend, nodes (wrapped in their groups),
    links, unchanged cycles, then changed cycles. What did not change is drawn
    as on a plain diagram — node fill by depth from ``options`` — so the changes
    read against the picture the reader knows. An empty diff is still a valid
    diagram, so a CI job always has a picture to post.

    ``plan`` says which metrics to draw, through the same render plugins as a
    plain diagram; each value is written as its change (:func:`format_change`).
    Without a plan no metric is drawn.
    """

    #: Output format id; concrete renderers must set it.
    fmt: ClassVar[str] = ""

    def __init__(
        self,
        *,
        show_cycle_details: bool = False,
        options: RendererOptions = DEFAULT_OPTIONS,
        plan: Optional[RenderPlan] = None,
    ) -> None:
        if not self.fmt:
            msg = f"{type(self).__name__} must set a non-empty 'fmt'"
            raise TypeError(msg)
        if plan is not None and plan.fmt != self.fmt:
            msg = f"plan was built for '{plan.fmt}', but this renderer is '{self.fmt}'"
            raise ValueError(msg)
        self.show_cycle_details = show_cycle_details
        self.options = options
        self.plan = plan

    def render(self, diff: GraphDiff) -> str:
        """Template method: orchestrates the diff rendering algorithm."""
        if diff.is_empty and not diff.graph.nodes:
            return self._format_empty()
        rendered = [
            (
                node.id,
                self._format_node(
                    node.id,
                    diff.node_status[node.id],
                    self._metric_rows(node, diff.node_metrics.get(node.id, {})),
                ),
            )
            for node in diff.graph.nodes
        ]
        nodes = wrap_groups(diff.graph.groups, rendered, self._format_group)
        # Every connection at the place a plain diagram declares it — by its
        # first namespace pair — so the layout matches the plain diagram's: the
        # layout engine places things by declaration order.
        connections: list[tuple[tuple[str, str], CycleRender]] = [
            (
                pair,
                CycleRender(
                    inline=self._format_link(
                        *pair,
                        status,
                        self._decoration(diff.link_metrics.get(pair, {})),
                    ),
                ),
            )
            for pair, status in diff.link_status.items()
        ]
        connections += [
            (
                _first_pair(cycle),
                CycleRender(
                    inline=self._format_context_cycle(
                        cycle,
                        self._cycle_decoration(diff, cycle),
                    ),
                ),
            )
            for cycle in diff.context_cycles
        ]
        connections += [
            (
                delta.remaining or _first_pair(delta.cycle),
                self._format_cycle(delta, self._cycle_decoration(diff, delta.cycle)),
            )
            for delta in diff.cycle_changes
        ]
        connections.sort(key=lambda item: item[0])
        links = [cycle.inline for _, cycle in connections]
        deferred = [c.deferred for _, c in connections if c.deferred is not None]
        legend = self._format_legend(
            unchanged=diff.is_empty,
            metrics=self.plan is not None
            and bool(self.plan.node_items or self.plan.link_items),
        )
        return self._combine_output(legend, nodes, links, deferred)

    def _metric_rows(self, node: Node, changes: MetricChanges) -> list[str]:
        if self.plan is None:
            return []
        return metric_rows(self.plan, node.kind, _written(changes))

    def _decoration(self, changes: MetricChanges) -> LinkDecoration:
        if self.plan is None:
            return LinkDecoration()
        return decorate_link(self.plan, _written(changes))

    def _cycle_decoration(self, diff: GraphDiff, cycle: Cycle) -> LinkDecoration:
        key = frozenset({cycle.namespace_from, cycle.namespace_to})
        return self._decoration(diff.cycle_metrics.get(key, {}))

    def _depth_color(self, node_id: str) -> str:
        """The fill a plain diagram gives this node."""
        return self.options.get_color_for_depth(depth_of(node_id))

    def _format_group(self, namespace: str, nodes: list[str]) -> list[str]:
        """Wrap one namespace's nodes; by default, do not wrap (D2 nests itself)."""
        return nodes

    @abstractmethod
    def _format_node(self, node_id: str, status: ChangeStatus, rows: list[str]) -> str:
        """Format a node marked as added, removed or context, with metric rows."""
        ...

    @abstractmethod
    def _format_link(
        self,
        source: str,
        target: str,
        status: ChangeStatus,
        decoration: LinkDecoration,
    ) -> str:
        """Format an added, removed or unchanged link, with any metric labels."""
        ...

    @abstractmethod
    def _format_context_cycle(self, cycle: Cycle, decoration: LinkDecoration) -> str:
        """Format a cycle present on both sides, as a plain diagram draws it."""
        ...

    @abstractmethod
    def _format_cycle(
        self,
        delta: CycleDelta,
        decoration: LinkDecoration,
    ) -> CycleRender:
        """Format a new or resolved cycle, with details for a new one."""
        ...

    @abstractmethod
    def _format_legend(self, *, unchanged: bool, metrics: bool) -> str:
        """Explain every marker; ``unchanged`` says first that nothing changed.

        ``metrics``: metrics are drawn, so say how a changed value reads.
        """
        ...

    @abstractmethod
    def _format_empty(self) -> str:
        """A complete diagram saying nothing changed, with nothing to show."""
        ...

    @abstractmethod
    def _combine_output(
        self,
        legend: str,
        nodes: list[str],
        links: list[str],
        deferred: list[str],
    ) -> str:
        """Combine all parts into final output with header/footer."""
        ...


def _written(changes: MetricChanges) -> Mapping[str, MetricValue]:
    return {name: format_change(change) for name, change in changes.items()}


def _first_pair(cycle: Cycle) -> tuple[str, str]:
    """The cycle's pair a plain diagram reaches first, iterating pairs sorted."""
    return min(
        (cycle.namespace_from, cycle.namespace_to),
        (cycle.namespace_to, cycle.namespace_from),
    )
