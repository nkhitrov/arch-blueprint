from __future__ import annotations

from collections.abc import Mapping
from typing import Optional

import pytest

from arch_blueprint.domain.graph import BlueprintGraph, MetricValue
from arch_blueprint.metrics import (
    ALL_KINDS,
    NO_OPTIONS,
    MetricConfigError,
    MetricDisplay,
    MetricOption,
    MetricOptions,
    MetricRegistry,
    RenderContext,
    RenderFragment,
    RenderPlan,
    build_render_plan,
    default_registry,
    default_renders,
)
from arch_blueprint.metrics.balance import BalanceMetric
from arch_blueprint.metrics.edge_weight import EdgeWeightMetric
from arch_blueprint.metrics.fan_in import FanInMetric
from arch_blueprint.metrics.fan_out import FanOutMetric
from arch_blueprint.metrics.instability import InstabilityMetric
from arch_blueprint.metrics.namespace_distance import NamespaceDistanceMetric
from arch_blueprint.metrics.render import (
    BalanceMarkRender,
    EdgeLabelRender,
    TextRowRender,
)
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
    title = "misdirected"
    description = "a node metric wired to a link plugin"
    applies_to = ALL_KINDS
    render: Optional[str] = "edge_label"
    options: tuple[MetricOption, ...] = ()

    def compute(
        self,
        graph: BlueprintGraph,
        options: MetricOptions = NO_OPTIONS,
    ) -> Mapping[str, MetricValue]:
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


def test_namespace_distance_is_tree_distance_not_the_namespace_pair() -> None:
    """The distance of a link is measured between modules, not its namespaces.

    A namespace pair always shares every component but the last, so measuring it
    would return a constant 2 for every link in every project.
    """
    graph = make_graph(
        ["a.core", "a.deep.inner.mod", "b.util"],
        [
            make_edge("a.core", "b.util", "a", "b"),
            make_edge("a.deep.inner.mod", "b.util", "a", "b"),
        ],
    )
    assert NamespaceDistanceMetric().compute(graph) == {("a", "b"): 6}


def test_namespace_distance_is_smaller_when_endpoints_share_a_prefix() -> None:
    siblings = make_graph(
        ["pkg.sub.a", "pkg.sub.b"],
        [make_edge("pkg.sub.a", "pkg.sub.b", "pkg.sub.a", "pkg.sub.b")],
    )
    strangers = make_graph(
        ["pkg.sub.a", "other.b"],
        [make_edge("pkg.sub.a", "other.b", "pkg", "other")],
    )
    assert NamespaceDistanceMetric().compute(siblings) == {
        ("pkg.sub.a", "pkg.sub.b"): 2,
    }
    assert NamespaceDistanceMetric().compute(strangers) == {("pkg", "other"): 5}


def _spread_graph() -> BlueprintGraph:
    """Four links spanning both dimensions, so a threshold can be seen working.

    ``a -> b``: 9 imports, distance 9.  ``c -> d``: 9 imports, distance 4.
    ``e -> f``: 1 import, distance 8.   ``g -> h``: 1 import, distance 4.
    """
    edges = [
        make_edge("a.p.q.r.s", "b.t.u.v", "a", "b"),
        *[make_edge(f"a.m{n}", "b.n", "a", "b") for n in range(8)],
        *[make_edge(f"c.m{n}", "d.n", "c", "d") for n in range(9)],
        make_edge("e.p.q.r", "f.t.u.v", "e", "f"),
        make_edge("g.m0", "h.n", "g", "h"),
    ]
    node_ids = {edge.source for edge in edges} | {edge.target for edge in edges}
    return make_graph(sorted(node_ids), edges)


def test_balance_says_nothing_until_a_threshold_is_given() -> None:
    """No threshold, no verdict: every automatic one is wrong on some graph.

    Import counts are close to degenerate in real projects -- 22 of wemake's 29
    links carry exactly one import -- so any rank-based cut lands on the floor
    and "above the threshold" comes to mean "more than one import".
    """
    assert BalanceMetric().compute(_spread_graph(), {}) == {}


def test_balance_flags_a_link_clearing_every_threshold_given() -> None:
    verdicts = BalanceMetric().compute(
        _spread_graph(),
        {"strength": 9, "distance": 8},
    )
    assert verdicts[("a", "b")] == "too-far"
    assert verdicts[("c", "d")] == "balanced"
    assert verdicts[("e", "f")] == "balanced"
    assert verdicts[("g", "h")] == "balanced"


def test_a_threshold_left_out_does_not_constrain() -> None:
    """One knob set is a filter on that dimension alone."""
    by_strength = BalanceMetric().compute(_spread_graph(), {"strength": 9})
    assert by_strength[("a", "b")] == "too-far"
    assert by_strength[("c", "d")] == "too-far"
    assert by_strength[("e", "f")] == "balanced"

    by_distance = BalanceMetric().compute(_spread_graph(), {"distance": 8})
    assert by_distance[("a", "b")] == "too-far"
    assert by_distance[("c", "d")] == "balanced"
    assert by_distance[("e", "f")] == "too-far"


def test_a_threshold_includes_the_value_it_names() -> None:
    """``strength=9`` reads as "at least nine imports", not "more than nine"."""
    verdicts = BalanceMetric().compute(_spread_graph(), {"strength": 9})
    assert verdicts[("c", "d")] == "too-far"
    assert BalanceMetric().compute(_spread_graph(), {"strength": 10})[("c", "d")] == (
        "balanced"
    )


def test_balance_declares_the_two_knobs_it_takes() -> None:
    assert [option.name for option in BalanceMetric().options] == [
        "strength",
        "distance",
    ]


def test_compute_all_routes_by_target() -> None:
    graph = _multi_edge_graph()
    default_registry().compute_all(graph)
    assert graph.link_metrics[("a", "b")]["edge_weight"] == 2
    assert graph.node_metrics["b.util"]["fan_in"] == 2
    assert "edge_weight" not in graph.node_metrics["a.core"]
    assert graph.node_metrics["a.core"]["depth"] == 2
    assert graph.node_metrics["a.core"]["fan_out"] == 1


def test_balance_and_distance_are_registered_as_link_metrics() -> None:
    graph = _spread_graph()
    registry = default_registry()
    registry.compute(
        graph,
        ["balance", "namespace_distance"],
        {"balance": {"strength": 9, "distance": 8}},
    )
    assert graph.link_metrics[("a", "b")] == {
        "balance": "too-far",
        "namespace_distance": 9,
    }
    assert "balance" not in graph.node_metrics.get("a.m0", {})


def test_a_metrics_options_reach_it_and_nobody_else() -> None:
    """Handing every metric the whole bag would let one metric's typo hit another."""
    graph = _spread_graph()
    registry = default_registry()
    registry.compute(graph, ["balance", "edge_weight"], {"balance": {"strength": 9}})
    assert graph.link_metrics[("a", "b")]["balance"] == "too-far"
    assert graph.link_metrics[("a", "b")]["edge_weight"] == 9


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


def test_balance_mark_thickens_a_too_far_arrow_instead_of_labelling_it() -> None:
    """The arrow carries the verdict; a colored word blends into the diagram."""
    fragment = BalanceMarkRender().render(
        RenderContext(fmt="puml"),
        "balance",
        "too-far",
    )
    assert fragment is not None
    assert fragment.text == ""
    assert fragment.style == "#D35400,thickness=4"


def test_balance_mark_draws_only_the_too_far_verdict() -> None:
    """Only the actionable diagnosis earns ink; everything else stays plain."""
    fragment = BalanceMarkRender().render(
        RenderContext(fmt="puml"),
        "balance",
        "balanced",
    )
    assert fragment is None


def test_balance_mark_uses_d2_style_prefixed_keys() -> None:
    """D2 needs the ``style.`` prefix, as the cycle connection template does."""
    fragment = BalanceMarkRender().render(RenderContext(fmt="d2"), "balance", "too-far")
    assert fragment is not None
    assert fragment.style == 'style.stroke: "#D35400"; style.stroke-width: 4'


def test_balance_mark_stays_silent_on_a_cycle_that_is_balanced_both_ways() -> None:
    fragment = BalanceMarkRender().render(
        RenderContext(fmt="puml"),
        "balance",
        "balanced/balanced",
    )
    assert fragment is None


def test_balance_mark_asks_for_the_imports_behind_a_too_far_link() -> None:
    """A thick arrow says *that* a boundary is hot, never *what* crosses it.

    The plugin only raises the request; which edges get listed, and in what
    markup, stays with the renderer — it never learns which metric asked.
    """
    fragment = BalanceMarkRender().render(
        RenderContext(fmt="puml"),
        "balance",
        "too-far",
    )
    assert fragment is not None
    assert fragment.detail is True


def test_balance_mark_leaves_a_cycles_details_to_the_cycle() -> None:
    """A cycle already prints both directions' edges; asking again would double them."""
    fragment = BalanceMarkRender().render(
        RenderContext(fmt="puml"),
        "balance",
        "too-far/balanced",
    )
    assert fragment is not None
    assert fragment.detail is False


def test_balance_mark_labels_a_cycles_merged_value_without_styling_it() -> None:
    """A cycle carries two verdicts as ``forward/backward``; neither color wins."""
    fragment = BalanceMarkRender().render(
        RenderContext(fmt="puml"),
        "balance",
        "too-far/balanced",
    )
    assert fragment is not None
    assert fragment.text == "too-far/balanced"
    assert fragment.style == ""


# --- metric options -------------------------------------------------------


def _plan_with(*options: str) -> RenderPlan:
    return build_render_plan(
        default_registry(),
        default_renders(),
        MetricDisplay(shown=("balance",)),
        fmt="puml",
        options=options,
    )


def test_an_option_reaches_the_plan_as_a_number() -> None:
    plan = _plan_with("balance.strength=20", "balance.distance=5")
    assert plan.metric_options == {"balance": {"strength": 20.0, "distance": 5.0}}


def test_a_metric_with_no_option_given_gets_none() -> None:
    assert _plan_with().metric_options == {}


@pytest.mark.parametrize(
    ("option", "message"),
    [
        ("balance.strength", "expected METRIC.OPTION=VALUE"),
        ("balance.strength=lots", "not a number"),
        ("nosuch.strength=1", "unknown metric 'nosuch'"),
        ("balance.nosuch=1", "unknown option 'nosuch'"),
        ("fan_in.strength=1", "takes no options"),
    ],
)
def test_a_bad_option_is_rejected_with_its_reason(option: str, message: str) -> None:
    """Five distinct ways to get it wrong, five distinct things to say about it.

    A typo that silently never applies is worse than a refusal: the diagram
    still renders, and it renders the answer to a question nobody asked.
    """
    with pytest.raises(MetricConfigError, match=message):
        _plan_with(option)


def test_an_option_for_a_metric_that_is_not_shown_is_rejected() -> None:
    """It would otherwise be a no-op the user has no way to notice."""
    with pytest.raises(MetricConfigError, match="is not being computed"):
        build_render_plan(
            default_registry(),
            default_renders(),
            MetricDisplay(shown=("edge_weight",)),
            fmt="puml",
            options=("balance.strength=20",),
        )


# --- render plan ----------------------------------------------------------


def test_render_plan_carries_each_metrics_display_texts() -> None:
    """A metric brings its own wording, so the renderer hardcodes none of it."""
    plan = build_render_plan(
        registry=default_registry(),
        renders=default_renders(),
        display=MetricDisplay(shown=("edge_weight",)),
        fmt="puml",
    )
    item = plan.link_items[0]
    assert item.name == "edge_weight"
    assert item.title == "imports"
    assert "import" in item.description


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
