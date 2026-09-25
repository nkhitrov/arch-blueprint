from __future__ import annotations

from typing import Final

from arch_blueprint.diff.model import (
    SHADOWED_SUFFIX,
    ChangeStatus,
    CycleChange,
    CycleDelta,
    display_name,
    is_shadowed,
)
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
from arch_blueprint.renderer.d2 import format_cycle_note, format_cycle_notes_container

# D2 has no spot letter, so the marker goes into the label; D2 already labels a
# dotted key by its last component, which the prefix keeps.
_NODE_PREFIX: Final = {
    ChangeStatus.ADDED: "+ ",
    ChangeStatus.REMOVED: "- ",
    ChangeStatus.CONTEXT: "",
}
_NODE_FILL: Final = {
    ChangeStatus.ADDED: ADDED_COLOR,
    ChangeStatus.REMOVED: REMOVED_COLOR,
    ChangeStatus.CONTEXT: CONTEXT_COLOR,
}

_CONTEXT_FONT: Final = "#2C3E50"
_DASHED: Final = "style.stroke-dash: 5"

_LINK_STYLE: Final = {
    ChangeStatus.ADDED: (
        "added",
        f'style.stroke: "{ADDED_COLOR}"; style.stroke-width: 3',
    ),
    ChangeStatus.REMOVED: (
        "removed",
        f'style.stroke: "{REMOVED_COLOR}"; {_DASHED}',
    ),
}

_NEW_CYCLE_STYLE: Final = (
    f'style.stroke: "{CYCLE_HIGHLIGHT_COLOR}"; style.stroke-width: 4'
)
_RESOLVED_CYCLE_STYLE: Final = f'style.stroke: "{RESOLVED_COLOR}"; {_DASHED}'

_LEGEND: Final = "\n".join(
    [
        "diff_legend: Legend {",
        "  near: top-left",
        f'  added: "+ added" {{style.fill: "{ADDED_COLOR}"}}',
        f'  removed: "- removed" {{style.fill: "{REMOVED_COLOR}"; {_DASHED}}}',
        f'  context: "unchanged, shown for context" {{style.fill: "{CONTEXT_COLOR}"}}',
        f'  new_cycle: "{NEW_CYCLE_LABEL}" {{{_NEW_CYCLE_STYLE}}}',
        f'  resolved: "{RESOLVED_CYCLE_LABEL}" {{{_RESOLVED_CYCLE_STYLE}}}',
        "}",
    ],
)


class D2LangDiffRenderer(DiffRenderer):
    """D2 diff renderer (stateless: cycle notes flow through CycleRender)."""

    fmt = "d2"

    def _format_node(self, node_id: str, status: ChangeStatus) -> str:
        lines = [f"{_key_of(node_id)}: {{", "  shape: class"]
        if _NODE_PREFIX[status] or is_shadowed(node_id):
            lines.append(f'  label: "{_NODE_PREFIX[status]}{display_name(node_id)}"')
        lines += ["  style: {", f'    fill: "{_NODE_FILL[status]}"']
        if status is ChangeStatus.CONTEXT:
            # D2 writes a class name in white, unreadable on the light grey.
            lines.append(f'    font-color: "{_CONTEXT_FONT}"')
        if status is ChangeStatus.REMOVED:
            lines.append("    stroke-dash: 5")
        lines += ["  }", "}"]
        return "\n".join(lines)

    def _format_link(self, source: str, target: str, status: ChangeStatus) -> str:
        label, style = _LINK_STYLE[status]
        return f"{source} -> {target}: {label} {{{style}}}"

    def _format_cycle(self, delta: CycleDelta) -> CycleRender:
        cycle = delta.cycle
        if delta.change is CycleChange.RESOLVED:
            return CycleRender(inline=self._format_resolved(delta))
        connection = (
            f"{cycle.namespace_from} <-> {cycle.namespace_to}: "
            f"{NEW_CYCLE_LABEL} {{{_NEW_CYCLE_STYLE}}}"
        )
        # Only a new cycle gets its imports listed: they are what to fix.
        if delta.change is CycleChange.NEW and self.show_cycle_details:
            return CycleRender(inline=connection, deferred=format_cycle_note(cycle))
        return CycleRender(inline=connection)

    @staticmethod
    def _format_resolved(delta: CycleDelta) -> str:
        """The dependency the cycle left behind; a bare line if none is left."""
        if delta.remaining is None:
            source, target = delta.cycle.namespace_from, delta.cycle.namespace_to
            connector = "--"
        else:
            source, target = delta.remaining
            connector = "->"
        return (
            f"{source} {connector} {target}: "
            f"{RESOLVED_CYCLE_LABEL} {{{_RESOLVED_CYCLE_STYLE}}}"
        )

    def _format_legend(self) -> str:
        return _LEGEND

    def _format_empty(self) -> str:
        return f'direction: right\nno_changes: "{NO_CHANGES_LABEL}" {{shape: text}}'

    def _combine_output(
        self,
        legend: str,
        nodes: list[str],
        links: list[str],
        deferred: list[str],
    ) -> str:
        sections = ["direction: right", legend, "\n\n".join(nodes)]
        if links:
            sections.append("\n".join(links))
        if deferred:
            sections.append(format_cycle_notes_container(deferred))
        return "\n".join(sections)


def _key_of(node_id: str) -> str:
    """A node's D2 key: a shadowed id's last part is quoted, it is not a name."""
    if is_shadowed(node_id):
        return f'{node_id.removesuffix(SHADOWED_SUFFIX)}"{SHADOWED_SUFFIX}"'
    return node_id
