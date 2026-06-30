from __future__ import annotations

import pytest

from arch_blueprint.analyze.cycles import CycleAnalyzer
from arch_blueprint.domain.graph import BlueprintGraph, Edge, build_links
from arch_blueprint.domain.node import Node, NodeKind
from arch_blueprint.extract.base import common_depth_namespaces, parent_namespace
from arch_blueprint.extract.module_extractor import ModuleExtractor
from arch_blueprint.extract.source import GrimpSource
from arch_blueprint.metrics import default_registry
from arch_blueprint.metrics.fan_in import FanInMetric
from arch_blueprint.metrics.fan_out import FanOutMetric
from arch_blueprint.metrics.instability import InstabilityMetric
from arch_blueprint.renderer.base import RendererOptions
from tests.conftest import CYCLIC_PROJECT


def _edge(source: str, target: str, src_ns: str, tgt_ns: str) -> Edge:
    return Edge(
        source=source,
        target=target,
        source_namespace=src_ns,
        target_namespace=tgt_ns,
    )


# --- naming helpers -------------------------------------------------------


def test_parent_namespace():
    assert parent_namespace("app.models") == "app"
    assert parent_namespace("app") == "app"
    assert parent_namespace("a.b.c") == "a.b"


def test_common_depth_namespaces():
    assert common_depth_namespaces("app2.service", "app1.models") == ("app2", "app1")
    assert common_depth_namespaces("a.b.c", "a.b.d") == ("a.b.c", "a.b.d")
    assert common_depth_namespaces("a.b", "a.c") == ("a.b", "a.c")


# --- link aggregation -----------------------------------------------------


def test_build_links_groups_by_namespace_pair():
    edges = {
        _edge("a.x", "b.y", "a", "b"),
        _edge("a.z", "b.w", "a", "b"),
        _edge("a.x", "c.y", "a", "c"),
    }
    links = build_links(edges)
    by_pair = {(link.source_namespace, link.target_namespace): link for link in links}
    assert set(by_pair) == {("a", "b"), ("a", "c")}
    assert len(by_pair[("a", "b")].edges) == 2
    assert len(by_pair[("a", "c")].edges) == 1


# --- cycle detection ------------------------------------------------------


def test_detect_cycles_finds_bidirectional_pair():
    edges = {_edge("a.x", "b.y", "a", "b"), _edge("b.y", "a.x", "b", "a")}
    cycles = CycleAnalyzer.detect_cycles(build_links(edges))
    assert len(cycles) == 1
    cycle = cycles[0]
    assert {cycle.namespace_from, cycle.namespace_to} == {"a", "b"}


def test_detect_cycles_ignores_unidirectional():
    edges = {_edge("a.x", "b.y", "a", "b")}
    assert CycleAnalyzer.detect_cycles(build_links(edges)) == []


# --- metrics --------------------------------------------------------------


def _sample_graph() -> BlueprintGraph:
    nodes = [
        Node(id="a.core", kind=NodeKind.MODULE, namespace="a"),
        Node(id="b.util", kind=NodeKind.MODULE, namespace="b"),
    ]
    edges = {_edge("a.core", "b.util", "a", "b")}
    return BlueprintGraph(nodes=nodes, edges=edges)


def test_fan_in_and_fan_out():
    graph = _sample_graph()
    fan_in = FanInMetric().compute(graph)
    fan_out = FanOutMetric().compute(graph)
    assert fan_in == {"a.core": 0, "b.util": 1}
    assert fan_out == {"a.core": 1, "b.util": 0}


def test_instability():
    graph = _sample_graph()
    instability = InstabilityMetric().compute(graph)
    # a.core: out 1 / (0 + 1) = 1.0 ; b.util: out 0 / (1 + 0) = 0.0
    assert instability == {"a.core": 1.0, "b.util": 0.0}


def test_registry_compute_all_populates_graph():
    graph = _sample_graph()
    default_registry().compute_all(graph)
    assert graph.node_metrics["a.core"]["depth"] == 2
    assert graph.node_metrics["a.core"]["fan_out"] == 1
    assert graph.node_metrics["b.util"]["fan_in"] == 1


# --- renderer options -----------------------------------------------------


def test_get_color_cycles_through_palette():
    options = RendererOptions(depth_colors=["#000", "#111", "#222"])
    assert options.get_color_for_depth(0) == "#000"
    assert options.get_color_for_depth(3) == "#000"
    assert options.get_color_for_depth(4) == "#111"


def test_empty_depth_colors_rejected():
    with pytest.raises(ValueError, match="depth_colors"):
        RendererOptions(depth_colors=[])


# --- extractors (over fixtures) -------------------------------------------


def test_module_extractor_builds_cycle():
    source = GrimpSource(str(CYCLIC_PROJECT), ["pkg_a.*", "pkg_b.*"])
    graph = ModuleExtractor(source).extract()
    ids = {node.id for node in graph.nodes}
    assert ids == {"pkg_a.core", "pkg_a.services", "pkg_b.util"}
    assert all(node.kind is NodeKind.MODULE for node in graph.nodes)
    cycles = CycleAnalyzer.detect_cycles(graph.links)
    assert len(cycles) == 1
