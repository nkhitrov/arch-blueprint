from __future__ import annotations

from collections.abc import Iterable

import pytest

from arch_blueprint.__main__ import _RENDERERS
from arch_blueprint.analyze import analyze
from arch_blueprint.diff import (
    DIFF_RENDERERS,
    ChangeStatus,
    CycleChange,
    GraphDiff,
    PlantUmlDiffRenderer,
    diff_graphs,
)
from arch_blueprint.domain.graph import BlueprintGraph, Edge
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


def test_identical_graphs_give_an_empty_diff() -> None:
    graph = _graph(NODES, [A_TO_B])
    diff = diff_graphs(graph, _graph(NODES, [A_TO_B]))
    assert diff.is_empty
    assert diff.graph.nodes == []
    assert diff.link_status == {}


@pytest.mark.parametrize("selection", SELECTIONS, ids=lambda s: s.name)
def test_every_golden_snapshot_is_equal_to_itself(selection: Selection) -> None:
    text = snapshot_path(selection.name).read_text(encoding="utf-8")
    assert diff_graphs(load(text).graph, load(text).graph).is_empty


def test_added_and_removed_nodes() -> None:
    diff = diff_graphs(_graph(["a.x", "b.y"], []), _graph(["a.x", "c.z"], []))
    assert _statuses(diff) == {
        "b.y": ChangeStatus.REMOVED,
        "c.z": ChangeStatus.ADDED,
    }
    assert not diff.is_empty


def test_added_link_shows_its_unchanged_endpoints_as_context() -> None:
    diff = diff_graphs(_graph(NODES, []), _graph(NODES, [A_TO_B]))
    assert diff.link_status == {("a", "b"): ChangeStatus.ADDED}
    # d.w and c.z take no part in the change and are hidden.
    assert _statuses(diff) == {
        "a.x": ChangeStatus.CONTEXT,
        "b.y": ChangeStatus.CONTEXT,
    }


def test_removed_link_is_taken_from_the_old_side() -> None:
    diff = diff_graphs(_graph(NODES, [A_TO_B, A_TO_C]), _graph(NODES, [A_TO_B]))
    assert diff.link_status == {("a", "c"): ChangeStatus.REMOVED}
    assert {edge.target for edge in diff.graph.edges} == {"c.z"}


def test_link_to_a_removed_module() -> None:
    diff = diff_graphs(_graph(NODES, [A_TO_C]), _graph(["a.x", "b.y", "d.w"], []))
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
    diff = diff_graphs(_graph(NODES, []), _graph(NODES, [into_submodule]))
    assert _statuses(diff) == {
        "a.x": ChangeStatus.CONTEXT,
        "b.y": ChangeStatus.CONTEXT,
    }


def test_import_of_a_package_facade_shows_the_nodes_under_it() -> None:
    """``pkg.*`` never makes ``pkg`` a node, so a facade import has no owner node."""
    into_facade = make_edge("a.x", "b", "a", "b")
    nodes = [*NODES, "b.z"]
    diff = diff_graphs(_graph(nodes, []), _graph(nodes, [into_facade]))
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
    assert diff.link_status == {}


def test_unchanged_cycle_is_hidden() -> None:
    both = [A_TO_B, B_TO_A]
    diff = diff_graphs(_graph(NODES, both), _graph(NODES, [*both, A_TO_C]))
    assert diff.cycle_changes == ()
    assert diff.link_status == {("a", "c"): ChangeStatus.ADDED}


def test_import_inside_an_existing_link_is_not_a_link_change() -> None:
    extra = make_edge("a.x2", "b.y", "a", "b")
    diff = diff_graphs(
        _graph(NODES, [A_TO_B]),
        _graph([*NODES, "a.x2"], [A_TO_B, extra]),
    )
    assert diff.link_status == {}
    assert _statuses(diff) == {"a.x2": ChangeStatus.ADDED}


def test_diff_graph_groups_nodes_under_the_changed_link_endpoints() -> None:
    diff = diff_graphs(_graph(NODES, []), _graph(NODES, [A_TO_B]))
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
