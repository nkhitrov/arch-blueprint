from arch_blueprint.metrics.balance import BalanceMetric
from arch_blueprint.metrics.base import (
    ALL_KINDS,
    NO_OPTIONS,
    AllMetricOptions,
    LinkMetric,
    Metric,
    MetricOption,
    MetricOptions,
    MetricRegistry,
    MetricTarget,
    NodeMetric,
)
from arch_blueprint.metrics.depth import DepthMetric
from arch_blueprint.metrics.display import MetricDisplay
from arch_blueprint.metrics.edge_weight import EdgeWeightMetric
from arch_blueprint.metrics.fan_in import FanInMetric
from arch_blueprint.metrics.fan_out import FanOutMetric
from arch_blueprint.metrics.instability import InstabilityMetric
from arch_blueprint.metrics.namespace_distance import NamespaceDistanceMetric
from arch_blueprint.metrics.plan import (
    DEFAULT_COLOR_METRIC,
    MetricConfigError,
    PlannedMetric,
    RenderPlan,
    build_render_plan,
)
from arch_blueprint.metrics.render import (
    RenderContext,
    RenderFragment,
    RenderPlugin,
    RenderRegistry,
    default_renders,
)

#: The metric driving node fill color; always computed, never displayed.
COLOR_METRIC = DEFAULT_COLOR_METRIC


def default_registry() -> MetricRegistry:
    """Build the registry of metrics shipped by default.

    Register a new metric here (one line) to make it available — no changes to
    the extractor or renderer cores are required. Which of the two register
    methods you call is what makes it a node or a link metric.
    """
    registry = MetricRegistry()
    registry.register_node(DepthMetric())
    registry.register_node(FanInMetric())
    registry.register_node(FanOutMetric())
    registry.register_node(InstabilityMetric())
    registry.register_link(EdgeWeightMetric())
    registry.register_link(NamespaceDistanceMetric())
    registry.register_link(BalanceMetric())
    return registry


__all__ = [
    "ALL_KINDS",
    "COLOR_METRIC",
    "DEFAULT_COLOR_METRIC",
    "NO_OPTIONS",
    "AllMetricOptions",
    "LinkMetric",
    "Metric",
    "MetricConfigError",
    "MetricDisplay",
    "MetricOption",
    "MetricOptions",
    "MetricRegistry",
    "MetricTarget",
    "NodeMetric",
    "PlannedMetric",
    "RenderContext",
    "RenderFragment",
    "RenderPlan",
    "RenderPlugin",
    "RenderRegistry",
    "build_render_plan",
    "default_registry",
    "default_renders",
]
