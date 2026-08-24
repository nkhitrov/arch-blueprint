from __future__ import annotations

from arch_blueprint.analyze.cycles import CycleAnalyzer
from arch_blueprint.analyze.groups import GroupAnalyzer
from arch_blueprint.domain.graph import build_links
from tests.conftest import make_edge, make_graph


def test_build_links_groups_by_namespace_pair() -> None:
    edges = frozenset(
        {
            make_edge("a.x", "b.y", "a", "b"),
            make_edge("a.z", "b.w", "a", "b"),
            make_edge("a.x", "c.y", "a", "c"),
        },
    )
    links = build_links(edges)
    by_pair = {(link.source_namespace, link.target_namespace): link for link in links}
    assert set(by_pair) == {("a", "b"), ("a", "c")}
    assert len(by_pair[("a", "b")].edges) == 2
    assert len(by_pair[("a", "c")].edges) == 1


def test_detect_cycles_finds_bidirectional_pair() -> None:
    edges = frozenset(
        {make_edge("a.x", "b.y", "a", "b"), make_edge("b.y", "a.x", "b", "a")},
    )
    cycles = CycleAnalyzer.detect_cycles(build_links(edges))
    assert len(cycles) == 1
    assert {cycles[0].namespace_from, cycles[0].namespace_to} == {"a", "b"}


def test_detect_cycles_ignores_unidirectional() -> None:
    edges = frozenset({make_edge("a.x", "b.y", "a", "b")})
    assert CycleAnalyzer.detect_cycles(build_links(edges)) == []


def test_detect_cycles_reports_each_pair_once() -> None:
    """Both directions of one cycle must not yield two Cycle objects."""
    edges = frozenset(
        {
            make_edge("a.x", "b.y", "a", "b"),
            make_edge("b.y", "a.x", "b", "a"),
            make_edge("a.z", "b.w", "a", "b"),
        },
    )
    cycles = CycleAnalyzer.detect_cycles(build_links(edges))
    assert len(cycles) == 1
    assert len(cycles[0].forward_edges) + len(cycles[0].backward_edges) == 3


def test_graph_derives_links_on_construction() -> None:
    graph = make_graph(
        ["a.core", "b.util"],
        [make_edge("a.core", "b.util", "a", "b")],
    )
    assert {(link.source_namespace, link.target_namespace) for link in graph.links} == {
        ("a", "b"),
    }
    # cycles are filled by the analyze step, not by construction
    assert graph.cycles == []


# --- grouping -------------------------------------------------------------


def test_groups_wrap_endpoints_no_node_is_named_after() -> None:
    graph = make_graph(
        ["a.core", "b.util"],
        [make_edge("a.core", "b.util", "a", "b")],
    )
    groups = GroupAnalyzer.build(graph)
    assert [(g.namespace, g.members) for g in groups] == [
        ("a", ("a.core",)),
        ("b", ("b.util",)),
    ]


def test_no_group_for_a_namespace_that_is_a_node() -> None:
    """``package a.b { class a.b }`` is a syntax error, so it is never built."""
    graph = make_graph(
        ["writer", "storage.backend"],
        [make_edge("writer", "storage.backend", "writer", "storage")],
    )
    assert [g.namespace for g in GroupAnalyzer.build(graph)] == ["storage"]


def test_nested_namespaces_pick_the_deepest() -> None:
    """Declaring a node in two containers would silently drop it."""
    graph = make_graph(
        ["a.b.c.one", "a.z.two"],
        [
            make_edge("a.b.c.one", "a.z.two", "a.b", "a.z"),
            make_edge("a.b.c.one", "a.z.two", "a.b.c", "a.z"),
        ],
    )
    owners = {
        member: group.namespace
        for group in GroupAnalyzer.build(graph)
        for member in group.members
    }
    assert owners["a.b.c.one"] == "a.b.c"


def test_nodes_outside_every_endpoint_namespace_stay_ungrouped() -> None:
    graph = make_graph(
        ["a.core", "b.util", "lonely"],
        [make_edge("a.core", "b.util", "a", "b")],
    )
    grouped = {m for group in GroupAnalyzer.build(graph) for m in group.members}
    assert "lonely" not in grouped


def test_no_links_means_no_groups() -> None:
    assert GroupAnalyzer.build(make_graph(["a.core"], [])) == []
