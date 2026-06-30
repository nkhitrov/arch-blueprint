from __future__ import annotations

import textwrap
from string import Template
from typing import Final

from arch_blueprint.domain.graph import Cycle
from arch_blueprint.domain.node import Node
from arch_blueprint.metrics import BlockBuilder
from arch_blueprint.renderer.base import (
    CYCLE_HIGHLIGHT_COLOR,
    BlueprintRenderer,
    CycleRender,
)
from arch_blueprint.renderer.cycles import cycle_detail_sections

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


class _D2BlockBuilder:
    """Renders metric rows as D2 fields inside a node block."""

    def row(self, label: str, value: str) -> str:
        return f"{label}: {value}"


class D2LangRenderer(BlueprintRenderer):
    """D2 diagram renderer (stateless: cycle notes flow through CycleRender)."""

    def _block_builder(self) -> BlockBuilder:
        return _D2BlockBuilder()

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

    def _format_link(self, source: str, target: str) -> str:
        return f"{source} -> {target}"

    def _format_cycle(self, cycle: Cycle) -> CycleRender:
        connection = _CYCLE_CONNECTION_TEMPLATE.substitute(
            ns_a=cycle.namespace_from,
            ns_b=cycle.namespace_to,
            color=CYCLE_HIGHLIGHT_COLOR,
        )
        if not self.options.show_cycle_details:
            return CycleRender(inline=connection)
        return CycleRender(inline=connection, deferred=self._format_cycle_note(cycle))

    def _format_cycle_note(self, cycle: Cycle) -> str:
        """Format cycle details as a separate note block (D2 needs them deferred)."""
        forward_details, backward_details = cycle_detail_sections(cycle)
        ns_a_safe = cycle.namespace_from.replace(".", "_")
        ns_b_safe = cycle.namespace_to.replace(".", "_")
        return _CYCLE_NOTE_TEMPLATE.substitute(
            ns_a=cycle.namespace_from,
            ns_b=cycle.namespace_to,
            note_id=f"cycle_{ns_a_safe}_{ns_b_safe}",
            forward_details=forward_details,
            backward_details=backward_details,
            note_color=_CYCLE_NOTE_COLOR,
            stroke_color=CYCLE_HIGHLIGHT_COLOR,
        )

    def _combine_output(
        self,
        nodes: list[str],
        links: list[str],
        deferred: list[str],
    ) -> str:
        sections = ["direction: right", "\n\n".join(nodes), "\n".join(links)]
        if deferred:
            sections.append(self._format_cycle_notes_container(deferred))
        return "\n".join(sections)

    @staticmethod
    def _format_cycle_notes_container(notes: list[str]) -> str:
        """Wrap cycle notes in a styled box with grid layout."""
        notes_content = "\n\n".join(notes)
        indented_notes = textwrap.indent(notes_content, "    ")
        return _CYCLE_CONTAINER_TEMPLATE.substitute(
            fill=_CYCLE_CONTAINER_FILL,
            stroke=_CYCLE_CONTAINER_STROKE,
            notes=indented_notes,
        )
