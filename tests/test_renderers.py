from __future__ import annotations

import pytest

from arch_blueprint.analyze.cycles import CycleAnalyzer
from arch_blueprint.analyze.groups import GroupAnalyzer
from arch_blueprint.blueprint import ArchBlueprint
from arch_blueprint.domain.graph import BlueprintGraph, Cycle
from arch_blueprint.domain.node import Node
from arch_blueprint.metrics import (
    MetricDisplay,
    RenderPlan,
    build_render_plan,
    default_registry,
    default_renders,
)
from arch_blueprint.renderer.base import (
    BlueprintRenderer,
    CycleRender,
    LinkDecoration,
    RendererOptions,
)
from arch_blueprint.renderer.d2 import D2LangRenderer
from arch_blueprint.renderer.puml import PlantUmlRenderer
from tests.conftest import CYCLIC_PROJECT, make_edge, make_graph


def _plan(fmt: str, *shown: str) -> RenderPlan:
    registry = default_registry()
    return build_render_plan(
        registry,
        default_renders(),
        MetricDisplay(shown=shown),
        fmt=fmt,
    )


def _computed_graph() -> BlueprintGraph:
    """A two-node graph with metrics computed, but no analysis run yet."""
    graph = make_graph(
        ["a.core", "b.util"],
        [make_edge("a.core", "b.util", "a", "b")],
    )
    default_registry().compute_all(graph)
    return graph


def _cyclic_graph() -> BlueprintGraph:
    graph = make_graph(
        ["a.core", "b.util"],
        [
            make_edge("a.core", "b.util", "a", "b"),
            make_edge("b.util", "a.core", "b", "a"),
        ],
    )
    default_registry().compute_all(graph)
    return graph


class _CapturingRenderer(BlueprintRenderer):
    """Records the graph it was handed instead of drawing it."""

    fmt = "puml"

    def render(self, graph: BlueprintGraph) -> str:
        self.captured = graph
        return ""

    def _format_node(self, node: Node, color: str, blocks: list[str]) -> str:
        return ""

    def _format_link(
        self,
        source: str,
        target: str,
        decoration: LinkDecoration,
    ) -> str:
        return ""

    def _format_cycle(self, cycle: Cycle, decoration: LinkDecoration) -> CycleRender:
        return CycleRender(inline="")

    def _combine_output(
        self,
        nodes: list[str],
        links: list[str],
        deferred: list[str],
    ) -> str:
        return ""


class _NoFormatRenderer(_CapturingRenderer):
    fmt = ""


# --- options --------------------------------------------------------------


def test_get_color_cycles_through_palette() -> None:
    options = RendererOptions(depth_colors=["#000", "#111", "#222"])
    assert options.get_color_for_depth(0) == "#000"
    assert options.get_color_for_depth(3) == "#000"
    assert options.get_color_for_depth(4) == "#111"


def test_empty_depth_colors_rejected() -> None:
    with pytest.raises(ValueError, match="depth_colors"):
        RendererOptions(depth_colors=[])


# --- renderer construction ------------------------------------------------


def test_renderer_rejects_a_plan_for_another_format() -> None:
    with pytest.raises(ValueError, match="built for 'd2'"):
        PlantUmlRenderer(plan=_plan("d2"))


def test_renderer_without_a_format_is_rejected() -> None:
    with pytest.raises(TypeError, match="non-empty 'fmt'"):
        _NoFormatRenderer(plan=_plan("puml"))


# --- nodes and links ------------------------------------------------------


def test_puml_renders_metric_blocks_in_requested_order() -> None:
    output = PlantUmlRenderer(plan=_plan("puml", "instability", "fan_in")).render(
        _computed_graph(),
    )
    assert "class a.core <<(M, #2ECC71)>> {" in output
    assert output.index("instability:") < output.index("fan_in:")


def test_d2_renders_metric_blocks() -> None:
    output = D2LangRenderer(plan=_plan("d2", "fan_in")).render(_computed_graph())
    assert "a.core: {" in output
    assert "  fan_in: 0" in output


def test_link_metric_labels_the_connection() -> None:
    output = PlantUmlRenderer(plan=_plan("puml", "edge_weight")).render(
        _computed_graph(),
    )
    assert "a ---> b : edge_weight=1" in output


def test_no_metrics_requested_means_bare_nodes() -> None:
    output = PlantUmlRenderer(plan=_plan("puml")).render(_computed_graph())
    assert "class a.core <<(M, #2ECC71)>>\n" in output
    assert "fan_in" not in output


# --- cycles ---------------------------------------------------------------


def test_renderer_draws_only_the_cycles_the_analyzer_found() -> None:
    """A hand-built graph has no cycles until the analyze step fills them in.

    Rendering one without that step yields two plain arrows — which is correct,
    and is why a cycle test must populate graph.cycles explicitly.
    """
    graph = _cyclic_graph()
    plain = PlantUmlRenderer(plan=_plan("puml")).render(graph)
    assert "<-[" not in plain
    assert plain.count("--->") == 2

    graph.cycles = CycleAnalyzer.detect_cycles(graph.links)
    analysed = PlantUmlRenderer(plan=_plan("puml")).render(graph)
    assert "a <-[#C0392B,bold]-> b" in analysed


def test_pipeline_fills_in_the_cycles() -> None:
    renderer = _CapturingRenderer(plan=_plan("puml"))
    ArchBlueprint(
        project_dir=str(CYCLIC_PROJECT),
        target_names=["pkg_a.*", "pkg_b.*"],
        renderer=renderer,
    ).run()
    assert len(renderer.captured.cycles) == 1


def test_cycle_label_carries_both_directions() -> None:
    """A cycle is one connection standing for two links, so it has two values."""
    graph = make_graph(
        ["a.core", "a.api", "b.util"],
        [
            make_edge("a.core", "b.util", "a", "b"),
            make_edge("a.api", "b.util", "a", "b"),
            make_edge("b.util", "a.core", "b", "a"),
        ],
    )
    default_registry().compute_all(graph)
    graph.cycles = CycleAnalyzer.detect_cycles(graph.links)
    output = PlantUmlRenderer(plan=_plan("puml", "edge_weight")).render(graph)
    assert "a <-[#C0392B,bold]-> b : edge_weight=2/1" in output


def test_d2_defers_cycle_details_to_a_separate_block() -> None:
    graph = _cyclic_graph()
    graph.cycles = CycleAnalyzer.detect_cycles(graph.links)
    options = RendererOptions(depth_colors=["#000"], show_cycle_details=True)
    output = D2LangRenderer(plan=_plan("d2"), options=options).render(graph)
    assert "a <-> b: CYCLE" in output
    assert '"Cycle Details"' in output


def test_puml_wraps_grouped_nodes_in_a_package() -> None:
    graph = _computed_graph()
    graph.groups = GroupAnalyzer.build(graph)
    output = PlantUmlRenderer(plan=_plan("puml")).render(graph)
    assert "package a <<(P, #95A5A6)>> {\n  class a.core" in output


def test_d2_leaves_grouping_to_its_own_nesting() -> None:
    """D2 nests by dotted name already: ``a.core`` lands in container ``a``."""
    graph = _computed_graph()
    graph.groups = GroupAnalyzer.build(graph)
    output = D2LangRenderer(plan=_plan("d2")).render(graph)
    assert "package" not in output
    assert output.startswith("direction: right\na.core: {")


def test_pipeline_fills_in_the_groups() -> None:
    renderer = _CapturingRenderer(plan=_plan("puml"))
    ArchBlueprint(
        project_dir=str(CYCLIC_PROJECT),
        target_names=["pkg_a.*", "pkg_b.*"],
        renderer=renderer,
    ).run()
    assert {group.namespace for group in renderer.captured.groups} == {"pkg_a", "pkg_b"}
