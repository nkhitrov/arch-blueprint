from __future__ import annotations

from typing import Final, Optional

from arch_blueprint.diff.model import (
    ChangeStatus,
    CycleChange,
    CycleDelta,
    OnCycle,
    is_shadowed,
)
from arch_blueprint.diff.render_base import (
    ADDED_COLOR,
    NEW_CYCLE_LABEL,
    NO_CHANGES_LABEL,
    REMOVED_COLOR,
    RESOLVED_COLOR,
    RESOLVED_CYCLE_LABEL,
    UNCHANGED_LABEL,
    DiffRenderer,
)
from arch_blueprint.domain.graph import Cycle, Tangle
from arch_blueprint.renderer.base import CYCLE_HIGHLIGHT_COLOR, CycleRender
from arch_blueprint.renderer.puml import (
    format_cycle_note,
    format_package,
    format_tangle_note,
    puml_header,
)

# A changed node: spot letter, stereotype text, fill and a dashed border. The
# text is what survives a grey-scale image, the color what the eye catches first.
_CHANGED_NODE: Final = {
    ChangeStatus.ADDED: f"<<(+, {ADDED_COLOR}) added>> {ADDED_COLOR};line.dashed",
    ChangeStatus.REMOVED: (
        f"<<(-, {REMOVED_COLOR}) removed>> {REMOVED_COLOR};line.dashed"
    ),
}

_LINK_ARROW: Final = {
    ChangeStatus.ADDED: (f"-[{ADDED_COLOR},dashed,thickness=3]->", " : added"),
    ChangeStatus.REMOVED: (f"-[{REMOVED_COLOR},dashed,thickness=2]->", " : removed"),
    ChangeStatus.CONTEXT: ("--->", ""),
}

# An unchanged link on a longer cycle: as a plain diagram draws it when the cycle
# is unchanged, marked like a new or resolved pair when the cycle is not.
_ON_CYCLE_ARROW: Final = {
    OnCycle.UNCHANGED: (f"-[{CYCLE_HIGHLIGHT_COLOR},bold]->", ""),
    OnCycle.NEW: (
        f"-[{CYCLE_HIGHLIGHT_COLOR},dashed,thickness=3]->",
        f" : {NEW_CYCLE_LABEL}",
    ),
    OnCycle.RESOLVED: (f"-[{RESOLVED_COLOR},dashed]->", f" : {RESOLVED_CYCLE_LABEL}"),
}

_LEGEND_LINES: Final = (
    UNCHANGED_LABEL,
    f"<color:{ADDED_COLOR}>**+ added**</color> module / dependency (dashed)",
    f"<color:{REMOVED_COLOR}>**- removed**</color> module / dependency (dashed)",
    f"<color:{CYCLE_HIGHLIGHT_COLOR}>**{NEW_CYCLE_LABEL}**</color> cycle introduced"
    " (dashed)",
    f"<color:{RESOLVED_COLOR}>**{RESOLVED_CYCLE_LABEL}**</color> dependency that"
    " remains",
)


class PlantUmlDiffRenderer(DiffRenderer):
    """PlantUML diff renderer."""

    fmt = "puml"

    def _format_node(self, node_id: str, status: ChangeStatus) -> str:
        marker = _CHANGED_NODE.get(status) or f"<<(M, {self._depth_color(node_id)})>>"
        if is_shadowed(node_id):  # quoted: the id's last part is not a name
            name = self._name_of(node_id)
            return f'class "{name}" as {node_id} {marker}'
        return f"class {node_id} {marker}"

    def _format_group(self, namespace: str, nodes: list[str]) -> list[str]:
        return format_package(namespace, nodes)

    def _format_link(
        self,
        source: str,
        target: str,
        status: ChangeStatus,
        on_cycle: Optional[OnCycle],
    ) -> str:
        if status is ChangeStatus.CONTEXT and on_cycle is not None:
            arrow, label = _ON_CYCLE_ARROW[on_cycle]
        else:
            arrow, label = _LINK_ARROW[status]
        return f"{_ref(source)} {arrow} {_ref(target)}{label}"

    def _format_tangle(self, tangle: Tangle) -> CycleRender:
        return CycleRender(inline=format_tangle_note(tangle, _ref))

    def _format_context_cycle(self, cycle: Cycle) -> str:
        arrow = f"<-[{CYCLE_HIGHLIGHT_COLOR},bold]->"
        return f"{_ref(cycle.endpoint_from)} {arrow} {_ref(cycle.endpoint_to)}"

    def _format_cycle(self, delta: CycleDelta, *, details: bool) -> CycleRender:
        cycle = delta.cycle
        if delta.change is CycleChange.RESOLVED:
            return CycleRender(inline=self._format_resolved(delta))
        arrow = f"<-[{CYCLE_HIGHLIGHT_COLOR},dashed,thickness=3]->"
        ends = f"{_ref(cycle.endpoint_from)} {arrow} {_ref(cycle.endpoint_to)}"
        link = f"{ends} : {NEW_CYCLE_LABEL}"
        if details:
            link = f"{link}\n{format_cycle_note(cycle)}"
        return CycleRender(inline=link)

    @staticmethod
    def _format_resolved(delta: CycleDelta) -> str:
        """The dependency the cycle left behind; a bare line if none is left."""
        if delta.remaining is None:
            source, target = delta.cycle.endpoint_from, delta.cycle.endpoint_to
            connector = f"-[{RESOLVED_COLOR},dashed]-"
        else:
            source, target = delta.remaining
            connector = f"-[{RESOLVED_COLOR},dashed]->"
        return f"{_ref(source)} {connector} {_ref(target)} : {RESOLVED_CYCLE_LABEL}"

    def _format_legend(self, *, unchanged: bool) -> str:
        lines = ([f"**{NO_CHANGES_LABEL}**"] if unchanged else []) + [*_LEGEND_LINES]
        body = "\n".join(f"  {line}" for line in lines)
        return f"legend top left\n{body}\nendlegend"

    def _format_empty(self) -> str:
        header = puml_header(nested=self.options.nested)
        return f'{header}note "{NO_CHANGES_LABEL}" as no_changes\n@enduml\n'

    def _combine_output(
        self,
        legend: str,
        nodes: list[str],
        links: list[str],
        deferred: list[str],
    ) -> str:
        nodes_section = "\n".join(nodes)
        links_section = "\n".join(links) + "\n" if links else ""
        header = puml_header(nested=self.options.nested)
        return f"{header}{legend}\n\n{nodes_section}\n\n{links_section}@enduml\n"


def _ref(endpoint: str) -> str:
    """An arrow endpoint: a shadowed id is quoted, PlantUML rejects it bare."""
    return f'"{endpoint}"' if is_shadowed(endpoint) else endpoint
