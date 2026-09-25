from __future__ import annotations

import textwrap
from typing import Final

from arch_blueprint.diff.model import ChangeStatus, CycleChange, CycleDelta
from arch_blueprint.diff.render_base import (
    ADDED_COLOR,
    CONTEXT_COLOR,
    NEW_CYCLE_LABEL,
    NO_CHANGES_LABEL,
    REMOVED_COLOR,
    RESOLVED_COLOR,
    RESOLVED_CYCLE_LABEL,
    DiffRenderer,
)
from arch_blueprint.renderer.base import CYCLE_HIGHLIGHT_COLOR, CycleRender
from arch_blueprint.renderer.puml import (
    PUML_HEADER,
    format_cycle_note,
    format_package,
)

# Spot letter and stereotype text per status: the text is what survives a
# grey-scale image, the spot and color what the eye catches first.
_NODE_STEREOTYPE: Final = {
    ChangeStatus.ADDED: f"<<(+, {ADDED_COLOR}) added>>",
    ChangeStatus.REMOVED: f"<<(-, {REMOVED_COLOR}) removed>> #line.dashed",
    ChangeStatus.CONTEXT: f"<<(M, {CONTEXT_COLOR})>>",
}

_LINK_ARROW: Final = {
    ChangeStatus.ADDED: (f"-[{ADDED_COLOR},bold]->", "added"),
    ChangeStatus.REMOVED: (f"-[{REMOVED_COLOR},dashed]->", "removed"),
}

_LEGEND: Final = textwrap.dedent(
    f"""\
    legend top left
      <color:{ADDED_COLOR}>**+ added**</color> module / dependency
      <color:{REMOVED_COLOR}>**- removed**</color> module / dependency (dashed)
      <color:{RESOLVED_COLOR}>**M**</color> unchanged, shown for context
      <color:{CYCLE_HIGHLIGHT_COLOR}>**{NEW_CYCLE_LABEL}**</color> cycle introduced
      <color:{RESOLVED_COLOR}>**{RESOLVED_CYCLE_LABEL}**</color> dependency that remains
    endlegend""",
)


class PlantUmlDiffRenderer(DiffRenderer):
    """PlantUML diff renderer."""

    fmt = "puml"

    def _format_node(self, node_id: str, status: ChangeStatus) -> str:
        return f"class {node_id} {_NODE_STEREOTYPE[status]}"

    def _format_group(self, namespace: str, nodes: list[str]) -> list[str]:
        return format_package(namespace, nodes)

    def _format_link(self, source: str, target: str, status: ChangeStatus) -> str:
        arrow, label = _LINK_ARROW[status]
        return f"{source} {arrow} {target} : {label}"

    def _format_cycle(self, delta: CycleDelta) -> CycleRender:
        cycle = delta.cycle
        if delta.change is CycleChange.RESOLVED:
            return CycleRender(inline=self._format_resolved(delta))
        arrow = f"<-[{CYCLE_HIGHLIGHT_COLOR},bold]->"
        link = (
            f"{cycle.namespace_from} {arrow} {cycle.namespace_to} : {NEW_CYCLE_LABEL}"
        )
        # Only a new cycle gets its imports listed: they are what to fix.
        if delta.change is CycleChange.NEW and self.show_cycle_details:
            link = f"{link}\n{format_cycle_note(cycle)}"
        return CycleRender(inline=link)

    @staticmethod
    def _format_resolved(delta: CycleDelta) -> str:
        """The dependency the cycle left behind; a bare line if none is left."""
        if delta.remaining is None:
            source, target = delta.cycle.namespace_from, delta.cycle.namespace_to
            connector = f"-[{RESOLVED_COLOR},dashed]-"
        else:
            source, target = delta.remaining
            connector = f"-[{RESOLVED_COLOR},dashed]->"
        return f"{source} {connector} {target} : {RESOLVED_CYCLE_LABEL}"

    def _format_legend(self) -> str:
        return _LEGEND

    def _format_empty(self) -> str:
        return f'{PUML_HEADER}note "{NO_CHANGES_LABEL}" as no_changes\n@enduml\n'

    def _combine_output(
        self,
        legend: str,
        nodes: list[str],
        links: list[str],
        deferred: list[str],
    ) -> str:
        nodes_section = "\n".join(nodes)
        links_section = "\n".join(links) + "\n" if links else ""
        return f"{PUML_HEADER}{legend}\n\n{nodes_section}\n\n{links_section}@enduml\n"
