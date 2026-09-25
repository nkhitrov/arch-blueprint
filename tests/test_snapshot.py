from __future__ import annotations

import json

import pytest

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
    actual = run_cli(selection.project, *selection.modules, "-f", "json")
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
    actual = run_command("render", str(snapshot), *scenario.render_args, "-f", fmt)
    assert actual.stdout == expected


@pytest.mark.parametrize("selection", SELECTIONS, ids=lambda s: s.name)
def test_dump_of_a_load_is_the_same_bytes(selection: Selection) -> None:
    text = snapshot_path(selection.name).read_text(encoding="utf-8").rstrip("\n")
    snapshot = load(text)
    assert dump(snapshot.graph, snapshot.metrics) == text


def test_load_re_derives_cycles_and_groups() -> None:
    snapshot = load(snapshot_path("cyclic").read_text(encoding="utf-8"))
    [cycle] = snapshot.graph.cycles
    assert {cycle.namespace_from, cycle.namespace_to} == {"pkg_a", "pkg_b"}
    assert {group.namespace for group in snapshot.graph.groups} == {"pkg_a", "pkg_b"}


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
            json.dumps({**_valid(), "nodes": [{"id": "a", "kind": "planet"}]}),
            "unknown node kind",
            id="node_kind",
        ),
        pytest.param(
            json.dumps({**_valid(), "node_metrics": {"a": {"depth": True}}}),
            "expected a number or a string",
            id="metric_value",
        ),
    ],
)
def test_invalid_snapshots_are_rejected(document: str, expected: str) -> None:
    with pytest.raises(SnapshotError, match=expected):
        load(document)
