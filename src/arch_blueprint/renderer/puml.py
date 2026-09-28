from __future__ import annotations

import textwrap
from collections.abc import Callable
from string import Template
from typing import Final

from arch_blueprint.domain.graph import Cycle, Tangle
from arch_blueprint.domain.node import Node, NodeKind
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
from arch_blueprint.renderer.layout import Frame

# PlantUML reads the dots of ``class a.b.c`` as packages and nests the class in
# them. With no separator an id is one opaque name: every frame is declared
# (``package "label" as id``) and every box labelled, from the drawing's layout.
PUML_HEADER: Final = textwrap.dedent(
    """\
    @startuml
    !theme amiga

    top to bottom direction
    hide empty members
    set separator none

    """,
)


def escape_creole(text: str) -> str:
    """``text`` shown literally where PlantUML reads creole markup.

    A title, a package's label and a note are creole: ``__init__`` there is
    ``init`` underlined. ``~`` escapes the markup; a quoted class label is not
    creole and needs none.
    """
    return text.replace("__", "~__")


def puml_header(title: str = "") -> str:
    """The diagram preamble, with a ``title`` line when the drawing has one."""
    if not title:
        return PUML_HEADER
    return f"{PUML_HEADER}title {escape_creole(title)}\n\n"


_CYCLE_NOTE_TEMPLATE: Final = Template(
    textwrap.dedent(
        """\
        note on link
          **$a -> $b:**
        $forward_details
          **$b -> $a:**
        $backward_details
        end note
        """,
    ).rstrip(),
)


def spot_letter(kind: NodeKind) -> str:
    """The letter in a node's spot: what kind of thing the box is."""
    return kind.letter


def format_frame(frame: Frame, items: list[str]) -> list[str]:
    """Declare ``frame`` as a package under its label, holding rendered ``items``.

    Aliased by the full name, so an arrow ending on the frame names it as it
    names any node: with no separator, the dots in the alias are just letters.
    No stereotype: on a package PlantUML draws one as literal text inside the
    frame rather than as a colored spot, which is noise on every container.
    """
    body = "\n".join(f"  {line}" for item in items for line in item.splitlines())
    label = escape_creole(frame.label)
    return [f'package "{label}" as {frame.namespace} {{\n{body}\n}}']


#: What sets a neighbor's box apart (``--deps``): a dashed border and grey text.
NEIGHBOR_STYLE: Final = "#line.dashed;text:7F8C8D"


def neighbor_marker(kind: NodeKind) -> str:
    """The spot and box style of a node outside the focus."""
    return f"<<({spot_letter(kind)}, {NEIGHBOR_COLOR})>> {NEIGHBOR_STYLE}"


def class_head(label: str, node_id: str, marker: str) -> str:
    """``class`` declaring ``node_id``, labelled ``label`` where the two differ."""
    if label == node_id:
        return f"class {node_id} {marker}"
    return f'class "{label}" as {node_id} {marker}'


def format_cycle_note(cycle: Cycle) -> str:
    """The ``note on link`` listing both directions' imports of a cycle."""
    forward_details, backward_details = cycle_detail_sections(cycle)
    return _CYCLE_NOTE_TEMPLATE.substitute(
        a=escape_creole(cycle.endpoint_from),
        b=escape_creole(cycle.endpoint_to),
        forward_details=escape_creole(forward_details),
        backward_details=escape_creole(backward_details),
    )


def format_tangle_note(
    tangle: Tangle,
    ref: Callable[[str], str] = lambda endpoint: endpoint,
) -> str:
    """A note listing every import on a longer cycle, tied to each member.

    The dotted lines are what ties it to the cycle rather than to one arrow:
    the pairs on it get no note of their own, so this is the one place its
    imports are listed. ``ref`` spells a member as an arrow endpoint.
    """
    note_id = tangle_note_id(tangle)
    lines = [f"note as {note_id}", f"  **{escape_creole(tangle_title(tangle))}**"]
    for heading, imports in tangle_detail_sections(tangle):
        lines.append(f"  **{escape_creole(heading)}:**")
        lines.extend(f"  {escape_creole(line)}" for line in imports)
    lines.append("end note")
    lines.extend(f"{note_id} .. {ref(member)}" for member in tangle.members)
    return "\n".join(lines)


class PlantUmlRenderer(BlueprintRenderer):
    """PlantUML diagram renderer."""

    fmt = "puml"
    cyclic_link_styles = (CYCLE_HIGHLIGHT_COLOR, "bold")

    def _format_node(self, node: Node, color: str, blocks: list[str]) -> str:
        marker = f"<<({spot_letter(node.kind)}, {color})>>"
        head = class_head(self.layout.label(node.id), node.id, marker)
        if not blocks:
            return head
        body = "\n".join(f"  {block}" for block in blocks)
        return f"{head} {{\n{body}\n}}"

    def _format_neighbor(self, node: Node) -> str:
        return class_head(
            self.layout.label(node.id),
            node.id,
            neighbor_marker(node.kind),
        )

    def _format_frame(self, frame: Frame, items: list[str]) -> list[str]:
        """Declare the frame as a package, so links point at a real element."""
        return format_frame(frame, items)

    def _format_link(
        self,
        source: str,
        target: str,
        decoration: LinkDecoration,
    ) -> str:
        arrow = f"-[{','.join(decoration.styles)}]->" if decoration.styles else "--->"
        link = f"{source} {arrow} {target}"
        if decoration.labels:
            link = f"{link} : {' '.join(decoration.labels)}"
        return link

    def _format_cycle(
        self,
        cycle: Cycle,
        decoration: LinkDecoration,
        *,
        details: bool,
    ) -> CycleRender:
        color = CYCLE_HIGHLIGHT_COLOR
        link = f"{cycle.endpoint_from} <-[{color},bold]-> {cycle.endpoint_to}"
        if decoration.labels:
            link = f"{link} : {' '.join(decoration.labels)}"

        if not details:
            return CycleRender(inline=link)

        return CycleRender(inline=f"{link}\n{format_cycle_note(cycle)}")

    def _format_tangle(self, tangle: Tangle) -> CycleRender:
        return CycleRender(inline=format_tangle_note(tangle))

    def _combine_output(
        self,
        nodes: list[str],
        links: list[str],
        deferred: list[str],
    ) -> str:
        nodes_section = "\n".join(nodes)
        links_section = "\n".join(links) + "\n" if links else ""
        header = puml_header(self.layout.title)
        return f"{header}{nodes_section}\n\n{links_section}@enduml\n"
