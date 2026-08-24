from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import (
    CYCLIC_MODULES,
    CYCLIC_PROJECT,
    EXAMPLE_MODULES,
    EXAMPLE_PROJECT,
    run_cli,
)

_USAGE_ERROR = 2


def test_successful_run_reports_success() -> None:
    result = run_cli(EXAMPLE_PROJECT, *EXAMPLE_MODULES)
    assert result.returncode == 0
    assert result.stdout.startswith("@startuml")
    assert result.stderr == ""


@pytest.mark.parametrize(
    ("project", "args", "expected"),
    [
        pytest.param(
            EXAMPLE_PROJECT / "nope",
            ["-m", "app1.*"],
            "no such project directory",
            id="missing_dir",
        ),
        pytest.param(
            EXAMPLE_PROJECT,
            ["-m", "nosuch.*"],
            "Can't import module",
            id="unimportable",
        ),
        pytest.param(
            EXAMPLE_PROJECT,
            ["-m", "app1.zzz.*"],
            "no modules matched",
            id="no_match",
        ),
        pytest.param(
            EXAMPLE_PROJECT,
            ["-m", "app1.*", "--metric", "fanin"],
            "unknown metric 'fanin'",
            id="metric_typo",
        ),
        pytest.param(
            EXAMPLE_PROJECT,
            ["-m", "app1.*", "--metric", "depth"],
            "compute-only",
            id="metric_not_displayable",
        ),
    ],
)
def test_input_errors_are_reported_without_a_traceback(
    project: Path,
    args: list[str],
    expected: str,
) -> None:
    result = run_cli(project, *args, check=False)
    assert result.returncode == _USAGE_ERROR
    assert expected in result.stderr
    assert "Traceback" not in result.stderr
    assert result.stdout == ""


def test_metric_typo_lists_the_available_names() -> None:
    result = run_cli(EXAMPLE_PROJECT, "-m", "app1.*", "--metric", "fanin", check=False)
    assert "fan_in" in result.stderr
    assert "edge_weight" in result.stderr


def test_output_is_utf8_whatever_the_console_encoding() -> None:
    """Cycle details contain arrows; a cp1252 console must not kill the run."""
    result = run_cli(
        CYCLIC_PROJECT,
        *CYCLIC_MODULES,
        extra_env={"PYTHONIOENCODING": "cp1252"},
    )
    assert result.returncode == 0
    assert "→" in result.stdout


def test_link_metrics_reach_cyclic_connections() -> None:
    """A cycle stands for two links, so its label carries both values."""
    result = run_cli(CYCLIC_PROJECT, *CYCLIC_MODULES, "--metric", "edge_weight")
    assert "edge_weight=2/1" in result.stdout
