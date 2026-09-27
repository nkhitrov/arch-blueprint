from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tests.conftest import (
    DIFF_CASES,
    SCENARIOS,
    SELECTIONS,
    Selection,
    diff_golden_path,
    golden_path,
    snapshot_path,
)

# ``class "label" as id`` / ``package "label" as id``: every drawn name is
# declared under its id and labelled apart from it (``renderer/layout.py``).
_CLASS = re.compile(r'^\s*class\s+(?:"[^"]*"\s+as\s+)?(?P<name>[\w.()]+)')
_PACKAGE = re.compile(r'^\s*package\s+(?:"[^"]*"\s+as\s+)?(?P<name>[\w.]+)')
_LINK = re.compile(
    r'^(?P<source>[\w.]+|"[^"]+")\s+(?:--->|<?-\[[^\]]*\]->)\s+'
    r'(?P<target>[\w.]+|"[^"]+")',
)


def _declared(source: str) -> tuple[set[str], set[str]]:
    """Return the class ids and package names a diagram declares."""
    classes = {m.group("name") for m in map(_CLASS.match, source.splitlines()) if m}
    packages = {
        m.group("name").strip('"')
        for m in map(_PACKAGE.match, source.splitlines())
        if m
    }
    return classes, packages


def _link_endpoints(source: str) -> set[str]:
    endpoints: set[str] = set()
    for line in source.splitlines():
        match = _LINK.match(line)
        if match:
            endpoints.update(
                match.group(end).strip('"') for end in ("source", "target")
            )
    return endpoints


# Diagrams and diffs alike: both declare packages around link endpoints.
_GOLDENS = [golden_path("puml", s.name) for s in SCENARIOS] + [
    diff_golden_path("puml", c.name) for c in DIFF_CASES
]


def _read(golden: Path) -> str:
    return golden.read_text(encoding="utf-8")


@pytest.mark.parametrize("golden", _GOLDENS, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_no_package_wraps_a_class_of_its_own_name(golden: Path) -> None:
    """``package a.b { class a.b }`` is a PlantUML syntax error ("Bad name").

    Grouping would produce exactly that shape whenever a link endpoint equals a
    node id — which it does for 18 of 23 endpoints when this project graphs
    itself, so the analyzer declines to build a container for those.
    """
    classes, packages = _declared(_read(golden))
    assert packages & classes == set()


@pytest.mark.parametrize("golden", _GOLDENS, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_every_link_endpoint_is_declared(golden: Path) -> None:
    """An arrow to an undeclared name makes PlantUML invent an empty box.

    The metric-carrying nodes then sit unconnected beside it. Namespace grouping
    is what gives these endpoints a declaration: either a package of their own,
    or a class already carrying that exact name.
    """
    source = _read(golden)
    classes, packages = _declared(source)
    assert _link_endpoints(source) <= (classes | packages)


@pytest.mark.parametrize("selection", SELECTIONS, ids=lambda s: s.name)
def test_no_node_lies_under_another(selection: Selection) -> None:
    """A node id that prefixes another is both a box and a frame when nested.

    PlantUML rejects the source; D2 draws the inner nodes as the outer one's
    fields. The module levels keep leaves; the definition levels rename a
    facade's definition named like a submodule (``pkg.__init__.mod``).
    """
    document = json.loads(snapshot_path(selection.name).read_text(encoding="utf-8"))
    ids = [node["id"] for node in document["nodes"]]
    assert [a for a in ids for b in ids if b.startswith(f"{a}.")] == []


def _frames(source: str) -> dict[str, tuple[int, int]]:
    """Each package's alias: how many classes and packages it holds directly."""
    held: dict[str, tuple[int, int]] = {"": (0, 0)}
    open_frames: list[str] = []
    for line in source.splitlines():
        package, cls = _PACKAGE.match(line), _CLASS.match(line)
        if open_frames and (package or cls):
            classes, packages = held[open_frames[-1]]
            held[open_frames[-1]] = (
                (classes + 1, packages) if cls else (classes, packages + 1)
            )
        if package:
            held[package.group("name")] = (0, 0)
            open_frames.append(package.group("name"))
        elif cls and line.rstrip().endswith("{"):  # a class's metric rows
            open_frames.append("")
        elif line.strip() == "}" and open_frames:
            open_frames.pop()
    return held


@pytest.mark.parametrize("golden", _GOLDENS, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_no_frame_holds_nothing_but_one_frame(golden: Path) -> None:
    """A chain of empty frames is noise: it is merged into one frame.

    A frame stays when it holds a node, holds two frames, or an arrow ends on
    it — then it is what the arrow points at.
    """
    source = _read(golden)
    endpoints = _link_endpoints(source)
    noise = [
        name
        for name, (classes, packages) in _frames(source).items()
        if name and classes == 0 and packages == 1 and name not in endpoints
    ]
    assert noise == []


# A title, a package label and a note's text are creole: ``__x__`` there is
# ``x`` underlined. The quoted class label is not, and ``note as id`` /
# ``id .. member`` name elements rather than show text.
_CREOLE_TEXT = re.compile(r'^\s*(?:title (?P<title>.*)|package "(?P<label>[^"]*)")')


@pytest.mark.parametrize("golden", _GOLDENS, ids=lambda p: p.stem)
def test_no_creole_markup_in_shown_names(golden: Path) -> None:
    for line in _read(golden).splitlines():
        match = _CREOLE_TEXT.match(line)
        if match is None:
            continue
        text = match.group("title") or match.group("label") or ""
        assert "__" not in text.replace("~__", ""), line
