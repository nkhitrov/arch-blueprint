from __future__ import annotations

from typing import Final, Optional

from arch_blueprint.diff.model import (
    SHADOWED_SUFFIX,
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
from arch_blueprint.renderer.base import (
    CYCLE_HIGHLIGHT_COLOR,
    CycleRender,
    LinkDecoration,
)
from arch_blueprint.renderer.d2 import (
    CYCLE_CONNECTION_TEMPLATE,
    DIRECTION,
    flat_key,
    format_cycle_note,
    format_cycle_notes_container,
    format_tangle_note,
    format_tangle_ties,
    quote_label,
)

# D2 has no spot letter, so a changed node's marker goes into the label; D2
# already labels a dotted key by its last component, which the prefix keeps.
_CHANGED_NODE: Final = {
    ChangeStatus.ADDED: ("+ ", ADDED_COLOR),
    ChangeStatus.REMOVED: ("- ", REMOVED_COLOR),
}

_DASHED: Final = "style.stroke-dash: 5"

#: Per status: the link's label and styles; a context link is a plain one.
_LINK_STYLE: Final[dict[ChangeStatus, tuple[str, tuple[str, ...]]]] = {
    ChangeStatus.ADDED: (
        "added",
        (f'style.stroke: "{ADDED_COLOR}"', "style.stroke-width: 3", _DASHED),
    ),
    ChangeStatus.REMOVED: (
        "removed",
        (f'style.stroke: "{REMOVED_COLOR}"', _DASHED),
    ),
    ChangeStatus.CONTEXT: ("", ()),
}

_NEW_CYCLE_STYLE: Final = (
    f'style.stroke: "{CYCLE_HIGHLIGHT_COLOR}"; style.stroke-width: 4; {_DASHED}'
)
_RESOLVED_CYCLE_STYLE: Final = f'style.stroke: "{RESOLVED_COLOR}"; {_DASHED}'

# An unchanged link on a longer cycle: as a plain diagram draws it when the cycle
# is unchanged, marked like a new or resolved pair when the cycle is not.
_ON_CYCLE_STYLE: Final[dict[OnCycle, tuple[str, tuple[str, ...]]]] = {
    OnCycle.UNCHANGED: (
        "",
        (f'style.stroke: "{CYCLE_HIGHLIGHT_COLOR}"', "style.stroke-width: 4"),
    ),
    OnCycle.NEW: (
        NEW_CYCLE_LABEL,
        (f'style.stroke: "{CYCLE_HIGHLIGHT_COLOR}"', "style.stroke-width: 4", _DASHED),
    ),
    OnCycle.RESOLVED: (
        RESOLVED_CYCLE_LABEL,
        (f'style.stroke: "{RESOLVED_COLOR}"', _DASHED),
    ),
}

_LEGEND_ITEMS: Final = (
    f'  unchanged: "{UNCHANGED_LABEL}"',
    f'  added: "+ added" {{style.fill: "{ADDED_COLOR}"; {_DASHED}}}',
    f'  removed: "- removed" {{style.fill: "{REMOVED_COLOR}"; {_DASHED}}}',
    f'  new_cycle: "{NEW_CYCLE_LABEL}" {{{_NEW_CYCLE_STYLE}}}',
    f'  resolved: "{RESOLVED_CYCLE_LABEL}" {{{_RESOLVED_CYCLE_STYLE}}}',
)
_METRIC_LEGEND_ITEM: Final = f'  metric: "{METRIC_CHANGE_LABEL}" {{shape: text}}'


class D2LangDiffRenderer(DiffRenderer):
    """D2 diff renderer (stateless: cycle notes flow through CycleRender)."""

    fmt = "d2"

    def _key_of(self, node_id: str) -> str:
        """A node's D2 key: quoted whole when flat, as a plain diagram's."""
        return _nested_key(node_id) if self.options.nested else flat_key(node_id)

    def _format_node(self, node_id: str, status: ChangeStatus, rows: list[str]) -> str:
        prefix, fill = _CHANGED_NODE.get(status, ("", self._depth_color(node_id)))
        lines = [f"{self._key_of(node_id)}: {{", "  shape: class"]
        if prefix or is_shadowed(node_id):
            lines.append(f'  label: "{prefix}{self._name_of(node_id)}"')
        lines += ["  style: {", f'    fill: "{fill}"']
        if prefix:
            lines.append("    stroke-dash: 5")
        lines.append("  }")
        lines += [f"  {row}" for row in rows]  # where a plain diagram puts them
        lines.append("}")
        return "\n".join(lines)

    def _format_link(
        self,
        source: str,
        target: str,
        status: ChangeStatus,
        on_cycle: Optional[OnCycle],
        decoration: LinkDecoration,
    ) -> str:
        if status is ChangeStatus.CONTEXT and on_cycle is not None:
            label, styles = _ON_CYCLE_STYLE[on_cycle]
        else:
            label, styles = _LINK_STYLE[status]
        # The status, then the metric labels joined as a plain diagram joins them.
        text = " ".join(part for part in (label, ", ".join(decoration.labels)) if part)
        link = f"{self._key_of(source)} -> {self._key_of(target)}"
        if text:
            link = f"{link}: {quote_label(text)}"
        styles = (*styles, *decoration.styles)
        if styles:
            link = f"{link} {{{'; '.join(styles)}}}"
        return link

    def _format_tangle(self, tangle: Tangle) -> CycleRender:
        return CycleRender(
            inline=format_tangle_ties(tangle, self._key_of),
            deferred=format_tangle_note(tangle),
        )

    def _format_context_cycle(self, cycle: Cycle, decoration: LinkDecoration) -> str:
        return CYCLE_CONNECTION_TEMPLATE.substitute(
            a=self._key_of(cycle.endpoint_from),
            b=self._key_of(cycle.endpoint_to),
            label=quote_label(_cycle_label("CYCLE", decoration)),
            color=CYCLE_HIGHLIGHT_COLOR,
        )

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
        label = quote_label(_cycle_label(NEW_CYCLE_LABEL, decoration))
        ends = f"{self._key_of(cycle.endpoint_from)} <-> "
        ends += self._key_of(cycle.endpoint_to)
        connection = f"{ends}: {label} {{{_NEW_CYCLE_STYLE}}}"
        if details:
            return CycleRender(inline=connection, deferred=format_cycle_note(cycle))
        return CycleRender(inline=connection)

    def _format_resolved(self, delta: CycleDelta, decoration: LinkDecoration) -> str:
        """The dependency the cycle left behind; a bare line if none is left."""
        if delta.remaining is None:
            source, target = delta.cycle.endpoint_from, delta.cycle.endpoint_to
            connector = "--"
        else:
            source, target = delta.remaining
            connector = "->"
        label = quote_label(_cycle_label(RESOLVED_CYCLE_LABEL, decoration))
        return (
            f"{self._key_of(source)} {connector} {self._key_of(target)}: "
            f"{label} {{{_RESOLVED_CYCLE_STYLE}}}"
        )

    def _format_legend(self, *, unchanged: bool, metrics: bool) -> str:
        head = ["diff_legend: Legend {", "  near: top-left"]
        if unchanged:
            head.append(f'  no_changes: "{NO_CHANGES_LABEL}" {{shape: text}}')
        items = [*_LEGEND_ITEMS, *([_METRIC_LEGEND_ITEM] if metrics else [])]
        return "\n".join([*head, *items, "}"])

    def _format_empty(self) -> str:
        return f'{DIRECTION}\nno_changes: "{NO_CHANGES_LABEL}" {{shape: text}}'

    def _combine_output(
        self,
        legend: str,
        nodes: list[str],
        links: list[str],
        deferred: list[str],
    ) -> str:
        sections = [DIRECTION, legend, "\n\n".join(nodes)]
        if links:
            sections.append("\n".join(links))
        if deferred:
            sections.append(format_cycle_notes_container(deferred))
        return "\n".join(sections)


def _cycle_label(label: str, decoration: LinkDecoration) -> str:
    """A cycle's label, then its metric labels, as a plain diagram writes them."""
    return " ".join((label, *decoration.labels))


def _nested_key(node_id: str) -> str:
    """A node's D2 key: a shadowed id's last part is quoted, it is not a name."""
    if is_shadowed(node_id):
        return f'{node_id.removesuffix(SHADOWED_SUFFIX)}"{SHADOWED_SUFFIX}"'
    return node_id
