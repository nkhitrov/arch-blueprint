from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.conftest import DIFF_CASES, SCENARIOS, diff_golden_path, golden_path

_CLASS = re.compile(r"^\s*class\s+(?P<name>[\w.]+)")
_PACKAGE = re.compile(r'^\s*package\s+(?P<name>[\w.]+|"[^"]+")')
#: Every arrow shape the PlantUML renderer emits: plain, styled one-way (what a
#: balance verdict draws), and the bidirectional cycle arrow. Missing a shape
#: here does not fail the invariants below — it makes them pass vacuously.
_LINK = re.compile(
    r"^(?P<source>[\w.]+)\s+(?:--->|<?-\[[^\]]*\]->)\s+(?P<target>[\w.]+)",
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
            endpoints.update({match.group("source"), match.group("target")})
    return endpoints


# Diagrams and diffs alike: both declare packages around link endpoints.
_GOLDENS = [golden_path("puml", s.name) for s in SCENARIOS] + [
    diff_golden_path("puml", c.name) for c in DIFF_CASES
]


def test_link_endpoints_are_found_on_every_arrow_shape_we_emit() -> None:
    """The invariant below is worthless if the regex silently skips an arrow.

    A styled one-way arrow is what a balance verdict produces, and it matched
    nothing until this test existed — so that scenario's endpoints were never
    actually checked.
    """
    source = "\n".join(
        [
            "plain ---> target",
            "styled -[#D35400,thickness=4]-> other",
            "cyclic <-[#C0392B,bold]-> partner",
        ],
    )
    assert _link_endpoints(source) == {
        "plain",
        "target",
        "styled",
        "other",
        "cyclic",
        "partner",
    }


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
