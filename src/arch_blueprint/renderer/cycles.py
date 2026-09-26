from __future__ import annotations

import textwrap
from collections import defaultdict

from arch_blueprint.domain.graph import Cycle, Edge, Tangle

#: Marks the imports of a package ``__init__.py`` in a tangle's note: they close
#: the cycle but have no arrow on the diagram.
HIDDEN_LINK_NOTE = "package __init__, not drawn"


def _short(module: str, endpoint: str) -> str:
    """``module`` relative to the endpoint it is drawn at — its own name if it is it.

    Both sides of an import are cut the same way, whatever the link level: at
    the namespace level ``a.b.c`` at endpoint ``a.b`` is ``c``; at the module
    level the endpoint is the module itself, and ``a.b`` is ``b``.
    """
    if module == endpoint:
        return module.rsplit(".", 1)[-1]
    return module.removeprefix(f"{endpoint}.")


def format_edges(edges: frozenset[Edge]) -> list[str]:
    """Format edges as ``- source → target`` lines, each cut to its endpoint."""
    lines: list[str] = []
    for edge in sorted(edges, key=lambda e: (e.source, e.target)):
        source = _short(edge.source, edge.source_endpoint)
        target = _short(edge.target, edge.target_endpoint)
        lines.append(f"- {source} → {target}")
    return lines


def cycle_detail_sections(cycle: Cycle, indent: str = "  ") -> tuple[str, str]:
    """Return (forward, backward) edge-detail blocks, indented for a renderer.

    Shared by every renderer so cycle-detail formatting lives in one place.
    """
    forward = "\n".join(format_edges(cycle.forward_edges))
    backward = "\n".join(format_edges(cycle.backward_edges))
    return textwrap.indent(forward, indent), textwrap.indent(backward, indent)


def tangle_detail_sections(tangle: Tangle) -> list[tuple[str, list[str]]]:
    """``(heading, import lines)`` per link of a tangle, drawn links first.

    A heading is ``source -> target``; the facade imports that close the cycle
    without an arrow are grouped the same way and say so.
    """
    sections = [
        (f"{link.source} -> {link.target}", format_edges(link.edges))
        for link in tangle.links
    ]
    hidden: dict[tuple[str, str], set[Edge]] = defaultdict(set)
    for edge in tangle.hidden_edges:
        hidden[(edge.source_endpoint, edge.target_endpoint)].add(edge)
    sections += [
        (
            f"{source} -> {target} ({HIDDEN_LINK_NOTE})",
            format_edges(frozenset(hidden[(source, target)])),
        )
        for source, target in sorted(hidden)
    ]
    return sections


def tangle_title(tangle: Tangle) -> str:
    """What a tangle's note is headed with: the endpoints on the cycle."""
    return f"Cycle: {', '.join(tangle.members)}"


def tangle_note_id(tangle: Tangle) -> str:
    """An identifier unique per tangle: tangles never share an endpoint."""
    return f"tangle_{tangle.members[0].replace('.', '_')}"
