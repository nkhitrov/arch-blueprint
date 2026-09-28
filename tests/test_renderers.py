from __future__ import annotations

import pytest

from arch_blueprint.analyze import analyze
from arch_blueprint.analyze.cycles import CycleAnalyzer
from arch_blueprint.blueprint import ArchBlueprint
from arch_blueprint.diff import PlantUmlDiffRenderer
from arch_blueprint.domain.graph import BlueprintGraph, Cycle, Edge, Tangle
from arch_blueprint.domain.node import Node, NodeKind
from arch_blueprint.metrics import (
    MetricDisplay,
    RenderPlan,
    build_render_plan,
    default_registry,
    default_renders,
)
from arch_blueprint.renderer.base import (
    NEIGHBOR_COLOR,
    BlueprintRenderer,
    CycleRender,
    LinkDecoration,
    RendererOptions,
)
from arch_blueprint.renderer.cycles import format_edges, tangle_note_id
from arch_blueprint.renderer.d2 import D2LangRenderer, key_part
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
    """Records the cycles it was handed instead of drawing them."""

    fmt = "puml"

    def __init__(self, plan: RenderPlan) -> None:
        super().__init__(plan)
        # Shared with the copy ``render`` draws through: a shallow copy.
        self.captured: list[Cycle] = []

    def _format_node(self, node: Node, color: str, blocks: list[str]) -> str:
        return ""

    def _format_link(
        self,
        source: str,
        target: str,
        decoration: LinkDecoration,
    ) -> str:
        return ""

    def _format_cycle(
        self,
        cycle: Cycle,
        decoration: LinkDecoration,
        *,
        details: bool,
    ) -> CycleRender:
        self.captured.append(cycle)
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


@pytest.mark.parametrize("base", [PlantUmlRenderer, PlantUmlDiffRenderer])
def test_renderer_overriding_the_renamed_group_hook_is_rejected(base: type) -> None:
    """``_format_group`` is never called any more: overriding it would draw flat."""
    with pytest.raises(TypeError, match="override '_format_frame"):
        type("Grouping", (base,), {"_format_group": lambda self, *args: []})


def test_layout_read_outside_render_raises() -> None:
    """Only the copy ``render`` draws through knows the drawing's layout."""
    renderer = D2LangRenderer(plan=_plan("d2"))
    with pytest.raises(RuntimeError, match="outside render"):
        renderer._format_node(Node("a.b.X", NodeKind.CLASS), "#000", [])
    with pytest.raises(RuntimeError, match="outside render"):
        _ = PlantUmlDiffRenderer().layout
    renderer.render(_computed_graph())
    with pytest.raises(RuntimeError, match="outside render"):
        _ = renderer.layout  # render drew through a copy, not through this one


# --- nodes and links ------------------------------------------------------


def test_puml_renders_metric_blocks_in_requested_order() -> None:
    output = PlantUmlRenderer(plan=_plan("puml", "instability", "fan_in")).render(
        _computed_graph(),
    )
    assert 'class "core" as a.core <<(M, #2ECC71)>> {' in output
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
    assert 'class "core" as a.core <<(M, #2ECC71)>>\n' in output
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
    assert len(renderer.captured) == 1


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


def test_puml_wraps_framed_nodes_in_a_package() -> None:
    output = PlantUmlRenderer(plan=_plan("puml")).render(_computed_graph())
    assert 'package "a" as a {\n  class "core" as a.core' in output


def test_d2_nests_framed_nodes_by_key() -> None:
    """D2 nests by key already: ``a.core`` lands in container ``a``."""
    output = D2LangRenderer(plan=_plan("d2")).render(_computed_graph())
    assert "package" not in output
    assert output.startswith("direction: down\na.core: {")


def _definitions_graph() -> BlueprintGraph:
    """A class and a function in one module, a class in another."""
    graph = BlueprintGraph(
        nodes=[
            Node("shop.api.Service", NodeKind.CLASS),
            Node("shop.models.User", NodeKind.CLASS),
            Node("shop.models.make_user", NodeKind.FUNCTION),
        ],
        edges=frozenset(
            {
                make_edge(
                    "shop.api.Service",
                    "shop.models.make_user",
                    "shop.api.Service",
                    "shop.models.make_user",
                ),
            },
        ),
    )
    return analyze(graph)


def test_puml_spot_letter_says_what_a_node_is() -> None:
    graph = _definitions_graph()
    graph.nodes.append(Node("shop.models", NodeKind.MODULE))
    output = PlantUmlRenderer(plan=_plan("puml"), options=_FLAT).render(graph)
    assert "as shop.api.Service <<(C, " in output
    assert "as shop.models.make_user <<(F, " in output
    assert "as shop.models <<(M, " in output


def test_puml_frames_definitions_by_module() -> None:
    output = PlantUmlRenderer(plan=_plan("puml")).render(_definitions_graph())
    assert 'package "shop" as shop {\n  package "api" as shop.api {\n' in output
    assert 'class "Service" as shop.api.Service' in output
    assert 'package "models" as shop.models {\n    class "User"' in output
    assert "shop.api.Service ---> shop.models.make_user" in output


def test_d2_nests_definitions_by_key() -> None:
    output = D2LangRenderer(plan=_plan("d2")).render(_definitions_graph())
    assert "shop.api.Service: {" in output
    assert "shop.api.Service -> shop.models.make_user" in output


@pytest.mark.parametrize(
    ("part", "key"),
    [
        ("label", '"label"'),
        ("Style", '"Style"'),
        ("labels", "labels"),
        ("app.core", '"app.core"'),
        ("(module)", '"(module)"'),
    ],
)
def test_d2_quotes_a_key_part_it_would_misread(part: str, key: str) -> None:
    """``app.util.label -> ...`` is "reserved keywords are prohibited in edges"."""
    assert key_part(part) == key


def test_d2_nested_keyword_node_is_quoted_everywhere() -> None:
    edge = make_edge(
        "app.util.style",
        "app.util.label",
        "app.util.style",
        "app.util.label",
    )
    graph = make_graph(["app.util.label", "app.util.style"], [edge])
    output = D2LangRenderer(plan=_plan("d2")).render(analyze(graph))
    assert '"app.util"."label": {' in output
    assert '"app.util"."style" -> "app.util"."label"' in output


# --- frames: every chain of empty ones merged -------------------------------


def _deep_graph(*edges: Edge) -> BlueprintGraph:
    """Two classes deep under one chain of packages, and one beside it."""
    return analyze(
        make_graph(
            ["app.features.core.ep.usecases.Run", "app.features.core.ep.models.Task"],
            list(edges),
        ),
    )


_RUN_TO_TASK = make_edge(
    "app.features.core.ep.usecases.Run",
    "app.features.core.ep.models.Task",
    "app.features.core.ep.usecases",
    "app.features.core.ep.models",
)


def test_puml_merges_a_chain_of_empty_frames() -> None:
    output = PlantUmlRenderer(plan=_plan("puml")).render(_deep_graph(_RUN_TO_TASK))
    assert (
        'package "app.features.core.ep" as app.features.core.ep {\n'
        '  package "usecases" as app.features.core.ep.usecases {\n'
        '    class "Run" as app.features.core.ep.usecases.Run'
    ) in output
    assert 'package "app" ' not in output
    assert "app.features.core.ep.usecases ---> app.features.core.ep.models" in output


def test_d2_merges_a_chain_of_empty_frames_into_one_key_part() -> None:
    output = D2LangRenderer(plan=_plan("d2")).render(_deep_graph(_RUN_TO_TASK))
    assert '"app.features.core.ep".usecases.Run: {' in output
    assert '"app.features.core.ep".usecases -> "app.features.core.ep".models' in output


def test_puml_keeps_a_frame_an_arrow_ends_on() -> None:
    """``app.features`` holds one frame only, but an arrow points at it."""
    edge = make_edge(
        "outside.X",
        "app.features.core.ep.models.Task",
        "outside",
        "app.features",
    )
    graph = analyze(
        make_graph(["app.features.core.ep.models.Task", "outside.X"], [edge]),
    )
    output = PlantUmlRenderer(plan=_plan("puml")).render(graph)
    assert 'package "app.features" as app.features {' in output
    assert 'package "core.ep.models" as app.features.core.ep.models {' in output
    assert "outside ---> app.features" in output


def test_d2_keeps_a_frame_an_arrow_ends_on() -> None:
    edge = make_edge(
        "outside.X",
        "app.features.core.ep.models.Task",
        "outside",
        "app.features",
    )
    graph = analyze(
        make_graph(["app.features.core.ep.models.Task", "outside.X"], [edge]),
    )
    output = D2LangRenderer(plan=_plan("d2")).render(graph)
    assert '"app.features"."core.ep.models".Task: {' in output
    assert 'outside -> "app.features"' in output


def test_puml_keeps_a_frame_holding_a_node() -> None:
    graph = analyze(make_graph(["a.X", "a.b.c.Y"], []))
    output = PlantUmlRenderer(plan=_plan("puml")).render(graph)
    assert (
        'package "a" as a {\n  class "X" as a.X <<(M, #E74C3C)>>\n'
        '  package "b.c" as a.b.c {'
    ) in output


def test_d2_keeps_a_frame_holding_a_node() -> None:
    graph = analyze(make_graph(["a.X", "a.b.c.Y"], []))
    output = D2LangRenderer(plan=_plan("d2")).render(graph)
    assert "a.X: {" in output
    assert 'a."b.c".Y: {' in output


def test_both_formats_keep_a_frame_holding_two_frames() -> None:
    graph = analyze(make_graph(["a.b.X", "a.c.Y"], []))
    puml = PlantUmlRenderer(plan=_plan("puml")).render(graph)
    assert 'package "a" as a {\n  package "b" as a.b {' in puml
    assert 'package "c" as a.c {' in puml
    d2 = D2LangRenderer(plan=_plan("d2")).render(graph)
    assert "a.b.X: {" in d2
    assert "a.c.Y: {" in d2


@pytest.mark.parametrize(
    ("edge", "line"),
    [
        # Namespace level: both sides below their endpoints.
        pytest.param(make_edge("a.b.c", "a.d.e", "a.b", "a.d"), "- c → e", id="ns"),
        # Module level: each side is its endpoint, so each is its own name.
        pytest.param(make_edge("p.a", "p.b", "p.a", "p.b"), "- a → b", id="module"),
        # An import that lands inside a package node: cut the same way.
        pytest.param(make_edge("p.a", "p.b.x", "p.a", "p.b"), "- a → x", id="inside"),
    ],
)
def test_cycle_note_lines_cut_both_sides_alike(edge: Edge, line: str) -> None:
    assert format_edges(frozenset({edge})) == [line]


def _tangle(first: str) -> Tangle:
    return Tangle(members=(first, "z"), links=(), hidden_edges=frozenset())


@pytest.mark.parametrize(
    ("first", "second"),
    [("a.b_c", "a_b.c"), ("a_.b", "a._b"), ("a__b", "a.b"), ("a_x28_", "a(")],
)
def test_tangle_note_id_tells_dots_from_underscores(first: str, second: str) -> None:
    assert tangle_note_id(_tangle(first)) != tangle_note_id(_tangle(second))


def test_tangle_note_id_is_a_word_for_a_shadowed_member() -> None:
    """``pkg.(module)`` would end a PlantUML alias at the parenthesis."""
    assert tangle_note_id(_tangle("pkg.(module)")).isidentifier()


# --- flat names (module links) --------------------------------------------

_FLAT = RendererOptions(depth_colors=["#000"], nested=False)


def _facade_graph() -> BlueprintGraph:
    """``a.core`` imports the package ``b`` itself: an endpoint no node carries."""
    return make_graph(["a.core", "b.util"], [make_edge("a.core", "b", "a.core", "b")])


def test_flat_puml_keeps_dotted_names_whole() -> None:
    output = PlantUmlRenderer(plan=_plan("puml"), options=_FLAT).render(
        _facade_graph(),
    )
    assert "set separator none\n" in output
    assert "package" not in output
    assert "class b <<(M, #000)>>\nclass b.util" in output


def test_flat_d2_keeps_every_name_one_key() -> None:
    output = D2LangRenderer(plan=_plan("d2"), options=_FLAT).render(_facade_graph())
    assert output.index("b: {") < output.index('"b.util": {')
    assert '"a.core" -> b' in output


def test_nested_is_the_default() -> None:
    output = PlantUmlRenderer(plan=_plan("puml")).render(_facade_graph())
    assert 'package "b" as b {\n  class "util" as b.util' in output


def test_flat_declares_a_facade_with_no_node_of_its_own() -> None:
    """``a`` groups nothing — its nodes are under the deeper facade ``a.b``."""
    graph = make_graph(
        ["a.b.x", "z.m"],
        [make_edge("z.m", "a", "z.m", "a"), make_edge("z.m", "a.b", "z.m", "a.b")],
    )
    output = PlantUmlRenderer(plan=_plan("puml"), options=_FLAT).render(graph)
    assert "class a <<(M, #000)>>\nclass a.b <<(M, #000)>>\nclass a.b.x" in output


# --- flat: the prefix every name shares is the title ------------------------


def _shared_prefix_graph() -> BlueprintGraph:
    return make_graph(
        ["app.x.core.A", "app.x.util.B"],
        [make_edge("app.x.core.A", "app.x.util.B", "app.x.core.A", "app.x.util.B")],
    )


def test_flat_puml_strips_the_shared_prefix_into_the_title() -> None:
    output = PlantUmlRenderer(plan=_plan("puml"), options=_FLAT).render(
        _shared_prefix_graph(),
    )
    assert "set separator none\n\ntitle app.x\n\n" in output
    assert 'class "core.A" as app.x.core.A <<(M, #000)>>' in output
    assert "app.x.core.A ---> app.x.util.B" in output


def test_flat_d2_strips_the_shared_prefix_into_the_title() -> None:
    output = D2LangRenderer(plan=_plan("d2"), options=_FLAT).render(
        _shared_prefix_graph(),
    )
    assert output.startswith(
        "direction: down\ntitle: app.x {near: top-center; shape: text}\n",
    )
    assert '"app.x.core.A": {\n  shape: class\n  label: "core.A"\n' in output
    assert '"app.x.core.A" -> "app.x.util.B"' in output


@pytest.mark.parametrize("fmt", ["puml", "d2"])
def test_flat_single_node_keeps_its_own_name(fmt: str) -> None:
    graph = make_graph(["app.x.core.A"], [])
    renderer = {"puml": PlantUmlRenderer, "d2": D2LangRenderer}[fmt]
    output = renderer(plan=_plan(fmt), options=_FLAT).render(graph)
    if fmt == "puml":
        assert "title app.x.core\n" in output
        assert 'class "A" as app.x.core.A' in output
    else:
        assert "title: app.x.core {" in output
        assert 'label: "A"' in output


@pytest.mark.parametrize("fmt", ["puml", "d2"])
def test_flat_names_differing_at_the_first_part_have_no_title(fmt: str) -> None:
    graph = make_graph(["a.x.A", "b.x.B"], [])
    renderer = {"puml": PlantUmlRenderer, "d2": D2LangRenderer}[fmt]
    output = renderer(plan=_plan(fmt), options=_FLAT).render(graph)
    assert "title" not in output
    assert "label" not in output
    assert '"a.x.A" as' not in output


# --- neighbors (--deps) ---------------------------------------------------


def _neighbor_graph() -> BlueprintGraph:
    """``app.orders.api`` is the focus; it imports ``lib.money``, a neighbor."""
    graph = make_graph(
        ["app.orders.api", "app.orders.models", "lib.money"],
        [
            make_edge(
                "app.orders.api",
                "app.orders.models",
                "app.orders.api",
                "app.orders.models",
            ),
            make_edge("app.orders.api", "lib.money", "app.orders.api", "lib.money"),
        ],
    )
    graph.neighbors = frozenset({"lib.money"})
    default_registry().compute_all(graph)
    return analyze(graph)


def test_flat_neighbor_keeps_its_full_name_and_the_title_is_the_focus() -> None:
    output = PlantUmlRenderer(plan=_plan("puml"), options=_FLAT).render(
        _neighbor_graph(),
    )
    assert "title app.orders\n" in output
    assert 'class "api" as app.orders.api <<(M, #000)>>' in output
    assert "class lib.money <<(M, #BDC3C7)>> #line.dashed;text:7F8C8D\n" in output


def test_neighbor_draws_no_metric_blocks() -> None:
    plan = build_render_plan(
        registry=default_registry(),
        renders=default_renders(),
        display=MetricDisplay(shown=("fan_in",)),
        fmt="d2",
    )
    output = D2LangRenderer(plan=plan, options=_FLAT).render(_neighbor_graph())
    neighbor = output[output.index('"lib.money": {') :]
    assert "fan_in" not in neighbor.split("\n}\n")[0]
    assert "stroke-dash: 3" in neighbor


def test_a_renderer_that_knows_no_neighbors_draws_them_in_the_neighbor_color() -> None:
    """``_format_neighbor`` is concrete: a renderer written before it still works."""
    colors: dict[str, str] = {}

    class _Colors(_CapturingRenderer):
        def _format_node(self, node: Node, color: str, blocks: list[str]) -> str:
            colors[node.id] = color
            return ""

    _Colors(_plan("puml")).render(_neighbor_graph())
    assert colors["lib.money"] == NEIGHBOR_COLOR
    assert colors["app.orders.api"] != NEIGHBOR_COLOR
