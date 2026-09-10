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
    LinkDecoration,
    RenderedLink,
    RendererOptions,
    RenderSections,
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

    def _format_cycle(self, cycle: Cycle, decoration: LinkDecoration) -> RenderedLink:
        return RenderedLink(inline="")

    def _combine_output(self, sections: RenderSections) -> str:
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
    assert output.index("instability:") < output.index("fan-in:")


def test_d2_renders_metric_blocks() -> None:
    output = D2LangRenderer(plan=_plan("d2", "fan_in")).render(_computed_graph())
    assert "a.core: {" in output
    assert "  fan-in: 0" in output


def test_link_metric_labels_the_connection() -> None:
    output = PlantUmlRenderer(plan=_plan("puml", "edge_weight")).render(
        _computed_graph(),
    )
    assert "a ---> b : imports=1" in output


def test_puml_stacks_link_labels_one_per_line() -> None:
    """One label per line: a single long line stretches the whole diagram."""
    output = PlantUmlRenderer(
        plan=_plan("puml", "edge_weight", "namespace_distance"),
    ).render(_computed_graph())
    assert "a ---> b : imports=1\\ndistance=4" in output


def test_d2_stacks_link_labels_and_quotes_the_break() -> None:
    """A raw newline would end the D2 statement, so the label must be quoted."""
    output = D2LangRenderer(
        plan=_plan("d2", "edge_weight", "namespace_distance"),
    ).render(_computed_graph())
    assert 'a -> b: "imports=1\\ndistance=4"' in output


def test_d2_stacks_a_cycles_labels_under_the_cycle_marker() -> None:
    graph = _cyclic_graph()
    graph.cycles = CycleAnalyzer.detect_cycles(graph.links)
    output = D2LangRenderer(plan=_plan("d2", "edge_weight")).render(graph)
    assert 'a <-> b: "CYCLE\\nimports=1/1"' in output


def test_the_legend_names_every_option_a_shown_metric_takes() -> None:
    """The knobs have to be discoverable from the picture, not only from --help.

    Unset ones carry their description: that row is the whole path from "why is
    nothing coloured" to a second run that colours the right thing.
    """
    output = PlantUmlRenderer(plan=_plan("puml", "balance")).render(_computed_graph())
    assert "  options" in output
    assert (
        "  balance.strength = not set "
        "(imports a link must carry to count as strong)" in output
    )


def test_a_set_option_is_reported_as_the_number_in_force() -> None:
    plan = build_render_plan(
        default_registry(),
        default_renders(),
        MetricDisplay(shown=("balance",)),
        fmt="puml",
        options=("balance.strength=20",),
    )
    output = PlantUmlRenderer(plan=plan).render(_computed_graph())
    assert "  balance.strength = 20" in output
    assert "not set (imports" not in output


def test_the_legend_lists_the_values_that_landed_on_the_diagram() -> None:
    """A threshold is picked from the data, so the data has to be on the page."""
    graph = make_graph(
        ["a.one", "a.two", "b.n", "c.n"],
        [
            make_edge("a.one", "b.n", "a", "b"),
            make_edge("a.two", "b.n", "a", "b"),
            make_edge("a.one", "c.n", "a", "c"),
        ],
    )
    default_registry().compute_all(graph)
    output = PlantUmlRenderer(plan=_plan("puml", "edge_weight")).render(graph)
    assert "  values on this diagram" in output
    assert "  imports: 1, 2" in output


def test_repeated_values_are_counted_rather_than_repeated() -> None:
    output = PlantUmlRenderer(plan=_plan("puml", "fan_in")).render(_computed_graph())
    assert "  fan-in: 0, 1" in output


def test_a_metric_with_nothing_to_say_gets_no_row() -> None:
    """``balance`` with no threshold set computes nothing; an empty row is noise."""
    output = PlantUmlRenderer(plan=_plan("puml", "balance")).render(_computed_graph())
    assert "balance:" not in output


def test_a_long_tail_of_values_is_elided_out_loud() -> None:
    """Elided, never silently truncated -- the row says how many it left out."""
    edges = [
        make_edge(f"s{depended}_{n}.m", f"t{depended}.n", f"s{depended}_{n}", "t")
        for depended in range(1, 16)
        for n in range(depended)
    ]
    node_ids = {edge.source for edge in edges} | {edge.target for edge in edges}
    graph = make_graph(sorted(node_ids), edges)
    default_registry().compute_all(graph)
    output = PlantUmlRenderer(plan=_plan("puml", "fan_in")).render(graph)
    assert "more" in output
    assert "\u2026" in output


def test_puml_explains_every_shown_metric_in_a_legend() -> None:
    """The picture has to stand on its own for someone who never read the docs."""
    output = PlantUmlRenderer(plan=_plan("puml", "edge_weight")).render(
        _computed_graph(),
    )
    assert "legend right" in output
    assert "  imports \u2014 how many imports cross this boundary" in output
    assert "  a/b on a cycle" in output
    assert output.index("endlegend") < output.index("@enduml")


def test_no_metrics_requested_means_no_legend() -> None:
    """Nothing shown, nothing to explain."""
    output = PlantUmlRenderer(plan=_plan("puml")).render(_computed_graph())
    assert "legend" not in output


def test_d2_appends_the_legend_after_the_diagram() -> None:
    """Prepending it would displace the node section D2 nesting relies on."""
    output = D2LangRenderer(plan=_plan("d2", "edge_weight")).render(_computed_graph())
    assert output.startswith("direction: right")
    assert output.index("how many imports cross") > output.index("a -> b")


def test_no_metrics_requested_means_bare_nodes() -> None:
    output = PlantUmlRenderer(plan=_plan("puml")).render(_computed_graph())
    assert "class a.core <<(M, #2ECC71)>>\n" in output
    assert "fan_in" not in output


# --- link details ---------------------------------------------------------


def _flagged_graph() -> BlueprintGraph:
    """Two links, one of which a metric has flagged as worth spelling out.

    The verdict is written straight into ``link_metrics`` rather than computed:
    what the renderer does with a flag must not depend on which metric raised it.
    """
    graph = make_graph(
        ["a.core", "a.views", "b.util", "c.text"],
        [
            make_edge("a.views", "b.util", "a", "b"),
            make_edge("a.core", "b.util", "a", "b"),
            make_edge("a.core", "c.text", "a", "c"),
        ],
    )
    default_registry().compute_all(graph)
    graph.link_metrics[("a", "b")]["balance"] = "too-far"
    graph.link_metrics[("a", "c")]["balance"] = "balanced"
    return graph


def _details_options(*, show: bool = True) -> RendererOptions:
    return RendererOptions(depth_colors=["#2ECC71"], show_link_details=show)


def test_puml_lists_the_imports_behind_a_flagged_link() -> None:
    """A thick arrow says a boundary is hot; the note says what crosses it.

    Both edges land on ``b.util``, so the header names it once and the lines
    carry only the importers.
    """
    output = PlantUmlRenderer(
        plan=_plan("puml", "balance"),
        options=_details_options(),
    ).render(_flagged_graph())
    assert (
        "a -[#D35400,thickness=4]-> b\n"
        "note on link\n"
        "  **a -> b.util:**\n"
        "  - core\n"
        "  - views\n"
        "end note"
    ) in output


def _note_body(output: str) -> list[str]:
    lines = output.splitlines()
    start = lines.index("note on link")
    return lines[start + 1 : lines.index("end note", start)]


def _rendered_note(*edges: tuple[str, str]) -> list[str]:
    """Render one flagged link built from ``(source, target)`` module pairs."""
    node_ids = sorted({end for edge in edges for end in edge})
    graph = make_graph(
        node_ids,
        [
            make_edge(source, target, source.split(".")[0], target.split(".")[0])
            for source, target in edges
        ],
    )
    default_registry().compute_all(graph)
    graph.link_metrics[("a", "b")]["balance"] = "too-far"
    output = PlantUmlRenderer(
        plan=_plan("puml", "balance"),
        options=_details_options(),
    ).render(graph)
    return _note_body(output)


def test_one_importer_is_named_in_the_header_not_on_every_line() -> None:
    """Repeating it is half the width of a real note: wemake's runs 41 lines."""
    assert _rendered_note(
        ("a.views", "b.one"),
        ("a.views", "b.two"),
    ) == ["  **a.views -> b:**", "  - one", "  - two"]


def test_one_imported_module_collapses_the_same_way() -> None:
    """The rule is about a constant end, not about which end it is."""
    assert _rendered_note(
        ("a.one", "b.util"),
        ("a.two", "b.util"),
    ) == ["  **a -> b.util:**", "  - one", "  - two"]


def test_both_ends_stay_on_the_line_when_neither_is_constant() -> None:
    """Nothing to hoist: dropping either end would lose which import is which."""
    assert _rendered_note(
        ("a.one", "b.first"),
        ("a.two", "b.second"),
    ) == [
        "  **a -> b:**",
        "  - one \u2192 first",
        "  - two \u2192 second",
    ]


def test_an_unflagged_link_gets_no_note() -> None:
    """Otherwise every arrow grows a note and the diagram is unreadable."""
    output = PlantUmlRenderer(
        plan=_plan("puml", "balance"),
        options=_details_options(),
    ).render(_flagged_graph())
    assert "a ---> c\nnote on link" not in output
    assert output.count("note on link") == 1


def test_link_details_can_be_turned_off() -> None:
    output = PlantUmlRenderer(
        plan=_plan("puml", "balance"),
        options=_details_options(show=False),
    ).render(_flagged_graph())
    assert "a -[#D35400,thickness=4]-> b" in output
    assert "note on link" not in output


def test_d2_defers_a_links_details_instead_of_labelling_the_arrow() -> None:
    """A six-line arrow label is exactly the diagram inflation stacking avoids."""
    output = D2LangRenderer(
        plan=_plan("d2", "balance"),
        options=_details_options(),
    ).render(_flagged_graph())
    connection = next(line for line in output.splitlines() if line.startswith("a -> b"))
    assert "core" not in connection
    assert '"Details"' in output
    assert output.index("### a \u2192 b.util") > output.index("a -> b")
    assert "  - core" in output


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
    assert "a <-[#C0392B,bold]-> b : imports=2/1" in output


def test_d2_defers_cycle_details_to_a_separate_block() -> None:
    graph = _cyclic_graph()
    graph.cycles = CycleAnalyzer.detect_cycles(graph.links)
    options = RendererOptions(depth_colors=["#000"], show_cycle_details=True)
    output = D2LangRenderer(plan=_plan("d2"), options=options).render(graph)
    assert "a <-> b: CYCLE" in output
    assert '"Details"' in output


def test_puml_wraps_grouped_nodes_in_a_package() -> None:
    graph = _computed_graph()
    graph.groups = GroupAnalyzer.build(graph)
    output = PlantUmlRenderer(plan=_plan("puml")).render(graph)
    assert "package a {\n  class a.core" in output


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
