from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Final, Optional

from arch_blueprint.domain.graph import BlueprintGraph, Cycle, Tangle

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


def depth_of(node_id: str) -> int:
    """A drawn node's dotted depth, as ``DepthMetric`` counts it: the fill color.

    A shadowed node keeps its module's depth, so it keeps its module's color.
    """
    return len(node_id.split(".")) - (1 if is_shadowed(node_id) else 0)


class ChangeStatus(Enum):
    """How a node or link differs between the two graphs."""

    ADDED = "added"
    REMOVED = "removed"
    #: Unchanged, drawn as context: as it looks on a plain diagram.
    CONTEXT = "context"


class CycleChange(Enum):
    """How a cycle differs between the two graphs."""

    NEW = "new"
    RESOLVED = "resolved"


@dataclass(frozen=True)
class CycleDelta:
    """A cycle that appeared or disappeared.

    ``cycle`` comes from the side where it exists — the new graph for a
    :attr:`CycleChange.NEW` one, the old graph for a resolved one — so its
    edges name the imports that close (or used to close) it.

    ``remaining`` is the one direction a resolved cycle left behind, as a
    ``(source_endpoint, target_endpoint)`` pair, or ``None`` when both went (and
    always for a new cycle). It is what a resolved cycle is drawn as: after breaking a
    cycle, who depends on whom is the thing a reviewer needs to see.
    """

    change: CycleChange
    cycle: Cycle
    remaining: Optional[tuple[str, str]] = None


@dataclass(frozen=True)
class TangleDelta:
    """A longer cycle (a :class:`Tangle`) that appeared or disappeared.

    Tangles compare by their set of endpoints: one that grows or shrinks is a
    different cycle — the old one resolved, a new one in its place. ``tangle``
    comes from the side where it exists, as for :class:`CycleDelta`.
    """

    change: CycleChange
    tangle: Tangle


class OnCycle(Enum):
    """How the longer cycle a drawn link lies on changed, if it lies on one."""

    UNCHANGED = "unchanged"
    NEW = "new"
    RESOLVED = "resolved"


@dataclass(frozen=True)
class GraphDiff:
    """What changed between two graphs, with the context it is drawn against.

    ``graph`` holds the shown nodes and the edges of the shown links, so its
    ``groups`` are the containers those links need. Statuses sit in side maps
    keyed by node id / endpoint pair, as metrics do on a plain graph. Unchanged
    nodes and links are :attr:`ChangeStatus.CONTEXT` — all of them, or with
    ``changes_only`` just the nodes a change touches and no links.

    An endpoint pair whose cycle changed is in ``cycle_changes`` and **not** in
    ``link_status``: it is drawn as one cycle connection, not as two arrows. A
    cycle present on both sides is in ``context_cycles``, likewise.

    Longer cycles are drawn on their links rather than as one connection, so
    their links stay in ``link_status``; ``tangle_changes`` and
    ``context_tangles`` say which cycle each lies on. The links of a changed
    tangle are shown even with ``changes_only``: without them the cycle that
    appeared or went could not be traced.
    """

    graph: BlueprintGraph
    node_status: Mapping[str, ChangeStatus]
    link_status: Mapping[tuple[str, str], ChangeStatus]
    cycle_changes: tuple[CycleDelta, ...]
    context_cycles: tuple[Cycle, ...] = ()
    tangle_changes: tuple[TangleDelta, ...] = ()
    context_tangles: tuple[Tangle, ...] = ()

    @property
    def is_empty(self) -> bool:
        """True when nothing was added or removed: context alone is no change.

        A tangle can change with no drawn link changing — through a package
        facade's imports, which are not drawn — so it is checked on its own.
        """
        return (
            not self.cycle_changes
            and not self.tangle_changes
            and all(
                status is ChangeStatus.CONTEXT
                for status in (*self.node_status.values(), *self.link_status.values())
            )
        )
