from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Final

from arch_blueprint.domain.node import NodeKind
from arch_blueprint.metrics.base import (
    AllMetricOptions,
    MetricOption,
    MetricRegistry,
    MetricTarget,
)
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
    title: str
    description: str
    plugin: RenderPlugin
    applies_to: frozenset[NodeKind]
    #: What the metric declares it can be tuned with, carried so the legend can
    #: name the knobs without the renderer reaching back into the registry.
    options: tuple[MetricOption, ...] = ()


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
    #: Resolved per-metric options. Read twice: the pipeline computes with them,
    #: the legend reports them, and neither re-parses the caller's strings.
    metric_options: AllMetricOptions = field(default_factory=dict)


def build_render_plan(
    registry: MetricRegistry,
    renders: RenderRegistry,
    display: MetricDisplay,
    fmt: str,
    color_metric: str = DEFAULT_COLOR_METRIC,
    options: Iterable[str] = (),
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
                    title=node_metric.title,
                    description=node_metric.description,
                    plugin=plugin,
                    applies_to=node_metric.applies_to,
                    options=node_metric.options,
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
                PlannedMetric(
                    name=name,
                    title=link_metric.title,
                    description=link_metric.description,
                    plugin=plugin,
                    applies_to=frozenset(),
                    options=link_metric.options,
                ),
            )
        else:
            known = ", ".join(sorted(registry.names()))
            raise MetricConfigError(f"unknown metric '{name}'. Available: {known}")

    required = frozenset({color_metric, *display.shown})
    return RenderPlan(
        fmt=fmt,
        color_metric=color_metric,
        required_metrics=required,
        node_items=tuple(node_items),
        link_items=tuple(link_items),
        metric_options=_resolve_options(registry, options, required),
    )


def _resolve_options(
    registry: MetricRegistry,
    given: Iterable[str],
    required: frozenset[str],
) -> AllMetricOptions:
    """Parse ``METRIC.OPTION=VALUE`` strings, or explain which one is wrong.

    Rejected rather than skipped, and for the same reason an unknown ``--metric``
    is: a typo that silently never applies still renders a diagram, and renders
    the answer to a question nobody asked.
    """
    resolved: dict[str, dict[str, float]] = {}
    for item in given:
        metric, option, value = _split_option(item)
        declared = {declaration.name for declaration in registry.options_of(metric)}
        if metric not in registry.names():
            known = ", ".join(sorted(registry.names()))
            raise MetricConfigError(
                f"unknown metric '{metric}' in option '{item}'. Available: {known}",
            )
        if not declared:
            raise MetricConfigError(f"metric '{metric}' takes no options")
        if option not in declared:
            raise MetricConfigError(
                f"unknown option '{option}' for metric '{metric}'. "
                f"Available: {', '.join(sorted(declared))}",
            )
        if metric not in required:
            raise MetricConfigError(
                f"option '{item}' is set but metric '{metric}' is not being "
                f"computed. Add --metric {metric}",
            )
        resolved.setdefault(metric, {})[option] = value
    return resolved


def _split_option(item: str) -> tuple[str, str, float]:
    """Split one ``METRIC.OPTION=VALUE`` string into its three parts."""
    key, separator, raw = item.partition("=")
    metric, dot, option = key.partition(".")
    if not separator or not dot or not metric or not option:
        raise MetricConfigError(
            f"could not read option '{item}': expected METRIC.OPTION=VALUE",
        )
    try:
        return metric, option, float(raw)
    except ValueError:
        raise MetricConfigError(
            f"value '{raw}' of option '{item}' is not a number",
        ) from None


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
