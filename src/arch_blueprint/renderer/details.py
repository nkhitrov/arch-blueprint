from __future__ import annotations

import textwrap
from dataclasses import dataclass
from typing import Optional

from arch_blueprint.domain.graph import Cycle, Edge, Link


@dataclass(frozen=True)
class DetailBlock:
    """One direction of a detail note: its two ends, and the imports between them.

    ``source`` and ``target`` are what the note's header names -- namespaces
    normally, but a module wherever every edge shares that end. Hoisting it is
    not cosmetic: on wemake's 41-import note the repeated end is half the width
    of every line, and it is the same string 41 times.
    """

    source: str
    target: str
    lines: str


def _short(name: str, namespace: str) -> str:
    """Drop the namespace a name sits under; a no-op when the two are equal."""
    return name.removeprefix(namespace + ".")


def _only(names: set[str]) -> Optional[str]:
    """The single name in ``names``, or ``None`` when there is more than one."""
    return next(iter(names)) if len(names) == 1 else None


def detail_block(
    source: str,
    target: str,
    edges: frozenset[Edge],
    indent: str = "  ",
) -> DetailBlock:
    """Format the edges of one direction, hoisting whichever end is constant.

    Sorted by ``(source, target)`` because ``edges`` is a frozenset and the
    output is compared byte-for-byte.
    """
    ordered = sorted(edges, key=lambda edge: (edge.source, edge.target))
    one_source = _only({edge.source for edge in ordered})
    one_target = _only({edge.target for edge in ordered})

    if one_source is not None:
        source = one_source
        rows = [_short(edge.target, target) for edge in ordered]
    elif one_target is not None:
        target = one_target
        rows = [_short(edge.source, source) for edge in ordered]
    else:
        rows = [
            f"{_short(edge.source, source)} → {_short(edge.target, target)}"
            for edge in ordered
        ]

    body = "\n".join(f"- {row}" for row in rows)
    return DetailBlock(
        source=source,
        target=target,
        lines=textwrap.indent(body, indent),
    )


def cycle_detail_blocks(
    cycle: Cycle,
    indent: str = "  ",
) -> tuple[DetailBlock, DetailBlock]:
    """Return the (forward, backward) blocks of a cycle, in that order."""
    forward = detail_block(
        cycle.namespace_from,
        cycle.namespace_to,
        cycle.forward_edges,
        indent,
    )
    backward = detail_block(
        cycle.namespace_to,
        cycle.namespace_from,
        cycle.backward_edges,
        indent,
    )
    return forward, backward


def link_detail_block(link: Link, indent: str = "  ") -> DetailBlock:
    """Return the block for one link: the same shape, with one direction."""
    return detail_block(
        link.source_namespace,
        link.target_namespace,
        link.edges,
        indent,
    )
