from __future__ import annotations

import textwrap
from string import Template
from typing import Final

from arch_blueprint.domain.graph import Cycle, Link
from arch_blueprint.domain.node import Node
from arch_blueprint.renderer.base import (
    CYCLE_HIGHLIGHT_COLOR,
    BlueprintRenderer,
    LegendSection,
    LinkDecoration,
    RenderedLink,
    RenderSections,
)
from arch_blueprint.renderer.details import (
    cycle_detail_blocks,
    link_detail_block,
)

CYCLE_CONNECTION_TEMPLATE: Final = Template(
    '$ns_a <-> $ns_b: $label {style.stroke: "$color"; style.stroke-width: 4}',
)

#: Labels are stacked one per line; ``quote_label`` escapes the break for D2.
_LABEL_BREAK: Final = "\n"

#: Characters that end or nest a D2 statement, so a bare label cannot contain them.
#: A newline is one of them — it ends the statement outright, which is why a
#: multi-line label must be quoted and its breaks escaped.
_LABEL_SPECIALS: Final = frozenset(';{}|#"\n')


def quote_label(label: str) -> str:
    """Quote a connection label that would otherwise terminate the statement."""
    if not _LABEL_SPECIALS.intersection(label):
        return label
    escaped = (
        label.replace("\\", "\\\\")
        .replace('"', '\\"')
        # Last: this one introduces a backslash that must not be escaped again.
        .replace("\n", "\\n")
    )
    return f'"{escaped}"'


_CYCLE_NOTE_COLOR: Final = "#FADBD8"
#: A link's detail note is informational, never an alarm: keeping it off the
#: cycle palette is what stops a flagged link from reading as a cycle.
_LINK_NOTE_COLOR: Final = "#ECF0F1"
_LINK_NOTE_STROKE: Final = "#7F8C8D"
_DETAILS_CONTAINER_FILL: Final = "#FEF9E7"
_DETAILS_CONTAINER_STROKE: Final = "#F39C12"

# The title is bold text, not a ``###`` heading: D2 sizes a markdown block by a
# measurement that underestimates heading width, so a heading wraps to a second
# line the block has no room for, and the last import in the note is cut off.
_CYCLE_NOTE_TEMPLATE: Final = Template(
    textwrap.dedent(
        """\
        $note_id: |md
          **$ns_a ↔ $ns_b**

          **$forward_source → $forward_target:**

        $forward_details

          **$backward_source → $backward_target:**

        $backward_details
        | {
          style.fill: "$note_color"
          style.stroke: "$stroke_color"
          style.border-radius: 8
        }
        """,
    ).rstrip(),
)

_LINK_NOTE_TEMPLATE: Final = Template(
    textwrap.dedent(
        """\
        $note_id: |md
          ### $source \u2192 $target

        $details
        | {
          style.fill: "$note_color"
          style.stroke: "$stroke_color"
          style.border-radius: 8
        }
        """,
    ).rstrip(),
)

_LEGEND_TEMPLATE: Final = Template(
    textwrap.dedent(
        """\
        "Legend": |md
          ### Legend

        $rows
        | {
          style.fill: "$fill"
          style.stroke: "$stroke"
          style.border-radius: 8
        }
        """,
    ).rstrip(),
)

_DETAILS_CONTAINER_TEMPLATE: Final = Template(
    textwrap.dedent(
        """\
        "Details": {
          style.fill: "$fill"
          style.stroke: "$stroke"
          style.stroke-width: 2
          style.border-radius: 12

          grid: {
            label: ""
            grid-rows: 1
            grid-gap: 32
            style.stroke: transparent
            style.fill: transparent

        $notes
          }
        }""",
    ),
)


def format_cycle_note(cycle: Cycle) -> str:
    """Format cycle details as a separate note block (D2 needs them deferred).

    Shared with the diff renderer, so a cycle reads the same in both.
    """
    forward, backward = cycle_detail_blocks(cycle)
    ns_a_safe = cycle.namespace_from.replace(".", "_")
    ns_b_safe = cycle.namespace_to.replace(".", "_")
    return _CYCLE_NOTE_TEMPLATE.substitute(
        ns_a=cycle.namespace_from,
        ns_b=cycle.namespace_to,
        note_id=f"cycle_{ns_a_safe}_{ns_b_safe}",
        forward_source=forward.source,
        forward_target=forward.target,
        backward_source=backward.source,
        backward_target=backward.target,
        forward_details=forward.lines,
        backward_details=backward.lines,
        note_color=_CYCLE_NOTE_COLOR,
        stroke_color=CYCLE_HIGHLIGHT_COLOR,
    )


def format_link_detail_note(link: Link) -> str:
    """Format one link's imports as a deferred note block.

    Nothing can go inline: D2 has no note-on-connection, so the block carries
    its own heading and is placed with the cycle notes.
    """
    source_safe = link.source_namespace.replace(".", "_")
    target_safe = link.target_namespace.replace(".", "_")
    block = link_detail_block(link)
    return _LINK_NOTE_TEMPLATE.substitute(
        source=block.source,
        target=block.target,
        note_id=f"link_{source_safe}_{target_safe}",
        details=block.lines,
        note_color=_LINK_NOTE_COLOR,
        stroke_color=_LINK_NOTE_STROKE,
    )


def format_cycle_notes_container(notes: list[str]) -> str:
    """Wrap the deferred detail notes in a styled box with grid layout."""
    notes_content = "\n\n".join(notes)
    indented_notes = textwrap.indent(notes_content, "    ")
    return _DETAILS_CONTAINER_TEMPLATE.substitute(
        fill=_DETAILS_CONTAINER_FILL,
        stroke=_DETAILS_CONTAINER_STROKE,
        notes=indented_notes,
    )


class D2LangRenderer(BlueprintRenderer):
    """D2 diagram renderer (stateless: cycle notes flow through RenderedLink)."""

    fmt = "d2"

    def _format_node(self, node: Node, color: str, blocks: list[str]) -> str:
        lines = [
            f"{node.id}: {{",
            "  shape: class",
            "  style: {",
            f'    fill: "{color}"',
            "  }",
        ]
        lines.extend(f"  {block}" for block in blocks)
        lines.append("}")
        return "\n".join(lines)

    def _format_link(
        self,
        source: str,
        target: str,
        decoration: LinkDecoration,
    ) -> str:
        link = f"{source} -> {target}"
        if decoration.labels:
            link = f"{link}: {quote_label(_LABEL_BREAK.join(decoration.labels))}"
        if decoration.styles:
            link = f"{link} {{{'; '.join(decoration.styles)}}}"
        return link

    def _format_cycle(self, cycle: Cycle, decoration: LinkDecoration) -> RenderedLink:
        label = "CYCLE"
        if decoration.labels:
            label = _LABEL_BREAK.join([label, *decoration.labels])
        connection = CYCLE_CONNECTION_TEMPLATE.substitute(
            ns_a=cycle.namespace_from,
            ns_b=cycle.namespace_to,
            label=quote_label(label),
            color=CYCLE_HIGHLIGHT_COLOR,
        )
        if not self.options.show_cycle_details:
            return RenderedLink(inline=connection)
        return RenderedLink(inline=connection, deferred=format_cycle_note(cycle))

    def _format_link_detail(self, link: Link) -> RenderedLink:
        """Defer the imports to a note: a six-line arrow label inflates the diagram."""
        return RenderedLink(inline="", deferred=format_link_detail_note(link))

    def _combine_output(self, sections: RenderSections) -> str:
        parts = [
            "direction: right",
            "\n\n".join(sections.nodes),
            "\n".join(sections.links),
        ]
        if sections.deferred:
            parts.append(format_cycle_notes_container(sections.deferred))
        legend = self._format_legend(sections.legend)
        if legend:
            parts.append(legend)
        return "\n".join(parts)

    @staticmethod
    def _format_legend(sections: tuple[LegendSection, ...]) -> str:
        """A styled markdown box explaining the shown metrics, or nothing.

        Appended last on purpose: D2 nests by dotted name, and anything emitted
        before the node section would displace the diagram itself.
        """
        if not sections:
            return ""
        blocks: list[str] = []
        for section in sections:
            rows = [f"  - {row}" for row in section.rows]
            if section.title:
                rows.insert(0, f"  **{section.title}**\n")
            blocks.append("\n".join(rows))
        return _LEGEND_TEMPLATE.substitute(
            rows="\n\n".join(blocks),
            fill=_DETAILS_CONTAINER_FILL,
            stroke=_DETAILS_CONTAINER_STROKE,
        )
