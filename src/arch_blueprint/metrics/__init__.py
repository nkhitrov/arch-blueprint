from arch_blueprint.metrics.base import Metric, MetricKey, MetricRegistry
from arch_blueprint.metrics.depth import DepthMetric
from arch_blueprint.metrics.display import MetricDisplay
from arch_blueprint.metrics.edge_weight import EdgeWeightMetric
from arch_blueprint.metrics.fan_in import FanInMetric
from arch_blueprint.metrics.fan_out import FanOutMetric
from arch_blueprint.metrics.instability import InstabilityMetric
from arch_blueprint.metrics.render import (
    MetricTarget,
    RenderContext,
    RenderFragment,
    RenderPlugin,
    RenderRegistry,
    default_renders,
)

# The color metric must always be present; it drives node fill color.
COLOR_METRIC = DepthMetric.name


def default_registry() -> MetricRegistry:
    """Build the registry of metrics shipped by default.

    Register a new metric here (one line) to make it available — no changes to
    the extractor or renderer cores are required.
    """
    registry = MetricRegistry()
    registry.register(DepthMetric())
    registry.register(FanInMetric())
    registry.register(FanOutMetric())
    registry.register(InstabilityMetric())
    registry.register(EdgeWeightMetric())
    return registry


__all__ = [
    "COLOR_METRIC",
    "Metric",
    "MetricDisplay",
    "MetricKey",
    "MetricRegistry",
    "MetricTarget",
    "RenderContext",
    "RenderFragment",
    "RenderPlugin",
    "RenderRegistry",
    "default_registry",
    "default_renders",
]
