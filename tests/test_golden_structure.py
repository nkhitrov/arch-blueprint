from __future__ import annotations

import re

import pytest

from tests.conftest import SCENARIOS, Scenario, golden_path

_CLASS = re.compile(r"^\s*class\s+(?P<name>[\w.]+)")
_PACKAGE = re.compile(r'^\s*package\s+(?P<name>[\w.]+|"[^"]+")')
_LINK = re.compile(
    r"^(?P<source>[\w.]+)\s+(?:--->|<-\[[^\]]*\]->)\s+(?P<target>[\w.]+)",
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


def _read(scenario: Scenario) -> str:
    return golden_path("puml", scenario.name).read_text(encoding="utf-8")


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
def test_no_package_wraps_a_class_of_its_own_name(scenario: Scenario) -> None:
    """``package a.b { class a.b }`` is a PlantUML syntax error ("Bad name").

    Nothing declares packages yet, so this holds trivially — it is here to stop
    namespace grouping from introducing that shape, which it would whenever a
    link endpoint happens to equal a node id.
    """
    classes, packages = _declared(_read(scenario))
    assert packages & classes == set()


@pytest.mark.xfail(
    strict=True,
    reason="links aggregate to namespaces that are never declared as nodes",
)
@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
def test_every_link_endpoint_is_declared(scenario: Scenario) -> None:
    """An arrow to an undeclared name makes PlantUML invent an empty box.

    The metric-carrying nodes then sit unconnected beside it. Namespace grouping
    is what gives these endpoints a declaration.
    """
    source = _read(scenario)
    classes, packages = _declared(source)
    assert _link_endpoints(source) <= (classes | packages)
