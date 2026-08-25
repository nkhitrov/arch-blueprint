from __future__ import annotations

import textwrap
from string import Template
from typing import Final

from arch_blueprint.domain.graph import Cycle
from arch_blueprint.domain.node import Node, NodeKind
from arch_blueprint.renderer.base import (
    CYCLE_HIGHLIGHT_COLOR,
    BlueprintRenderer,
    CycleRender,
    LinkDecoration,
)
from arch_blueprint.renderer.cycles import cycle_detail_sections

_HEADER: Final = textwrap.dedent(
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
          **$ns_a -> $ns_b:**
        $forward_details
          **$ns_b -> $ns_a:**
        $backward_details
        end note
        """,
    ).rstrip(),
)

# PlantUML stereotype spot letter per node kind.
_SPOT_LETTER: Final = {NodeKind.MODULE: "M"}
_DEFAULT_SPOT: Final = "M"


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
        body = "\n".join(f"  {line}" for node in nodes for line in node.splitlines())
        return [f"package {namespace} {{\n{body}\n}}"]

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

    def _format_cycle(self, cycle: Cycle, decoration: LinkDecoration) -> CycleRender:
        color = CYCLE_HIGHLIGHT_COLOR
        link = f"{cycle.namespace_from} <-[{color},bold]-> {cycle.namespace_to}"
        if decoration.labels:
            link = f"{link} : {' '.join(decoration.labels)}"

        if not self.options.show_cycle_details:
            return CycleRender(inline=link)

        forward_details, backward_details = cycle_detail_sections(cycle)
        note = _CYCLE_NOTE_TEMPLATE.substitute(
            ns_a=cycle.namespace_from,
            ns_b=cycle.namespace_to,
            forward_details=forward_details,
            backward_details=backward_details,
        )
        return CycleRender(inline=f"{link}\n{note}")

    def _combine_output(
        self,
        nodes: list[str],
        links: list[str],
        deferred: list[str],
    ) -> str:
        nodes_section = "\n".join(nodes)
        links_section = "\n".join(links) + "\n" if links else ""
        return f"{_HEADER}{nodes_section}\n\n{links_section}@enduml\n"
