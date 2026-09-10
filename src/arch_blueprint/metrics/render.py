from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar, Final, Optional, Protocol, runtime_checkable

from arch_blueprint.domain.graph import MetricValue
from arch_blueprint.metrics.base import MetricTarget


@dataclass(frozen=True)
class RenderContext:
    """What a render plugin is given: minimal and format-aware.

    ``fmt`` lets a plugin branch per output format (``"puml"`` / ``"d2"``) so it
    can emit format-specific text or styling without the library knowing about it.
    """

    fmt: str


@dataclass(frozen=True)
class RenderFragment:
    """What a render plugin returns; the renderer places it by the metric target.

    ``text`` becomes a node body line (NODE) or an edge label (LINK). ``style`` is
    a raw, format-specific payload the renderer injects into the edge's style slot.
    ``detail`` asks the renderer to spell out the imports behind the link, the way
    a cycle's note does -- a request, not content: the plugin has no edges in hand
    and no business emitting a format's markup.
    """

    text: str = ""
    style: str = ""
    detail: bool = False


@runtime_checkable
class RenderPlugin(Protocol):
    """A pluggable way to render a metric value.

    Render plugins are registered in a :class:`RenderRegistry`; a new one can be
    added without changing any library code. Metrics reference one by ``name``.
    """

    name: str
    attaches_to: MetricTarget

    def render(
        self,
        ctx: RenderContext,
        label: str,
        value: MetricValue,
    ) -> Optional[RenderFragment]:
        """Render ``value`` for ``ctx.fmt``, or ``None`` to render nothing."""
        ...


class RenderRegistry:
    """Registration-based lookup of render plugins, keyed by name."""

    def __init__(self) -> None:
        self._renders: dict[str, RenderPlugin] = {}

    def register(self, render: RenderPlugin) -> None:
        self._renders[render.name] = render

    def get(self, name: str) -> Optional[RenderPlugin]:
        return self._renders.get(name)

    def all(self) -> list[RenderPlugin]:
        return list(self._renders.values())


class TextRowRender:
    """Render a metric as a ``label: value`` text row inside a node block."""

    name = "text_row"
    attaches_to = MetricTarget.NODE

    def render(
        self,
        ctx: RenderContext,
        label: str,
        value: MetricValue,
    ) -> Optional[RenderFragment]:
        return RenderFragment(text=f"{label}: {value}")


class EdgeLabelRender:
    """Render a metric as a ``label=value`` text label on a connection."""

    name = "edge_label"
    attaches_to = MetricTarget.LINK

    def render(
        self,
        ctx: RenderContext,
        label: str,
        value: MetricValue,
    ) -> Optional[RenderFragment]:
        return RenderFragment(text=f"{label}={value}")


#: Line width marking a too-far connection, in both formats.
_TOO_FAR_WIDTH: Final = 4


class BalanceMarkRender:
    """Render a balance verdict as a colored, named mark on a connection.

    The arrow itself carries the verdict -- a thicker line in its own color --
    because a colored word blends into a busy diagram. The legend explains it.

    Only ``too-far`` is drawn, so the diagram shows problems instead of
    restating a verdict on every arrow; ``balanced`` stays silent.

    A cycle's merged ``forward/backward`` value is labelled in **text** instead:
    both renderers hardcode the cycle's own arrow style and discard a metric's,
    so text is the only channel left there. A cycle silent in both directions
    stays silent, and none of them asks for details -- a cycle's own note already
    lists every edge in both directions.
    """

    name = "balance_mark"
    attaches_to = MetricTarget.LINK

    _COLORS: ClassVar[Mapping[str, str]] = {"too-far": "#D35400"}
    _SILENT: ClassVar[frozenset[str]] = frozenset({"balanced"})

    def render(
        self,
        ctx: RenderContext,
        label: str,
        value: MetricValue,
    ) -> Optional[RenderFragment]:
        verdict = str(value)
        if all(part in self._SILENT for part in verdict.split("/")):
            return None
        color = self._COLORS.get(verdict)
        if color is None:
            return RenderFragment(text=verdict)
        if ctx.fmt == "d2":
            style = f'style.stroke: "{color}"; style.stroke-width: {_TOO_FAR_WIDTH}'
        else:
            style = f"{color},thickness={_TOO_FAR_WIDTH}"
        return RenderFragment(style=style, detail=True)


def default_renders() -> RenderRegistry:
    """Build the registry of render plugins shipped by default.

    Register a new render plugin here (one line) or on a registry you build
    yourself to add a render type without changing the extractor/metric cores.
    """
    registry = RenderRegistry()
    registry.register(TextRowRender())
    registry.register(EdgeLabelRender())
    registry.register(BalanceMarkRender())
    return registry
