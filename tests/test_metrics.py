from __future__ import annotations

from collections.abc import Mapping
from typing import Optional

import pytest

from arch_blueprint.domain.graph import BlueprintGraph, MetricValue
from arch_blueprint.metrics import (
    ALL_KINDS,
    MetricConfigError,
    MetricDisplay,
    MetricRegistry,
    RenderContext,
    RenderFragment,
    RenderPlan,
    build_render_plan,
    default_registry,
    default_renders,
)
from arch_blueprint.metrics.edge_weight import EdgeWeightMetric
from arch_blueprint.metrics.fan_in import FanInMetric
from arch_blueprint.metrics.fan_out import FanOutMetric
from arch_blueprint.metrics.instability import InstabilityMetric
from arch_blueprint.metrics.render import EdgeLabelRender, TextRowRender
from tests.conftest import make_edge, make_graph


def _sample_graph() -> BlueprintGraph:
    return make_graph(
        ["a.core", "b.util"],
        [make_edge("a.core", "b.util", "a", "b")],
    )


def _multi_edge_graph() -> BlueprintGraph:
    return make_graph(
        ["a.core", "a.api", "b.util"],
        [
            make_edge("a.core", "b.util", "a", "b"),
            make_edge("a.api", "b.util", "a", "b"),
        ],
    )


class _MisdirectedMetric:
    """A node metric pointing at a plugin that draws on links."""

    name = "misdirected"
    applies_to = ALL_KINDS
    render: Optional[str] = "edge_label"

    def compute(self, graph: BlueprintGraph) -> Mapping[str, MetricValue]:
        return {node.id: 1 for node in graph.nodes}


# --- computation ----------------------------------------------------------


def test_fan_in_and_fan_out() -> None:
    graph = _sample_graph()
    assert FanInMetric().compute(graph) == {"a.core": 0, "b.util": 1}
    assert FanOutMetric().compute(graph) == {"a.core": 1, "b.util": 0}


def test_instability() -> None:
    # a.core: out 1 / (0 + 1) = 1.0 ; b.util: out 0 / (1 + 0) = 0.0
    assert InstabilityMetric().compute(_sample_graph()) == {
        "a.core": 1.0,
        "b.util": 0.0,
    }


def test_edge_weight_computes_per_link() -> None:
    assert EdgeWeightMetric().compute(_multi_edge_graph()) == {("a", "b"): 2}


def test_compute_all_routes_by_target() -> None:
    graph = _multi_edge_graph()
    default_registry().compute_all(graph)
    assert graph.link_metrics[("a", "b")]["edge_weight"] == 2
    assert graph.node_metrics["b.util"]["fan_in"] == 2
    assert "edge_weight" not in graph.node_metrics["a.core"]
    assert graph.node_metrics["a.core"]["depth"] == 2
    assert graph.node_metrics["a.core"]["fan_out"] == 1


def test_compute_honours_the_requested_subset() -> None:
    graph = _multi_edge_graph()
    default_registry().compute(graph, ["depth"])
    assert graph.node_metrics["a.core"] == {"depth": 2}
    assert graph.link_metrics == {}


# --- render plugins -------------------------------------------------------


def test_edge_label_render() -> None:
    fragment = EdgeLabelRender().render(RenderContext(fmt="puml"), "edge_weight", 3)
    assert fragment == RenderFragment(text="edge_weight=3")


def test_text_row_render() -> None:
    fragment = TextRowRender().render(RenderContext(fmt="d2"), "fan_in", 2)
    assert fragment == RenderFragment(text="fan_in: 2")


def test_render_registry_lookup() -> None:
    renders = default_renders()
    edge_label = renders.get("edge_label")
    assert edge_label is not None
    assert edge_label.name == "edge_label"
    assert renders.get("missing") is None


# --- render plan ----------------------------------------------------------


def _plan(*shown: str) -> RenderPlan:
    return build_render_plan(
        default_registry(),
        default_renders(),
        MetricDisplay(shown=shown),
        fmt="puml",
    )


def test_plan_preserves_requested_order() -> None:
    """Blocks follow CLI order, not the order metrics were registered in."""
    plan = _plan("instability", "fan_in")
    assert [item.name for item in plan.node_items] == ["instability", "fan_in"]


def test_plan_splits_node_and_link_metrics() -> None:
    plan = _plan("fan_in", "edge_weight")
    assert [item.name for item in plan.node_items] == ["fan_in"]
    assert [item.name for item in plan.link_items] == ["edge_weight"]


def test_plan_always_requires_the_color_metric() -> None:
    assert _plan().required_metrics == {"depth"}
    assert _plan("fan_in").required_metrics == {"depth", "fan_in"}


def test_plan_rejects_unknown_metric() -> None:
    with pytest.raises(MetricConfigError, match="unknown metric 'fanin'"):
        _plan("fanin")


def test_plan_rejects_compute_only_metric() -> None:
    with pytest.raises(MetricConfigError, match="compute-only"):
        _plan("depth")


def test_plan_rejects_unknown_color_metric() -> None:
    with pytest.raises(MetricConfigError, match="color metric"):
        build_render_plan(
            default_registry(),
            default_renders(),
            MetricDisplay(),
            fmt="puml",
            color_metric="nope",
        )


def test_plan_rejects_plugin_attached_to_the_wrong_side() -> None:
    registry = MetricRegistry()
    registry.register_node(_MisdirectedMetric())
    with pytest.raises(MetricConfigError, match="attaches to link"):
        build_render_plan(
            registry,
            default_renders(),
            MetricDisplay(shown=("misdirected",)),
            fmt="puml",
            color_metric="misdirected",
        )
