from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from arch_blueprint.domain.graph import BlueprintGraph, Cycle


class ChangeStatus(Enum):
    """How a node or link differs between the two graphs."""

    ADDED = "added"
    REMOVED = "removed"
    #: Unchanged, drawn only because a change touches it.
    CONTEXT = "context"


class CycleChange(Enum):
    """How a namespace cycle differs between the two graphs."""

    NEW = "new"
    RESOLVED = "resolved"


@dataclass(frozen=True)
class CycleDelta:
    """A cycle that appeared or disappeared.

    ``cycle`` comes from the side where it exists — the new graph for a
    :attr:`CycleChange.NEW` one, the old graph for a resolved one — so its
    edges name the imports that close (or used to close) it.
    """

    change: CycleChange
    cycle: Cycle


@dataclass(frozen=True)
class GraphDiff:
    """What changed between two graphs, reduced to what is worth drawing.

    ``graph`` holds only the shown nodes and the edges of changed links, so its
    ``groups`` are the containers those links need. Statuses sit in side maps
    keyed by node id / namespace pair, as metrics do on a plain graph.

    A namespace pair whose cycle changed is in ``cycle_changes`` and **not** in
    ``link_status``: it is drawn as one cycle connection, not as two arrows.
    """

    graph: BlueprintGraph
    node_status: Mapping[str, ChangeStatus]
    link_status: Mapping[tuple[str, str], ChangeStatus]
    cycle_changes: tuple[CycleDelta, ...]

    @property
    def is_empty(self) -> bool:
        """True when nothing was added or removed: context alone is no change."""
        return (
            not self.link_status
            and not self.cycle_changes
            and all(
                status is ChangeStatus.CONTEXT for status in self.node_status.values()
            )
        )
