from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Optional

import pytest

from arch_blueprint.__main__ import _RENDERERS, _renderer
from arch_blueprint.analyze import analyze
from arch_blueprint.diff import (
    DIFF_RENDERERS,
    ChangeStatus,
    CycleChange,
    GraphDiff,
    MetricChange,
    PlantUmlDiffRenderer,
    diff_graphs,
    format_change,
)
from arch_blueprint.diff.render_base import ADDED_COLOR, REMOVED_COLOR, RESOLVED_COLOR
from arch_blueprint.domain.graph import BlueprintGraph, Edge, MetricValue
from arch_blueprint.metrics import (
    MetricDisplay,
    RenderPlan,
    build_render_plan,
    default_registry,
    default_renders,
)
from arch_blueprint.renderer.base import CYCLE_HIGHLIGHT_COLOR, DEFAULT_OPTIONS
from arch_blueprint.snapshot import load
from tests.conftest import SELECTIONS, Selection, make_edge, make_graph, snapshot_path


def _graph(node_ids: Iterable[str], edges: Iterable[Edge]) -> BlueprintGraph:
    # A hand-built graph has no cycles until analyzed; the diff compares cycles.
    return analyze(make_graph(node_ids, edges))


A_TO_B = make_edge("a.x", "b.y", "a", "b")
B_TO_A = make_edge("b.y", "a.x", "b", "a")
A_TO_C = make_edge("a.x", "c.z", "a", "c")
NODES = ["a.x", "b.y", "c.z", "d.w"]


def _statuses(diff: GraphDiff) -> dict[str, ChangeStatus]:
    return dict(diff.node_status)


def _changes(old: BlueprintGraph, new: BlueprintGraph) -> GraphDiff:
    return diff_graphs(old, new, changes_only=True)


def test_identical_graphs_give_an_empty_diff() -> None:
    graph = _graph(NODES, [A_TO_B])
    diff = _changes(graph, _graph(NODES, [A_TO_B]))
    assert diff.is_empty
    assert diff.graph.nodes == []
    assert diff.link_status == {}


def test_identical_graphs_in_full_are_all_context_and_still_empty() -> None:
    both = [A_TO_B, B_TO_A]
    diff = diff_graphs(_graph(NODES, [*both, A_TO_C]), _graph(NODES, [*both, A_TO_C]))
    assert diff.is_empty
    assert set(_statuses(diff)) == set(NODES)
    assert set(diff.node_status.values()) == {ChangeStatus.CONTEXT}
    assert diff.link_status == {("a", "c"): ChangeStatus.CONTEXT}
    [cycle] = diff.context_cycles
    assert {cycle.namespace_from, cycle.namespace_to} == {"a", "b"}


def test_full_diff_draws_the_changes_against_the_whole_graph() -> None:
    diff = diff_graphs(_graph(NODES, [A_TO_B]), _graph(NODES, [A_TO_B, A_TO_C]))
    assert diff.link_status == {
        ("a", "b"): ChangeStatus.CONTEXT,
        ("a", "c"): ChangeStatus.ADDED,
    }
    # d.w takes no part in any link, and is drawn all the same.
    assert _statuses(diff) == dict.fromkeys(NODES, ChangeStatus.CONTEXT)
    assert {edge.target for edge in diff.graph.edges} == {"b.y", "c.z"}


def test_link_that_became_a_cycle_is_not_also_drawn_as_context() -> None:
    diff = diff_graphs(_graph(NODES, [A_TO_B]), _graph(NODES, [A_TO_B, B_TO_A]))
    [change] = diff.cycle_changes
    assert change.change is CycleChange.NEW
    assert diff.link_status == {}
    assert diff.context_cycles == ()


@pytest.mark.parametrize("selection", SELECTIONS, ids=lambda s: s.name)
def test_every_golden_snapshot_is_equal_to_itself(selection: Selection) -> None:
    text = snapshot_path(selection.name).read_text(encoding="utf-8")
    assert diff_graphs(load(text).graph, load(text).graph).is_empty


def test_added_and_removed_nodes() -> None:
    diff = _changes(_graph(["a.x", "b.y"], []), _graph(["a.x", "c.z"], []))
    assert _statuses(diff) == {
        "b.y": ChangeStatus.REMOVED,
        "c.z": ChangeStatus.ADDED,
    }
    assert not diff.is_empty


def test_added_link_shows_its_unchanged_endpoints_as_context() -> None:
    diff = _changes(_graph(NODES, []), _graph(NODES, [A_TO_B]))
    assert diff.link_status == {("a", "b"): ChangeStatus.ADDED}
    # d.w and c.z take no part in the change and are hidden.
    assert _statuses(diff) == {
        "a.x": ChangeStatus.CONTEXT,
        "b.y": ChangeStatus.CONTEXT,
    }


def test_removed_link_is_taken_from_the_old_side() -> None:
    diff = _changes(_graph(NODES, [A_TO_B, A_TO_C]), _graph(NODES, [A_TO_B]))
    assert diff.link_status == {("a", "c"): ChangeStatus.REMOVED}
    assert {edge.target for edge in diff.graph.edges} == {"c.z"}


def test_link_to_a_removed_module() -> None:
    diff = _changes(_graph(NODES, [A_TO_C]), _graph(["a.x", "b.y", "d.w"], []))
    assert diff.link_status == {("a", "c"): ChangeStatus.REMOVED}
    assert _statuses(diff) == {
        "a.x": ChangeStatus.CONTEXT,
        "c.z": ChangeStatus.REMOVED,
    }


def test_import_of_a_submodule_shows_the_node_that_contains_it() -> None:
    """Nodes are packages when -m selects ``pkg.*.*``; imports name modules in them.

    Found on a real project: ``products`` importing ``accounting.constants``
    left ``accounting`` out of the diff, and the new arrow pointed at nothing.
    """
    into_submodule = make_edge("a.x", "b.y.constants", "a", "b")
    diff = _changes(_graph(NODES, []), _graph(NODES, [into_submodule]))
    assert _statuses(diff) == {
        "a.x": ChangeStatus.CONTEXT,
        "b.y": ChangeStatus.CONTEXT,
    }


def test_import_of_a_package_facade_shows_the_nodes_under_it() -> None:
    """``pkg.*`` never makes ``pkg`` a node, so a facade import has no owner node."""
    into_facade = make_edge("a.x", "b", "a", "b")
    nodes = [*NODES, "b.z"]
    diff = _changes(_graph(nodes, []), _graph(nodes, [into_facade]))
    assert _statuses(diff) == {
        "a.x": ChangeStatus.CONTEXT,
        "b.y": ChangeStatus.CONTEXT,
        "b.z": ChangeStatus.CONTEXT,
    }


def test_one_way_link_becoming_a_cycle_is_a_new_cycle() -> None:
    diff = diff_graphs(_graph(NODES, [A_TO_B]), _graph(NODES, [A_TO_B, B_TO_A]))
    [change] = diff.cycle_changes
    assert change.change is CycleChange.NEW
    assert change.cycle.backward_edges == frozenset({B_TO_A})
    # The added direction is drawn as the cycle, not as a second arrow.
    assert diff.link_status == {}
    assert not diff.is_empty


def test_broken_cycle_is_resolved_with_the_old_details() -> None:
    diff = diff_graphs(_graph(NODES, [A_TO_B, B_TO_A]), _graph(NODES, [A_TO_B]))
    [change] = diff.cycle_changes
    assert change.change is CycleChange.RESOLVED
    assert change.cycle.forward_edges == frozenset({A_TO_B})
    # Who depends on whom afterwards is the point of breaking a cycle.
    assert change.remaining == ("a", "b")
    assert diff.link_status == {}


def test_cycle_with_both_directions_gone_has_nothing_remaining() -> None:
    diff = diff_graphs(_graph(NODES, [A_TO_B, B_TO_A]), _graph(NODES, []))
    [change] = diff.cycle_changes
    assert change.change is CycleChange.RESOLVED
    assert change.remaining is None


def test_new_cycle_has_no_remaining_direction() -> None:
    diff = diff_graphs(_graph(NODES, [A_TO_B]), _graph(NODES, [A_TO_B, B_TO_A]))
    assert diff.cycle_changes[0].remaining is None


@pytest.mark.parametrize(
    ("fmt", "one_way", "no_way"),
    [
        ("puml", "a -[#95A5A6,dashed]-> b : cycle resolved", "a -[#95A5A6,dashed]- b"),
        ("d2", "a -> b: cycle resolved", "a -- b: cycle resolved"),
    ],
)
def test_resolved_cycle_is_drawn_as_the_dependency_that_remains(
    fmt: str,
    one_way: str,
    no_way: str,
) -> None:
    both = [A_TO_B, B_TO_A]
    renderer = DIFF_RENDERERS[fmt]()
    kept = renderer.render(diff_graphs(_graph(NODES, both), _graph(NODES, [A_TO_B])))
    gone = renderer.render(diff_graphs(_graph(NODES, both), _graph(NODES, [])))
    assert one_way in kept
    assert "a <-" not in kept
    assert no_way in gone


def test_unchanged_cycle_is_hidden_with_changes_only() -> None:
    both = [A_TO_B, B_TO_A]
    diff = _changes(_graph(NODES, both), _graph(NODES, [*both, A_TO_C]))
    assert diff.cycle_changes == ()
    assert diff.context_cycles == ()
    assert diff.link_status == {("a", "c"): ChangeStatus.ADDED}


def test_import_inside_an_existing_link_is_not_a_link_change() -> None:
    extra = make_edge("a.x2", "b.y", "a", "b")
    diff = _changes(
        _graph(NODES, [A_TO_B]),
        _graph([*NODES, "a.x2"], [A_TO_B, extra]),
    )
    assert diff.link_status == {}
    assert _statuses(diff) == {"a.x2": ChangeStatus.ADDED}


def test_diff_graph_groups_nodes_under_the_changed_link_endpoints() -> None:
    diff = _changes(_graph(NODES, []), _graph(NODES, [A_TO_B]))
    assert {group.namespace: group.members for group in diff.graph.groups} == {
        "a": ("a.x",),
        "b": ("b.y",),
    }


def test_empty_side_is_a_valid_input() -> None:
    """A package added wholesale diffs against a side with nothing selected."""
    diff = diff_graphs(_graph([], []), _graph(["a.x", "b.y"], [A_TO_B]))
    assert set(diff.node_status.values()) == {ChangeStatus.ADDED}
    assert diff.link_status == {("a", "b"): ChangeStatus.ADDED}


# --- rendering (in process; the goldens pin the full text) ------------------


@pytest.mark.parametrize("fmt", sorted(DIFF_RENDERERS))
def test_diff_renderer_is_stateless(fmt: str) -> None:
    diff = diff_graphs(_graph(NODES, [A_TO_B]), _graph(NODES, [A_TO_B, B_TO_A]))
    renderer = DIFF_RENDERERS[fmt]()
    assert renderer.render(diff) == renderer.render(diff)


def test_diff_renderer_without_a_format_is_rejected() -> None:
    class Nameless(PlantUmlDiffRenderer):
        fmt = ""

    with pytest.raises(TypeError, match="fmt"):
        Nameless()


def test_every_diagram_format_has_a_diff_renderer() -> None:
    """``diff -f`` must accept every format ``render -f`` does."""
    assert set(DIFF_RENDERERS) == set(_RENDERERS)


def test_module_replaced_by_a_package_is_drawn_inside_it() -> None:
    """``a/x.py`` becoming ``a/x/`` puts ``a.x`` and ``a.x.y`` in one diff.

    Found on a real project: neither PlantUML nor D2 can draw ``a.x`` as a
    class and as the container of ``a.x.y`` — the whole diagram failed.
    """
    diff = _changes(
        _graph(["a.x", "b.y"], [make_edge("b.y", "a.x", "b", "a")]),
        _graph(["a.x.y", "b.y"], [make_edge("b.y", "a.x.y", "b", "a")]),
    )
    assert _statuses(diff) == {
        "a.x.(module)": ChangeStatus.REMOVED,
        "a.x.y": ChangeStatus.ADDED,
    }
    puml = DIFF_RENDERERS["puml"]().render(diff)
    assert 'class "x" as a.x.(module) <<(-, #FF1744) removed>>' in puml
    assert "class a.x " not in puml
    d2 = DIFF_RENDERERS["d2"]().render(diff)
    assert 'a.x."(module)": {' in d2
    assert 'label: "- x"' in d2


def test_change_colors_stand_apart_from_a_plain_diagram() -> None:
    """Unchanged nodes keep their depth color, so no change may share one."""
    plain = {*DEFAULT_OPTIONS.depth_colors, CYCLE_HIGHLIGHT_COLOR}
    assert not {ADDED_COLOR, REMOVED_COLOR, RESOLVED_COLOR} & plain


@pytest.mark.parametrize(
    ("fmt", "context_node", "added_node", "added_link", "cycle"),
    [
        (
            "puml",
            f"class d.w <<(M, {DEFAULT_OPTIONS.get_color_for_depth(2)})>>",
            "<<(+, #00C853) added>> #00C853;line.dashed",
            "a -[#00C853,dashed,thickness=3]-> c : added",
            "a <-[#C0392B,bold]-> b\n",
        ),
        (
            "d2",
            f'fill: "{DEFAULT_OPTIONS.get_color_for_depth(2)}"',
            'label: "+ v"',
            "a -> c: added {",
            'a <-> b: CYCLE {style.stroke: "#C0392B"; style.stroke-width: 4}',
        ),
    ],
)
def test_unchanged_part_is_drawn_as_a_plain_diagram(
    fmt: str,
    context_node: str,
    added_node: str,
    added_link: str,
    cycle: str,
) -> None:
    both = [A_TO_B, B_TO_A]
    diff = diff_graphs(
        _graph(NODES, both),
        _graph([*NODES, "e.v"], [*both, A_TO_C]),
    )
    text = DIFF_RENDERERS[fmt]().render(diff)
    assert context_node in text
    assert added_node in text
    assert added_link in text
    assert cycle in text
    assert ": NEW CYCLE" not in text


@pytest.mark.parametrize("fmt", sorted(DIFF_RENDERERS))
def test_every_change_is_dashed(fmt: str) -> None:
    diff = diff_graphs(
        _graph(NODES, [A_TO_C]),
        _graph([*NODES, "e.v"], [A_TO_B, B_TO_A]),
    )
    text = DIFF_RENDERERS[fmt]().render(diff)
    changed = [
        line
        for line in text.splitlines()
        if any(mark in line for mark in (": added", ": removed", ": NEW CYCLE"))
    ]
    assert len(changed) == 2  # the removed link and the new cycle
    if fmt == "puml":
        assert all("dashed" in line for line in changed)
        assert "#00C853;line.dashed" in text
    else:
        assert all("stroke-dash" in line for line in changed)
        assert text.count("stroke-dash: 5") >= 3  # plus the added node


@pytest.mark.parametrize("fmt", sorted(DIFF_RENDERERS))
def test_no_change_in_full_draws_the_graph_and_says_so(fmt: str) -> None:
    graph = _graph(NODES, [A_TO_B])
    text = DIFF_RENDERERS[fmt]().render(diff_graphs(graph, _graph(NODES, [A_TO_B])))
    assert "No architectural changes" in text
    assert "d.w" in text


def _snapshot_graph(name: str) -> BlueprintGraph:
    return load(snapshot_path(name).read_text(encoding="utf-8")).graph


_SAME_GRAPHS = [
    *((s.name, lambda name=s.name: _snapshot_graph(name)) for s in SELECTIONS),
    # A cycle whose pair sorts before a plain link: declared first on both.
    ("cycle_first", lambda: _with_metrics(_graph(NODES, [A_TO_B, B_TO_A, A_TO_C]))),
]


def _with_metrics(graph: BlueprintGraph) -> BlueprintGraph:
    default_registry().compute_all(graph)  # depth colors the plain diagram's nodes
    return graph


@pytest.mark.parametrize("fmt", sorted(DIFF_RENDERERS))
@pytest.mark.parametrize(
    ("name", "build"),
    _SAME_GRAPHS,
    ids=[n for n, _ in _SAME_GRAPHS],
)
def test_diff_of_a_graph_with_itself_is_its_plain_diagram(
    fmt: str,
    name: str,
    build: Callable[[], BlueprintGraph],
) -> None:
    """Same declarations in the same order, so an album's frames lay out alike.

    The layout engine places things by declaration order: a diff that declared
    them otherwise would draw the same graph as a different picture.
    """
    graph = build()
    plain = _renderer(fmt, (), cycle_details=False, registry=default_registry())
    diff = DIFF_RENDERERS[fmt](show_cycle_details=False)
    drawn = diff.render(diff_graphs(graph, graph))
    assert _without_legend(drawn) == _without_legend(plain.render(graph))


def _without_legend(text: str) -> list[str]:
    lines = text.strip().splitlines()
    if "legend top left" in lines:  # puml
        start = lines.index("legend top left")
        del lines[start : lines.index("endlegend") + 2]
    if "diff_legend: Legend {" in lines:  # d2
        start = lines.index("diff_legend: Legend {")
        del lines[start : lines.index("}", start) + 1]
    return lines


# --- metrics ------------------------------------------------------------------
#
# Node metric values are set by hand: what is tested is how a diff compares and
# draws them, not how any one metric counts.

A2_TO_B = make_edge("a.x", "b.v", "a", "b")  # a second import inside a -> b


def _measured(
    node_ids: Iterable[str],
    edges: Iterable[Edge],
    fan_in: Optional[dict[str, int]] = None,
) -> BlueprintGraph:
    graph = _graph(node_ids, edges)
    default_registry().compute(graph, ["edge_weight"])
    for node_id, value in (fan_in or {}).items():
        graph.node_metrics.setdefault(node_id, {})["fan_in"] = value
    return graph


_SHOWN = ("fan_in", "edge_weight")


def _plan(fmt: str, *names: str) -> RenderPlan:
    return build_render_plan(
        default_registry(),
        default_renders(),
        MetricDisplay(shown=names),
        fmt,
    )


def test_without_metrics_a_diff_has_no_metric_changes() -> None:
    old = _measured(NODES, [A_TO_B], {"b.y": 1})
    new = _measured(NODES, [A_TO_B, A2_TO_B], {"b.y": 2})
    diff = diff_graphs(old, new)
    assert diff.is_empty
    assert not diff.metrics_changed
    assert (diff.node_metrics, diff.link_metrics, diff.cycle_metrics) == ({}, {}, {})


def test_a_metric_change_is_a_change_but_not_a_structural_one() -> None:
    old = _measured(NODES, [A_TO_B], {"b.y": 1, "a.x": 0})
    new = _measured(NODES, [A_TO_B, A2_TO_B], {"b.y": 2, "a.x": 0})
    diff = diff_graphs(old, new, metrics=_SHOWN)
    assert diff.is_empty  # structure alone, as for a caller asking no metrics
    assert diff.metrics_changed
    assert diff.node_metrics["b.y"] == {"fan_in": MetricChange(1, 2)}
    assert diff.node_metrics["a.x"] == {"fan_in": MetricChange(0, 0)}
    assert diff.link_metrics == {("a", "b"): {"edge_weight": MetricChange(1, 2)}}


def test_only_the_metrics_asked_for_are_compared() -> None:
    old = _measured(NODES, [A_TO_B], {"b.y": 1})
    new = _measured(NODES, [A_TO_B, A2_TO_B], {"b.y": 2})
    diff = diff_graphs(old, new, metrics=["edge_weight"])
    assert diff.node_metrics == {}
    assert diff.metrics_changed


def test_added_and_removed_have_one_side_and_are_no_metric_change() -> None:
    old = _measured(NODES, [A_TO_C], {"c.z": 1})
    new = _measured([*NODES, "e.v"], [A_TO_B], {"e.v": 0})
    diff = diff_graphs(old, new, metrics=_SHOWN)
    assert diff.node_metrics["c.z"] == {"fan_in": MetricChange(1, None)}
    assert diff.node_metrics["e.v"] == {"fan_in": MetricChange(None, 0)}
    assert diff.link_metrics == {
        ("a", "b"): {"edge_weight": MetricChange(None, 1)},
        ("a", "c"): {"edge_weight": MetricChange(1, None)},
    }
    assert not diff.metrics_changed


def test_cycle_metrics_combine_both_directions_on_each_side() -> None:
    both = [A_TO_B, B_TO_A]
    key = frozenset({"a", "b"})
    unchanged = diff_graphs(
        _measured(NODES, both),
        _measured(NODES, [*both, A2_TO_B]),
        metrics=_SHOWN,
    )
    [cycle] = unchanged.context_cycles
    forward = cycle.namespace_from == "a"
    expected = MetricChange("1/1", "2/1" if forward else "1/2")
    assert unchanged.cycle_metrics == {key: {"edge_weight": expected}}
    assert unchanged.metrics_changed

    # One direction before, both after: the cycle reads 1 → 1/1.
    new = diff_graphs(
        _measured(NODES, [A_TO_B]),
        _measured(NODES, both),
        metrics=_SHOWN,
    )
    assert new.cycle_metrics == {key: {"edge_weight": MetricChange(1, "1/1")}}
    # And resolved, the direction that remains: 1/1 → 2.
    resolved = diff_graphs(
        _measured(NODES, both),
        _measured(NODES, [A_TO_B, A2_TO_B]),
        metrics=_SHOWN,
    )
    assert resolved.cycle_metrics == {key: {"edge_weight": MetricChange("1/1", 2)}}


def test_changes_only_shows_what_a_metric_change_touches() -> None:
    old = _measured(NODES, [A_TO_B, A_TO_C], {"d.w": 1, "c.z": 1})
    new = _measured(NODES, [A_TO_B, A2_TO_B, A_TO_C], {"d.w": 2, "c.z": 1})
    diff = diff_graphs(old, new, changes_only=True, metrics=_SHOWN)
    # a -> b moved its weight, d.w its fan_in; a -> c and c.z did not change.
    assert diff.link_status == {("a", "b"): ChangeStatus.CONTEXT}
    assert _statuses(diff) == dict.fromkeys(["a.x", "b.y", "d.w"], ChangeStatus.CONTEXT)
    # Without metrics there is nothing to show.
    assert diff_graphs(old, new, changes_only=True).graph.nodes == []


def test_changes_only_shows_an_unchanged_cycle_whose_metric_changed() -> None:
    both = [A_TO_B, B_TO_A]
    old, new = _measured(NODES, both), _measured(NODES, [*both, A2_TO_B])
    assert _changes(old, new).context_cycles == ()
    diff = diff_graphs(old, new, changes_only=True, metrics=_SHOWN)
    assert len(diff.context_cycles) == 1
    assert diff.link_status == {}  # drawn as the cycle, not as an arrow


@pytest.mark.parametrize(
    ("change", "written"),
    [
        (MetricChange(3, 5), "3 → 5 (+2)"),
        (MetricChange(21, 4), "21 → 4 (-17)"),
        (MetricChange(0.5, 0.67), "0.5 → 0.67 (+0.17)"),
        (MetricChange(1.0, 0.5), "1.0 → 0.5 (-0.5)"),
        (MetricChange("2/1", "2/2"), "2/1 → 2/2"),
        (MetricChange(1, "1/1"), "1 → 1/1"),
        # Unchanged, added and removed pass the value itself: drawn as plain.
        (MetricChange(1.0, 1.0), 1.0),
        (MetricChange(None, 3), 3),
        (MetricChange(3, None), 3),
    ],
)
def test_format_change(change: MetricChange, written: MetricValue) -> None:
    assert format_change(change) == written
    assert type(format_change(change)) is type(written)


@pytest.mark.parametrize(
    ("fmt", "node_row", "link", "cycle"),
    [
        (
            "puml",
            "    fan_in: 1 → 3 (+2)\n",
            "a ---> c : edge_weight=1 → 2 (+1)",
            "a <-[#C0392B,bold]-> b : edge_weight=1/1",
        ),
        (
            "d2",
            "  fan_in: 1 → 3 (+2)\n",
            "a -> c: edge_weight=1 → 2 (+1)",
            'a <-> b: CYCLE edge_weight=1/1 {style.stroke: "#C0392B"',
        ),
    ],
)
def test_changed_metrics_are_drawn_old_to_new(
    fmt: str,
    node_row: str,
    link: str,
    cycle: str,
) -> None:
    both = [A_TO_B, B_TO_A]
    a_to_c2 = make_edge("a.x", "c.q", "a", "c")
    diff = diff_graphs(
        _measured(NODES, [*both, A_TO_C], {"c.z": 1, "d.w": 4}),
        _measured(NODES, [*both, A_TO_C, a_to_c2], {"c.z": 3, "d.w": 4}),
        metrics=_SHOWN,
    )
    text = DIFF_RENDERERS[fmt](plan=_plan(fmt, *_SHOWN)).render(diff)
    assert node_row in text
    assert "fan_in: 4\n" in text  # unchanged: as on a plain diagram
    assert link in text
    assert cycle in text
    assert "metric: old → new (difference)" in text


@pytest.mark.parametrize(
    ("fmt", "added", "removed", "new_cycle"),
    [
        (
            "puml",
            "a -[#00C853,dashed,thickness=3]-> c : added edge_weight=1",
            "b -[#FF1744,dashed,thickness=2]-> d : removed edge_weight=1",
            ": NEW CYCLE edge_weight=1 → 1/1",
        ),
        (
            "d2",
            "a -> c: added edge_weight=1 {",
            "b -> d: removed edge_weight=1 {",
            ": NEW CYCLE edge_weight=1 → 1/1 {",
        ),
    ],
)
def test_changed_links_and_cycles_carry_their_metrics(
    fmt: str,
    added: str,
    removed: str,
    new_cycle: str,
) -> None:
    b_to_d = make_edge("b.y", "d.w", "b", "d")
    diff = diff_graphs(
        _measured(NODES, [A_TO_B, b_to_d]),
        _measured(NODES, [A_TO_B, B_TO_A, A_TO_C]),
        metrics=_SHOWN,
    )
    text = DIFF_RENDERERS[fmt](plan=_plan(fmt, *_SHOWN)).render(diff)
    assert added in text
    assert removed in text
    assert new_cycle in text


@pytest.mark.parametrize("fmt", sorted(DIFF_RENDERERS))
def test_without_a_plan_no_metric_is_drawn(fmt: str) -> None:
    diff = diff_graphs(
        _measured(NODES, [A_TO_B], {"b.y": 1}),
        _measured(NODES, [A_TO_B, A2_TO_B], {"b.y": 2}),
        metrics=_SHOWN,
    )
    text = DIFF_RENDERERS[fmt]().render(diff)
    assert "fan_in" not in text
    assert "edge_weight" not in text
    assert "metric:" not in text


def test_a_plan_for_another_format_is_rejected() -> None:
    with pytest.raises(ValueError, match="built for 'd2'"):
        PlantUmlDiffRenderer(plan=_plan("d2"))


_METRICS_SHOWN = ("fan_in", "fan_out", "instability", "edge_weight")


@pytest.mark.parametrize("fmt", sorted(DIFF_RENDERERS))
@pytest.mark.parametrize(
    ("name", "build"),
    _SAME_GRAPHS,
    ids=[n for n, _ in _SAME_GRAPHS],
)
def test_diff_with_metrics_of_a_graph_with_itself_is_its_plain_diagram(
    fmt: str,
    name: str,
    build: Callable[[], BlueprintGraph],
) -> None:
    """Metrics too: an album's frames draw every value as the plain one does."""
    graph = build()
    plain = _renderer(
        fmt,
        _METRICS_SHOWN,
        cycle_details=False,
        registry=default_registry(),
    )
    diff = DIFF_RENDERERS[fmt](plan=_plan(fmt, *_METRICS_SHOWN))
    drawn = diff.render(diff_graphs(graph, graph, metrics=_METRICS_SHOWN))
    assert _without_legend(drawn) == _without_legend(plain.render(graph))
