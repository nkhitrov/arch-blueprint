from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Protocol, runtime_checkable

from arch_blueprint.domain.graph import MetricValue


class MetricTarget(Enum):
    """What a metric is computed and rendered on."""

    NODE = "node"
    LINK = "link"


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
    """

    text: str = ""
    style: str = ""


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


def default_renders() -> RenderRegistry:
    """Build the registry of render plugins shipped by default.

    Register a new render plugin here (one line) or on a registry you build
    yourself to add a render type without changing the extractor/metric cores.
    """
    registry = RenderRegistry()
    registry.register(TextRowRender())
    registry.register(EdgeLabelRender())
    return registry
