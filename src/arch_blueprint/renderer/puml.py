from __future__ import annotations

import textwrap
from string import Template
from typing import Final

from arch_blueprint.domain.graph import Cycle, Link
from arch_blueprint.domain.node import Node, NodeKind
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

PUML_HEADER: Final = textwrap.dedent(
    """\
    @startuml
    !theme amiga

    top to bottom direction
    hide empty members

    """,
)

_CYCLE_NOTE_TEMPLATE: Final = Template(
    textwrap.dedent(
        """\
        note on link
          **$forward_source -> $forward_target:**
        $forward_details
          **$backward_source -> $backward_target:**
        $backward_details
        end note
        """,
    ).rstrip(),
)

_LINK_NOTE_TEMPLATE: Final = Template(
    textwrap.dedent(
        """\
        note on link
          **$source -> $target:**
        $details
        end note
        """,
    ).rstrip(),
)

# PlantUML stereotype spot letter per node kind.
#: PlantUML expands this two-character escape inside a label into a line break.
#: A real newline cannot be used: a statement ends at the end of its line.
_LABEL_BREAK: Final = "\\n"

_SPOT_LETTER: Final = {NodeKind.MODULE: "M"}
_DEFAULT_SPOT: Final = "M"


def format_package(namespace: str, nodes: list[str]) -> list[str]:
    """Declare ``namespace`` as a package holding the already-rendered ``nodes``."""
    body = "\n".join(f"  {line}" for node in nodes for line in node.splitlines())
    return [f"package {namespace} {{\n{body}\n}}"]


def format_cycle_note(cycle: Cycle) -> str:
    """The ``note on link`` listing both directions' imports of a cycle.

    Shared with the diff renderer, so a cycle reads the same in both.
    """
    forward, backward = cycle_detail_blocks(cycle)
    return _CYCLE_NOTE_TEMPLATE.substitute(
        forward_source=forward.source,
        forward_target=forward.target,
        backward_source=backward.source,
        backward_target=backward.target,
        forward_details=forward.lines,
        backward_details=backward.lines,
    )


class PlantUmlRenderer(BlueprintRenderer):
    """PlantUML diagram renderer."""

    fmt = "puml"

    def _format_node(self, node: Node, color: str, blocks: list[str]) -> str:
        spot = _SPOT_LETTER.get(node.kind, _DEFAULT_SPOT)
        head = f"class {node.id} <<({spot}, {color})>>"
        if not blocks:
            return head
        body = "\n".join(f"  {block}" for block in blocks)
        return f"{head} {{\n{body}\n}}"

    def _format_group(self, namespace: str, nodes: list[str]) -> list[str]:
        """Declare the namespace as a package so links point at a real element.

        PlantUML would otherwise infer the container from the dotted class names
        and resolve the arrow to it, which happens to render the same — but only
        because every endpoint is a prefix of some declared class. Declaring it
        makes the emitted source say what it means.

        No stereotype: on a package PlantUML draws one as literal text inside the
        frame rather than as a colored spot, which is noise on every container.
        """
        return format_package(namespace, nodes)

    def _format_link(
        self,
        source: str,
        target: str,
        decoration: LinkDecoration,
    ) -> str:
        arrow = f"-[{','.join(decoration.styles)}]->" if decoration.styles else "--->"
        link = f"{source} {arrow} {target}"
        if decoration.labels:
            link = f"{link} : {_LABEL_BREAK.join(decoration.labels)}"
        return link

    def _format_link_detail(self, link: Link) -> RenderedLink:
        """Attach the note to the arrow by adjacency, as a cycle's note is.

        ``note on link`` binds to the most recently declared connection, so there
        is nothing to defer and nothing to name.
        """
        block = link_detail_block(link)
        note = _LINK_NOTE_TEMPLATE.substitute(
            source=block.source,
            target=block.target,
            details=block.lines,
        )
        return RenderedLink(inline=note)

    def _format_cycle(self, cycle: Cycle, decoration: LinkDecoration) -> RenderedLink:
        color = CYCLE_HIGHLIGHT_COLOR
        link = f"{cycle.namespace_from} <-[{color},bold]-> {cycle.namespace_to}"
        if decoration.labels:
            link = f"{link} : {_LABEL_BREAK.join(decoration.labels)}"

        if not self.options.show_cycle_details:
            return RenderedLink(inline=link)

        return RenderedLink(inline=f"{link}\n{format_cycle_note(cycle)}")

    def _combine_output(self, sections: RenderSections) -> str:
        nodes_section = "\n".join(sections.nodes)
        links = "\n".join(sections.links) + "\n" if sections.links else ""
        legend = self._legend(sections.legend)
        return f"{PUML_HEADER}{nodes_section}\n\n{links}{legend}@enduml\n"

    @staticmethod
    def _legend(sections: tuple[LegendSection, ...]) -> str:
        """A ``legend`` block, or nothing when no metric is shown.

        Rows are indented on purpose: an unindented line starting with ``class``
        or ``package`` would be picked up by the golden structure invariants.
        """
        if not sections:
            return ""
        blocks: list[str] = []
        for section in sections:
            rows = [f"  {row}" for row in section.rows]
            if section.title:
                rows.insert(0, f"  {section.title}")
            blocks.append("\n".join(rows))
        return "legend right\n" + "\n\n".join(blocks) + "\nendlegend\n\n"
