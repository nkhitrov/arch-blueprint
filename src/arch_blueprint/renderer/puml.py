from __future__ import annotations

import textwrap
from string import Template
from typing import Final

from arch_blueprint.models import CyclicDependency
from arch_blueprint.modules import BlueprintModule
from arch_blueprint.renderer.base import CYCLE_HIGHLIGHT_COLOR, BlueprintRenderer

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


class PlantUmlRenderer(BlueprintRenderer):
    """PlantUML diagram renderer."""

    def _format_module(self, module: BlueprintModule, color: str) -> str:
        return f"class {module.name} <<(M, {color})>>"

    def _format_link(self, source: str, target: str) -> str:
        return f"{source} ---> {target}"

    def _format_cycle(self, cycle: CyclicDependency) -> str:
        color = CYCLE_HIGHLIGHT_COLOR
        link = f"{cycle.namespace_from} <-[{color},bold]-> {cycle.namespace_to}"

        if not self.options.show_cycle_details:
            return link

        forward_details = "\n".join(self._format_edges(cycle.forward_edges))
        backward_details = "\n".join(self._format_edges(cycle.backward_edges))

        note = _CYCLE_NOTE_TEMPLATE.substitute(
            ns_a=cycle.namespace_from,
            ns_b=cycle.namespace_to,
            forward_details=textwrap.indent(forward_details, "  "),
            backward_details=textwrap.indent(backward_details, "  "),
        )
        return f"{link}\n{note}"

    def _combine_output(self, modules: list[str], links: list[str]) -> str:
        modules_section = "\n".join(modules)
        links_section = "\n".join(links) + "\n" if links else ""
        return f"{_HEADER}{modules_section}\n\n{links_section}@enduml\n"
