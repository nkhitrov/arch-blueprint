from __future__ import annotations

import textwrap
from string import Template
from typing import Final

from arch_blueprint.modules.models import CyclicDependency
from arch_blueprint.modules.module import BlueprintModule
from arch_blueprint.modules.renderers.base import (
    CYCLE_HIGHLIGHT_COLOR,
    BlueprintModuleRenderer,
    RendererOptions,
)

_MODULE_TEMPLATE: Final = Template(
    textwrap.dedent(
        """\
        $name: {
          shape: class
          style: {
            fill: "$fill_color"
          }
        }
        """,
    ).rstrip(),
)

_CYCLE_CONNECTION_TEMPLATE: Final = Template(
    '$ns_a <-> $ns_b: CYCLE {style.stroke: "$color"; style.stroke-width: 4}',
)

_CYCLE_NOTE_COLOR: Final = "#FADBD8"
_CYCLE_CONTAINER_FILL: Final = "#FEF9E7"
_CYCLE_CONTAINER_STROKE: Final = "#F39C12"

_CYCLE_NOTE_TEMPLATE: Final = Template(
    textwrap.dedent(
        """\
        $note_id: |md
          ### $ns_a ↔ $ns_b

          **$ns_a → $ns_b:**

        $forward_details

          **$ns_b → $ns_a:**

        $backward_details
        | {
          style.fill: "$note_color"
          style.stroke: "$stroke_color"
          style.border-radius: 8
        }
        """,
    ).rstrip(),
)

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


class D2ModuleRenderer(BlueprintModuleRenderer):
    """D2 diagram renderer."""

    def __init__(self, options: RendererOptions | None = None) -> None:
        super().__init__(options)
        self._cycle_notes: list[str] = []

    def render(self, target_modules: list[BlueprintModule]) -> str:
        """Override to reset cycle notes state before rendering."""
        self._cycle_notes = []
        return super().render(target_modules)

    def _format_module(self, module: BlueprintModule, color: str) -> str:
        return _MODULE_TEMPLATE.substitute(name=module.name, fill_color=color)

    def _format_link(self, source: str, target: str) -> str:
        return f"{source} -> {target}"

    def _format_cycle(self, cycle: CyclicDependency) -> str:
        connection = _CYCLE_CONNECTION_TEMPLATE.substitute(
            ns_a=cycle.namespace_from,
            ns_b=cycle.namespace_to,
            color=CYCLE_HIGHLIGHT_COLOR,
        )

        if self.options.show_cycle_details:
            self._cycle_notes.append(self._format_cycle_note(cycle))

        return connection

    def _format_cycle_note(self, cycle: CyclicDependency) -> str:
        """Format cycle details as a separate note block."""
        forward_details = "\n".join(self._format_edges(cycle.forward_edges))
        backward_details = "\n".join(self._format_edges(cycle.backward_edges))
        ns_a_safe = cycle.namespace_from.replace(".", "_")
        ns_b_safe = cycle.namespace_to.replace(".", "_")

        return _CYCLE_NOTE_TEMPLATE.substitute(
            ns_a=cycle.namespace_from,
            ns_b=cycle.namespace_to,
            note_id=f"cycle_{ns_a_safe}_{ns_b_safe}",
            forward_details=textwrap.indent(forward_details, "  "),
            backward_details=textwrap.indent(backward_details, "  "),
            note_color=_CYCLE_NOTE_COLOR,
            stroke_color=CYCLE_HIGHLIGHT_COLOR,
        )

    def _combine_output(self, modules: list[str], links: list[str]) -> str:
        sections = ["direction: right", "\n\n".join(modules), "\n".join(links)]

        if self._cycle_notes:
            cycle_notes_container = self._format_cycle_notes_container()
            sections.append(cycle_notes_container)

        return "\n".join(sections)

    def _format_cycle_notes_container(self) -> str:
        """Wrap cycle notes in a styled box with grid layout."""
        notes_content = "\n\n".join(self._cycle_notes)
        indented_notes = textwrap.indent(notes_content, "    ")
        return _CYCLE_CONTAINER_TEMPLATE.substitute(
            fill=_CYCLE_CONTAINER_FILL,
            stroke=_CYCLE_CONTAINER_STROKE,
            notes=indented_notes,
        )
