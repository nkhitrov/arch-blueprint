from __future__ import annotations

import textwrap
from collections.abc import Callable
from string import Template
from typing import Final

from arch_blueprint.domain.graph import Cycle, Tangle
from arch_blueprint.domain.node import Node
from arch_blueprint.renderer.base import (
    CYCLE_HIGHLIGHT_COLOR,
    NEIGHBOR_COLOR,
    BlueprintRenderer,
    CycleRender,
    LinkDecoration,
)
from arch_blueprint.renderer.cycles import (
    cycle_detail_sections,
    tangle_detail_sections,
    tangle_note_id,
    tangle_title,
)
from arch_blueprint.renderer.layout import Layout

#: Top to bottom, as the PlantUML diagrams are drawn: the layers of a project
#: read downwards, and an album leafs through both formats alike.
DIRECTION: Final = "direction: down"

CYCLE_CONNECTION_TEMPLATE: Final = Template(
    '$a <-> $b: $label {style.stroke: "$color"; style.stroke-width: 4}',
)

#: Characters that end or nest a D2 statement, so a bare label cannot contain them.
_LABEL_SPECIALS: Final = frozenset(';{}|#"')


def quote_label(label: str) -> str:
    """Quote a connection label that would otherwise terminate the statement."""
    if not _LABEL_SPECIALS.intersection(label):
        return label
    escaped = label.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


_CYCLE_NOTE_COLOR: Final = "#FADBD8"
_CYCLE_CONTAINER_FILL: Final = "#FEF9E7"
_CYCLE_CONTAINER_STROKE: Final = "#F39C12"

# The title is bold text, not a ``###`` heading: D2 sizes a markdown block by a
# measurement that underestimates heading width, so a heading wraps to a second
# line the block has no room for, and the last import in the note is cut off.
_CYCLE_NOTE_TEMPLATE: Final = Template(
    textwrap.dedent(
        """\
        $note_id: |md
          **$a ↔ $b**

          **$a → $b:**

        $forward_details

          **$b → $a:**

        $backward_details
        | {
          style.fill: "$note_color"
          style.stroke: "$stroke_color"
          style.border-radius: 8
        }
        """,
    ).rstrip(),
)

#: The container every cycle note is drawn in, and the grid inside it.
_CYCLE_NOTES_PATH: Final = '"Cycle Details".grid'

_CYCLE_CONTAINER_TEMPLATE: Final = Template(
    textwrap.dedent(
        """\
        "Cycle Details": {
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
    """Format cycle details as a separate note block (D2 needs them deferred)."""
    forward_details, backward_details = cycle_detail_sections(cycle)
    return _CYCLE_NOTE_TEMPLATE.substitute(
        a=cycle.endpoint_from,
        b=cycle.endpoint_to,
        # Quoted, so the dots stay literal: an id built by replacing them could
        # make two cycles collide (``a.b_c``/``d`` and ``a_b.c``/``d``).
        note_id=f'"cycle {cycle.endpoint_from} {cycle.endpoint_to}"',
        forward_details=forward_details,
        backward_details=backward_details,
        note_color=_CYCLE_NOTE_COLOR,
        stroke_color=CYCLE_HIGHLIGHT_COLOR,
    )


_TANGLE_NOTE_TEMPLATE: Final = Template(
    textwrap.dedent(
        """\
        $note_id: |md
        $body
        | {
          style.fill: "$note_color"
          style.stroke: "$stroke_color"
          style.border-radius: 8
        }
        """,
    ).rstrip(),
)


_TANGLE_TIE_STYLE: Final = (
    f'style.stroke: "{CYCLE_HIGHLIGHT_COLOR}"; style.stroke-dash: 3'
)


def format_tangle_ties(
    tangle: Tangle,
    key: Callable[[str], str] = lambda endpoint: endpoint,
) -> str:
    """Dashed lines from a longer cycle's note to each member of the cycle.

    They tie the note to the cycle rather than to one arrow: the pairs on it
    get no note of their own. Top-level connections, since the note itself sits
    in the notes container; ``key`` spells a member as a connection end.
    """
    note = f"{_CYCLE_NOTES_PATH}.{tangle_note_id(tangle)}"
    return "\n".join(
        f"{note} -- {key(member)} {{{_TANGLE_TIE_STYLE}}}" for member in tangle.members
    )


def format_tangle_note(tangle: Tangle) -> str:
    """A note listing every import on a longer cycle (deferred, like a cycle's)."""
    lines = [f"**{tangle_title(tangle)}**"]
    for heading, imports in tangle_detail_sections(tangle):
        lines += ["", f"**{heading}:**", "", *imports]
    return _TANGLE_NOTE_TEMPLATE.substitute(
        note_id=tangle_note_id(tangle),
        body=textwrap.indent("\n".join(lines), "  "),
        note_color=_CYCLE_NOTE_COLOR,
        stroke_color=CYCLE_HIGHLIGHT_COLOR,
    )


#: Names D2 reads as its own keywords wherever they sit in a key — a module or
#: a function called ``label`` or ``style`` — so they are quoted there. Matched
#: ignoring case, which covers every spelling D2 0.9 rejects and quotes a few
#: it would not mind. Only the ones a Python name can spell.
_D2_KEYWORDS: Final = frozenset(
    {
        "_",
        "animated",
        "bold",
        "class",
        "classes",
        "constraint",
        "direction",
        "fill",
        "filled",
        "font",
        "height",
        "icon",
        "italic",
        "label",
        "layers",
        "left",
        "link",
        "multiple",
        "near",
        "opacity",
        "scenarios",
        "shadow",
        "shape",
        "steps",
        "stroke",
        "style",
        "tooltip",
        "top",
        "underline",
        "vars",
        "width",
    },
)


def key_part(part: str) -> str:
    """One part of a D2 key, quoted where D2 would misread it bare.

    Quoted when D2 would split it (a merged frame ``app.features.core``, a flat
    node's full name), read it as a keyword, or reject it bare (a shadowed
    ``(module)``).
    """
    if "." in part or not part.isidentifier() or part.lower() in _D2_KEYWORDS:
        escaped = part.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return part


def layout_key(layout: Layout, name: str) -> str:
    """``name`` as a D2 key: nested by its frames, a merged chain one part.

    Flat, a drawing has no frames, so the key is the whole name, quoted: one
    box, its dots literal.
    """
    return ".".join(key_part(part) for part in layout.path(name))


def format_title(title: str) -> list[str]:
    """The diagram's title, above everything: the prefix its labels dropped."""
    if not title:
        return []
    return [f"title: {quote_label(title)} {{near: top-center; shape: text}}"]


def label_line(layout: Layout, node_id: str, marker: str = "") -> list[str]:
    """A node's ``label:`` line, only where its key does not already say it.

    D2 labels a node by its last key part; a flat drawing's key is the full
    name, and the label drops the shared prefix.
    """
    label = f"{marker}{layout.label(node_id)}"
    if label == layout.path(node_id)[-1]:
        return []
    return [f'  label: "{label}"']


def format_cycle_notes_container(notes: list[str]) -> str:
    """Wrap cycle notes in a styled box with grid layout."""
    notes_content = "\n\n".join(notes)
    indented_notes = textwrap.indent(notes_content, "    ")
    return _CYCLE_CONTAINER_TEMPLATE.substitute(
        fill=_CYCLE_CONTAINER_FILL,
        stroke=_CYCLE_CONTAINER_STROKE,
        notes=indented_notes,
    )


#: What sets a neighbor's box apart (``--deps``), inside its ``style`` block.
NEIGHBOR_STYLE: Final = (
    f'fill: "{NEIGHBOR_COLOR}"',
    "stroke-dash: 3",
    "opacity: 0.6",
)


def format_neighbor(key: str, layout: Layout, node_id: str) -> str:
    """A node outside the focus: muted and dashed, with no metric blocks."""
    lines = [
        f"{key}: {{",
        "  shape: class",
        *label_line(layout, node_id),
        "  style: {",
        *(f"    {line}" for line in NEIGHBOR_STYLE),
        "  }",
        "}",
    ]
    return "\n".join(lines)


class D2LangRenderer(BlueprintRenderer):
    """D2 diagram renderer (stateless: cycle notes flow through CycleRender)."""

    fmt = "d2"
    cyclic_link_styles = (
        f'style.stroke: "{CYCLE_HIGHLIGHT_COLOR}"',
        "style.stroke-width: 4",
    )

    def _key(self, endpoint: str) -> str:
        """A name's key, spelled through the drawing's layout."""
        return layout_key(self.layout, endpoint)

    def _format_node(self, node: Node, color: str, blocks: list[str]) -> str:
        lines = [
            f"{self._key(node.id)}: {{",
            "  shape: class",
            *label_line(self.layout, node.id),
            "  style: {",
            f'    fill: "{color}"',
            "  }",
        ]
        lines.extend(f"  {block}" for block in blocks)
        lines.append("}")
        return "\n".join(lines)

    def _format_neighbor(self, node: Node) -> str:
        return format_neighbor(self._key(node.id), self.layout, node.id)

    def _format_link(
        self,
        source: str,
        target: str,
        decoration: LinkDecoration,
    ) -> str:
        link = f"{self._key(source)} -> {self._key(target)}"
        if decoration.labels:
            link = f"{link}: {quote_label(', '.join(decoration.labels))}"
        if decoration.styles:
            link = f"{link} {{{'; '.join(decoration.styles)}}}"
        return link

    def _format_cycle(
        self,
        cycle: Cycle,
        decoration: LinkDecoration,
        *,
        details: bool,
    ) -> CycleRender:
        label = "CYCLE"
        if decoration.labels:
            label = f"{label} {' '.join(decoration.labels)}"
        connection = CYCLE_CONNECTION_TEMPLATE.substitute(
            a=self._key(cycle.endpoint_from),
            b=self._key(cycle.endpoint_to),
            label=quote_label(label),
            color=CYCLE_HIGHLIGHT_COLOR,
        )
        if not details:
            return CycleRender(inline=connection)
        return CycleRender(inline=connection, deferred=format_cycle_note(cycle))

    def _format_tangle(self, tangle: Tangle) -> CycleRender:
        return CycleRender(
            inline=format_tangle_ties(tangle, self._key),
            deferred=format_tangle_note(tangle),
        )

    def _combine_output(
        self,
        nodes: list[str],
        links: list[str],
        deferred: list[str],
    ) -> str:
        sections = [
            DIRECTION,
            *format_title(self.layout.title),
            "\n\n".join(nodes),
            "\n".join(links),
        ]
        if deferred:
            sections.append(format_cycle_notes_container(deferred))
        return "\n".join(sections)
