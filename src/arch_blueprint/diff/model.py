from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Final, Optional

from arch_blueprint.domain.graph import BlueprintGraph, Cycle

#: Appended to a node id that another shown node lies under — a module ``pkg.py``
#: replaced by a package ``pkg/`` puts both in one diff, and neither format can
#: draw a class that is also a container. Not an identifier a module can have.
SHADOWED_SUFFIX: Final = "(module)"


def shadowed_id(node_id: str) -> str:
    """The id a node is drawn under when another shown node lies under it."""
    return f"{node_id}.{SHADOWED_SUFFIX}"


def display_name(node_id: str) -> str:
    """A node's own name, the last part of its id: what a diagram labels it."""
    parts = node_id.split(".")
    if parts[-1] == SHADOWED_SUFFIX and len(parts) > 1:
        return parts[-2]
    return parts[-1]


def is_shadowed(node_id: str) -> bool:
    """Whether ``node_id`` is a :func:`shadowed_id`."""
    return node_id.endswith(f".{SHADOWED_SUFFIX}")


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

    ``remaining`` is the one direction a resolved cycle left behind, as a
    ``(source_ns, target_ns)`` pair, or ``None`` when both went (and always for
    a new cycle). It is what a resolved cycle is drawn as: after breaking a
    cycle, who depends on whom is the thing a reviewer needs to see.
    """

    change: CycleChange
    cycle: Cycle
    remaining: Optional[tuple[str, str]] = None


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
