from __future__ import annotations

import pytest

from tests.conftest import (
    EXAMPLE_MODULES,
    EXAMPLE_PROJECT,
    SCENARIOS,
    Scenario,
    assert_scenario_matches_golden,
    run_cli,
)

FORMAT = "puml"


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
def test_puml_output_matches_golden(scenario: Scenario) -> None:
    assert_scenario_matches_golden(scenario, FORMAT)


def test_output_is_deterministic() -> None:
    """Node declaration order must be stable across runs (default format)."""
    first = run_cli(EXAMPLE_PROJECT, *EXAMPLE_MODULES)
    second = run_cli(EXAMPLE_PROJECT, *EXAMPLE_MODULES)
    assert first.stdout == second.stdout
