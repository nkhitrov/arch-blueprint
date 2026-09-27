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
    METRIC_CHANGE_LABEL,
    NEW_CYCLE_LABEL,
    NO_CHANGES_LABEL,
    REMOVED_COLOR,
    RESOLVED_COLOR,
    RESOLVED_CYCLE_LABEL,
    UNCHANGED_LABEL,
    DiffRenderer,
)
from arch_blueprint.domain.graph import Cycle, Tangle
from arch_blueprint.domain.node import Node
from arch_blueprint.renderer.base import (
    CYCLE_HIGHLIGHT_COLOR,
    CycleRender,
    LinkDecoration,
)
from arch_blueprint.renderer.layout import Frame
from arch_blueprint.renderer.puml import (
    class_head,
    format_cycle_note,
    format_frame,
    format_tangle_note,
    puml_header,
    spot_letter,
)

# A changed node: spot letter, stereotype text, fill and a dashed border. The
# text is what survives a grey-scale image, the color what the eye catches first.
_CHANGED_NODE: Final = {
    ChangeStatus.ADDED: f"<<(+, {ADDED_COLOR}) added>> {ADDED_COLOR};line.dashed",
    ChangeStatus.REMOVED: (
        f"<<(-, {REMOVED_COLOR}) removed>> {REMOVED_COLOR};line.dashed"
    ),
}

#: Per status: the arrow's styles and its label; a context link is a plain one.
_LINK_ARROW: Final[dict[ChangeStatus, tuple[tuple[str, ...], str]]] = {
    ChangeStatus.ADDED: ((ADDED_COLOR, "dashed", "thickness=3"), "added"),
    ChangeStatus.REMOVED: ((REMOVED_COLOR, "dashed", "thickness=2"), "removed"),
    ChangeStatus.CONTEXT: ((), ""),
}

# An unchanged link on a longer cycle: as a plain diagram draws it when the cycle
# is unchanged, marked like a new or resolved pair when the cycle is not.
_ON_CYCLE_ARROW: Final[dict[OnCycle, tuple[tuple[str, ...], str]]] = {
    OnCycle.UNCHANGED: ((CYCLE_HIGHLIGHT_COLOR, "bold"), ""),
    OnCycle.NEW: ((CYCLE_HIGHLIGHT_COLOR, "dashed", "thickness=3"), NEW_CYCLE_LABEL),
    OnCycle.RESOLVED: ((RESOLVED_COLOR, "dashed"), RESOLVED_CYCLE_LABEL),
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


def _labelled(link: str, *labels: str) -> str:
    """``link`` with its non-empty labels after a colon, as a plain diagram does."""
    text = " ".join(label for label in labels if label)
    return f"{link} : {text}" if text else link


class PlantUmlDiffRenderer(DiffRenderer):
    """PlantUML diff renderer."""

    fmt = "puml"

    def _format_node(self, node: Node, status: ChangeStatus, rows: list[str]) -> str:
        node_id = node.id
        marker = (
            _CHANGED_NODE.get(status)
            or f"<<({spot_letter(node.kind)}, {self._depth_color(node_id)})>>"
        )
        head = class_head(self._name_of(node_id), node_id, marker)
        if not rows:
            return head
        body = "\n".join(f"  {row}" for row in rows)
        return f"{head} {{\n{body}\n}}"

    def _format_frame(self, frame: Frame, items: list[str]) -> list[str]:
        return format_frame(frame, items)

    def _format_link(
        self,
        source: str,
        target: str,
        status: ChangeStatus,
        on_cycle: Optional[OnCycle],
        decoration: LinkDecoration,
    ) -> str:
        if status is ChangeStatus.CONTEXT and on_cycle is not None:
            styles, label = _ON_CYCLE_ARROW[on_cycle]
        else:
            styles, label = _LINK_ARROW[status]
        styles = (*styles, *decoration.styles)
        arrow = f"-[{','.join(styles)}]->" if styles else "--->"
        return _labelled(
            f"{_ref(source)} {arrow} {_ref(target)}",
            label,
            *decoration.labels,
        )

    def _format_tangle(self, tangle: Tangle) -> CycleRender:
        return CycleRender(inline=format_tangle_note(tangle, _ref))

    def _format_context_cycle(self, cycle: Cycle, decoration: LinkDecoration) -> str:
        arrow = f"<-[{CYCLE_HIGHLIGHT_COLOR},bold]->"
        link = f"{_ref(cycle.endpoint_from)} {arrow} {_ref(cycle.endpoint_to)}"
        return _labelled(link, *decoration.labels)

    def _format_cycle(
        self,
        delta: CycleDelta,
        decoration: LinkDecoration,
        *,
        details: bool,
    ) -> CycleRender:
        cycle = delta.cycle
        if delta.change is CycleChange.RESOLVED:
            return CycleRender(inline=self._format_resolved(delta, decoration))
        arrow = f"<-[{CYCLE_HIGHLIGHT_COLOR},dashed,thickness=3]->"
        link = _labelled(
            f"{_ref(cycle.endpoint_from)} {arrow} {_ref(cycle.endpoint_to)}",
            NEW_CYCLE_LABEL,
            *decoration.labels,
        )
        if details:
            link = f"{link}\n{format_cycle_note(cycle)}"
        return CycleRender(inline=link)

    @staticmethod
    def _format_resolved(delta: CycleDelta, decoration: LinkDecoration) -> str:
        """The dependency the cycle left behind; a bare line if none is left."""
        if delta.remaining is None:
            source, target = delta.cycle.endpoint_from, delta.cycle.endpoint_to
            connector = f"-[{RESOLVED_COLOR},dashed]-"
        else:
            source, target = delta.remaining
            connector = f"-[{RESOLVED_COLOR},dashed]->"
        return _labelled(
            f"{_ref(source)} {connector} {_ref(target)}",
            RESOLVED_CYCLE_LABEL,
            *decoration.labels,
        )

    def _format_legend(self, *, unchanged: bool, metrics: bool) -> str:
        lines = ([f"**{NO_CHANGES_LABEL}**"] if unchanged else []) + [*_LEGEND_LINES]
        if metrics:
            lines.append(METRIC_CHANGE_LABEL)
        body = "\n".join(f"  {line}" for line in lines)
        return f"legend top left\n{body}\nendlegend"

    def _format_empty(self) -> str:
        return f'{puml_header()}note "{NO_CHANGES_LABEL}" as no_changes\n@enduml\n'

    def _combine_output(
        self,
        legend: str,
        nodes: list[str],
        links: list[str],
        deferred: list[str],
    ) -> str:
        nodes_section = "\n".join(nodes)
        links_section = "\n".join(links) + "\n" if links else ""
        header = puml_header(self.layout.title)
        return f"{header}{legend}\n\n{nodes_section}\n\n{links_section}@enduml\n"


def _ref(endpoint: str) -> str:
    """An arrow endpoint: a shadowed id is quoted, PlantUML rejects it bare."""
    return f'"{endpoint}"' if is_shadowed(endpoint) else endpoint
