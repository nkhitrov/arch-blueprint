from __future__ import annotations

import textwrap

from arch_blueprint.domain.graph import Cycle, Edge


def format_edges(edges: frozenset[Edge]) -> list[str]:
    """Format edges as ``- src_short → tgt_short`` lines (namespace stripped)."""
    lines: list[str] = []
    for edge in sorted(edges, key=lambda e: (e.source, e.target)):
        src_short = edge.source.removeprefix(edge.source_namespace + ".")
        tgt_short = edge.target.removeprefix(edge.target_namespace + ".")
        lines.append(f"- {src_short} → {tgt_short}")
    return lines


def cycle_detail_sections(cycle: Cycle, indent: str = "  ") -> tuple[str, str]:
    """Return (forward, backward) edge-detail blocks, indented for a renderer.

    Shared by every renderer so cycle-detail formatting lives in one place.
    """
    forward = "\n".join(format_edges(cycle.forward_edges))
    backward = "\n".join(format_edges(cycle.backward_edges))
    return textwrap.indent(forward, indent), textwrap.indent(backward, indent)
