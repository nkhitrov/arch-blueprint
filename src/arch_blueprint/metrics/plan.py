from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from arch_blueprint.domain.node import NodeKind
from arch_blueprint.metrics.base import MetricRegistry, MetricTarget
from arch_blueprint.metrics.depth import DepthMetric
from arch_blueprint.metrics.display import MetricDisplay
from arch_blueprint.metrics.render import RenderPlugin, RenderRegistry

#: The metric driving node fill color. It must always be computed.
DEFAULT_COLOR_METRIC: Final = DepthMetric.name


class MetricConfigError(ValueError):
    """A requested metric cannot be displayed, with the reason why."""


@dataclass(frozen=True)
class PlannedMetric:
    """One metric resolved to the plugin that will draw it."""

    name: str
    plugin: RenderPlugin
    applies_to: frozenset[NodeKind]


@dataclass(frozen=True)
class RenderPlan:
    """Everything a renderer needs to know about metrics, resolved up front.

    Resolution happens once instead of per node, and every way the request can be
    wrong is rejected here rather than silently skipped at draw time.
    """

    fmt: str
    color_metric: str
    required_metrics: frozenset[str]
    node_items: tuple[PlannedMetric, ...] = ()
    link_items: tuple[PlannedMetric, ...] = ()


def build_render_plan(
    registry: MetricRegistry,
    renders: RenderRegistry,
    display: MetricDisplay,
    fmt: str,
    color_metric: str = DEFAULT_COLOR_METRIC,
) -> RenderPlan:
    """Resolve requested metric names into drawable items, or explain the failure.

    ``display.shown`` order is preserved: metric blocks appear in the order the
    caller asked for them, not in registration order.
    """
    if registry.node_metric(color_metric) is None:
        raise MetricConfigError(
            f"color metric '{color_metric}' is not a registered node metric",
        )

    node_items: list[PlannedMetric] = []
    link_items: list[PlannedMetric] = []
    for name in display.shown:
        node_metric = registry.node_metric(name)
        link_metric = registry.link_metric(name)
        if node_metric is not None:
            plugin = _resolve_plugin(
                renders,
                name,
                node_metric.render,
                MetricTarget.NODE,
            )
            node_items.append(
                PlannedMetric(
                    name=name,
                    plugin=plugin,
                    applies_to=node_metric.applies_to,
                ),
            )
        elif link_metric is not None:
            plugin = _resolve_plugin(
                renders,
                name,
                link_metric.render,
                MetricTarget.LINK,
            )
            link_items.append(
                PlannedMetric(name=name, plugin=plugin, applies_to=frozenset()),
            )
        else:
            known = ", ".join(sorted(registry.names()))
            raise MetricConfigError(f"unknown metric '{name}'. Available: {known}")

    return RenderPlan(
        fmt=fmt,
        color_metric=color_metric,
        required_metrics=frozenset({color_metric, *display.shown}),
        node_items=tuple(node_items),
        link_items=tuple(link_items),
    )


def _resolve_plugin(
    renders: RenderRegistry,
    metric_name: str,
    render_name: str | None,
    target: MetricTarget,
) -> RenderPlugin:
    if render_name is None:
        raise MetricConfigError(
            f"metric '{metric_name}' is compute-only and cannot be displayed",
        )
    plugin = renders.get(render_name)
    if plugin is None:
        known = ", ".join(sorted(r.name for r in renders.all()))
        raise MetricConfigError(
            f"metric '{metric_name}' names unknown render plugin "
            f"'{render_name}'. Available: {known}",
        )
    if plugin.attaches_to is not target:
        raise MetricConfigError(
            f"metric '{metric_name}' is a {target.value} metric but render plugin "
            f"'{render_name}' attaches to {plugin.attaches_to.value}",
        )
    return plugin
