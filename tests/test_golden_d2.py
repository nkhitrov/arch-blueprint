from __future__ import annotations

import pytest

from tests.conftest import (
    SCENARIOS,
    Scenario,
    assert_scenario_matches_golden,
)

FORMAT = "d2"


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
def test_d2_output_matches_golden(scenario: Scenario) -> None:
    assert_scenario_matches_golden(scenario, FORMAT)
