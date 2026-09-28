from __future__ import annotations

import json

import pytest

from arch_blueprint.domain.graph import BlueprintGraph
from arch_blueprint.domain.node import Node, NodeKind
from arch_blueprint.snapshot import SNAPSHOT_VERSION, SnapshotError, dump, load
from tests.conftest import (
    SCENARIOS,
    SELECTIONS,
    Scenario,
    Selection,
    golden_path,
    run_cli,
    run_command,
    snapshot_path,
)


@pytest.mark.parametrize("selection", SELECTIONS, ids=lambda s: s.name)
def test_snapshot_matches_golden(selection: Selection) -> None:
    expected = snapshot_path(selection.name).read_text(encoding="utf-8")
    actual = run_cli(selection.project, *selection.args, "-f", "json")
    assert actual.stdout == expected


@pytest.mark.parametrize("fmt", ["puml", "d2"])
@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
def test_render_from_snapshot_equals_direct_render(
    scenario: Scenario,
    fmt: str,
) -> None:
    """The snapshot loses nothing: drawing it gives the direct diagram, byte for byte.

    This is what lets every diagram be drawn from a snapshot. Whatever a renderer
    starts to need that the snapshot does not carry breaks this test first.
    """
    expected = golden_path(fmt, scenario.name).read_text(encoding="utf-8")
    snapshot = snapshot_path(scenario.selection.name)
    actual = run_command("draw", str(snapshot), *scenario.render_args, "-f", fmt)
    assert actual.stdout == expected


@pytest.mark.parametrize("selection", SELECTIONS, ids=lambda s: s.name)
def test_dump_of_a_load_is_the_same_bytes(selection: Selection) -> None:
    text = snapshot_path(selection.name).read_text(encoding="utf-8").rstrip("\n")
    snapshot = load(text)
    assert dump(snapshot.graph, snapshot.metrics, snapshot.links, snapshot.deps) == text


def test_load_re_derives_cycles() -> None:
    snapshot = load(snapshot_path("cyclic").read_text(encoding="utf-8"))
    [cycle] = snapshot.graph.cycles
    assert {cycle.endpoint_from, cycle.endpoint_to} == {"pkg_a", "pkg_b"}


@pytest.mark.parametrize("links", ["class", "class-grouped"])
def test_load_keeps_the_link_level_and_node_kinds(links: str) -> None:
    graph = BlueprintGraph(
        nodes=[
            Node("shop.api.Service", NodeKind.CLASS),
            Node("shop.models.User", NodeKind.CLASS),
        ],
        edges=frozenset(),
    )
    snapshot = load(dump(graph, (), links))
    assert snapshot.links == links
    assert {node.kind for node in snapshot.graph.nodes} == {NodeKind.CLASS}


def test_load_keeps_deps_and_neighbors() -> None:
    snapshot = load(snapshot_path("focus_deps_class").read_text(encoding="utf-8"))
    assert snapshot.deps == "out"
    assert snapshot.graph.neighbors == {
        "app.features.core.legal_cases.models.LegalCase",
        "app.features.core.legal_cases.usecases.RemoveOldCustomerUseCase",
        "billing.invoices.Invoice",
    }


def test_a_version_2_snapshot_reads_as_one_without_deps() -> None:
    """Version 2 had no ``--deps``: its snapshots are still drawn and diffed."""
    document = _valid()
    del document["deps"]
    del document["neighbors"]
    snapshot = load(json.dumps({**document, "version": 2}))
    assert snapshot.deps is None
    assert snapshot.graph.neighbors == frozenset()
    assert snapshot.graph.nodes == load(json.dumps(_valid())).graph.nodes


def _valid() -> dict[str, object]:
    document = json.loads(snapshot_path("cyclic").read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _without(key: str) -> dict[str, object]:
    document = _valid()
    del document[key]
    return document


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        pytest.param("{nope", "not a JSON document", id="broken_json"),
        pytest.param("[]", "expected an object", id="not_an_object"),
        pytest.param(
            json.dumps({**_valid(), "format": "something-else"}),
            "not an arch-blueprint snapshot",
            id="foreign_format",
        ),
        pytest.param(
            json.dumps({**_valid(), "version": SNAPSHOT_VERSION + 1}),
            "unsupported snapshot version",
            id="future_version",
        ),
        pytest.param(
            json.dumps(_without("edges")),
            "missing field 'edges'",
            id="edges",
        ),
        pytest.param(
            json.dumps(_without("links")),
            "missing field 'links'",
            id="links",
        ),
        pytest.param(
            json.dumps({**_valid(), "links": "method"}),
            "unknown link level 'method'",
            id="link_level",
        ),
        pytest.param(
            json.dumps({**_valid(), "nodes": [{"id": "a", "kind": "planet"}]}),
            "unknown node kind",
            id="node_kind",
        ),
        pytest.param(
            json.dumps({**_valid(), "node_metrics": {"a": {"depth": True}}}),
            "expected a number or a string",
            id="metric_value",
        ),
        pytest.param(
            json.dumps(_without("deps")),
            "missing field 'deps'",
            id="deps",
        ),
        pytest.param(
            json.dumps({**_valid(), "deps": "sideways"}),
            "unknown --deps direction 'sideways'",
            id="deps_direction",
        ),
        pytest.param(
            json.dumps({**_valid(), "neighbors": ["nowhere"]}),
            "neighbors: 'nowhere' is not a node",
            id="stray_neighbor",
        ),
    ],
)
def test_invalid_snapshots_are_rejected(document: str, expected: str) -> None:
    with pytest.raises(SnapshotError, match=expected):
        load(document)
