from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar, Final

from arch_blueprint.diff.model import (
    ChangeStatus,
    CycleDelta,
    GraphDiff,
    depth_of,
)
from arch_blueprint.domain.graph import Cycle
from arch_blueprint.renderer.base import (
    DEFAULT_OPTIONS,
    RenderedLink,
    RendererOptions,
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


class DiffRenderer(ABC):
    """Template Method for drawing a :class:`GraphDiff`, like ``BlueprintRenderer``.

    Stateless: the fixed algorithm is legend, nodes (wrapped in their groups),
    links, unchanged cycles, then changed cycles. What did not change is drawn
    as on a plain diagram — node fill by depth from ``options`` — so the changes
    read against the picture the reader knows. An empty diff is still a valid
    diagram, so a CI job always has a picture to post.
    """

    #: Output format id; concrete renderers must set it.
    fmt: ClassVar[str] = ""

    def __init__(
        self,
        *,
        show_cycle_details: bool = True,
        options: RendererOptions = DEFAULT_OPTIONS,
    ) -> None:
        if not self.fmt:
            msg = f"{type(self).__name__} must set a non-empty 'fmt'"
            raise TypeError(msg)
        self.show_cycle_details = show_cycle_details
        self.options = options

    def render(self, diff: GraphDiff) -> str:
        """Template method: orchestrates the diff rendering algorithm."""
        if diff.is_empty and not diff.graph.nodes:
            return self._format_empty()
        rendered = [
            (node.id, self._format_node(node.id, diff.node_status[node.id]))
            for node in diff.graph.nodes
        ]
        nodes = wrap_groups(diff.graph.groups, rendered, self._format_group)
        # Every connection at the place a plain diagram declares it — by its
        # first namespace pair — so the layout matches the plain diagram's: the
        # layout engine places things by declaration order.
        connections: list[tuple[tuple[str, str], CycleRender]] = [
            (pair, CycleRender(inline=self._format_link(*pair, status)))
            for pair, status in diff.link_status.items()
        ]
        connections += [
            (_first_pair(cycle), CycleRender(inline=self._format_context_cycle(cycle)))
            for cycle in diff.context_cycles
        ]
        connections += [
            (delta.remaining or _first_pair(delta.cycle), self._format_cycle(delta))
            for delta in diff.cycle_changes
        ]
        connections.sort(key=lambda item: item[0])
        links = [cycle.inline for _, cycle in connections]
        deferred = [c.deferred for _, c in connections if c.deferred is not None]
        legend = self._format_legend(unchanged=diff.is_empty)
        return self._combine_output(legend, nodes, links, deferred)

    def _depth_color(self, node_id: str) -> str:
        """The fill a plain diagram gives this node."""
        return self.options.get_color_for_depth(depth_of(node_id))

    def _format_group(self, namespace: str, nodes: list[str]) -> list[str]:
        """Wrap one namespace's nodes; by default, do not wrap (D2 nests itself)."""
        return nodes

    @abstractmethod
    def _format_node(self, node_id: str, status: ChangeStatus) -> str:
        """Format a node marked as added, removed or context."""
        ...

    @abstractmethod
    def _format_link(self, source: str, target: str, status: ChangeStatus) -> str:
        """Format an added, removed or unchanged link between namespaces."""
        ...

    @abstractmethod
    def _format_context_cycle(self, cycle: Cycle) -> str:
        """Format a cycle present on both sides, as a plain diagram draws it."""
        ...

    @abstractmethod
    def _format_cycle(self, delta: CycleDelta) -> RenderedLink:
        """Format a new or resolved cycle, with details for a new one."""
        ...

    @abstractmethod
    def _format_legend(self, *, unchanged: bool) -> str:
        """Explain every marker; ``unchanged`` says first that nothing changed."""
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


def _first_pair(cycle: Cycle) -> tuple[str, str]:
    """The cycle's pair a plain diagram reaches first, iterating pairs sorted."""
    return min(
        (cycle.namespace_from, cycle.namespace_to),
        (cycle.namespace_to, cycle.namespace_from),
    )
