from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar, Final

from arch_blueprint.diff.model import ChangeStatus, CycleDelta, GraphDiff
from arch_blueprint.renderer.base import CycleRender, wrap_groups

# One palette for every format, so a puml and a d2 diff read the same. Every
# marker also carries text: a diff pasted as a grey-scale image stays legible.
ADDED_COLOR: Final = "#2ECC71"
REMOVED_COLOR: Final = "#E74C3C"
CONTEXT_COLOR: Final = "#D5D8DC"
RESOLVED_COLOR: Final = "#95A5A6"

NEW_CYCLE_LABEL: Final = "NEW CYCLE"
RESOLVED_CYCLE_LABEL: Final = "cycle resolved"
NO_CHANGES_LABEL: Final = "No architectural changes"


class DiffRenderer(ABC):
    """Template Method for drawing a :class:`GraphDiff`, like ``BlueprintRenderer``.

    Stateless: the fixed algorithm is legend, nodes (wrapped in their groups),
    changed links, then changed cycles. An empty diff is still a valid diagram,
    so a CI job always has a picture to post.
    """

    #: Output format id; concrete renderers must set it.
    fmt: ClassVar[str] = ""

    def __init__(self, *, show_cycle_details: bool = True) -> None:
        if not self.fmt:
            msg = f"{type(self).__name__} must set a non-empty 'fmt'"
            raise TypeError(msg)
        self.show_cycle_details = show_cycle_details

    def render(self, diff: GraphDiff) -> str:
        """Template method: orchestrates the diff rendering algorithm."""
        if diff.is_empty:
            return self._format_empty()
        rendered = [
            (node.id, self._format_node(node.id, diff.node_status[node.id]))
            for node in diff.graph.nodes
        ]
        nodes = wrap_groups(diff.graph.groups, rendered, self._format_group)
        links = [
            self._format_link(source, target, status)
            for (source, target), status in diff.link_status.items()
        ]
        deferred: list[str] = []
        for delta in diff.cycle_changes:
            cycle = self._format_cycle(delta)
            links.append(cycle.inline)
            if cycle.deferred is not None:
                deferred.append(cycle.deferred)
        return self._combine_output(self._format_legend(), nodes, links, deferred)

    def _format_group(self, namespace: str, nodes: list[str]) -> list[str]:
        """Wrap one namespace's nodes; by default, do not wrap (D2 nests itself)."""
        return nodes

    @abstractmethod
    def _format_node(self, node_id: str, status: ChangeStatus) -> str:
        """Format a node marked as added, removed or context."""
        ...

    @abstractmethod
    def _format_link(self, source: str, target: str, status: ChangeStatus) -> str:
        """Format an added or removed link between namespaces."""
        ...

    @abstractmethod
    def _format_cycle(self, delta: CycleDelta) -> CycleRender:
        """Format a new or resolved cycle, with details for a new one."""
        ...

    @abstractmethod
    def _format_legend(self) -> str:
        """Explain every marker the diagram uses."""
        ...

    @abstractmethod
    def _format_empty(self) -> str:
        """A complete diagram saying nothing changed."""
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
