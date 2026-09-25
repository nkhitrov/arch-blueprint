from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import (
    CYCLIC_MODULES,
    CYCLIC_PROJECT,
    DIFF_CASES,
    EXAMPLE_MODULES,
    EXAMPLE_PROJECT,
    run_cli,
    run_command,
    snapshot_path,
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


def test_errors_are_utf8_whatever_the_console_encoding() -> None:
    """A message can carry any path; a cp1252 stderr must not mangle it."""
    result = run_cli(
        EXAMPLE_PROJECT / "проект",
        "-m",
        "app1.*",
        check=False,
        extra_env={"PYTHONIOENCODING": "cp1252"},
    )
    assert result.returncode == _USAGE_ERROR
    assert "проект" in result.stderr


def test_link_metrics_reach_cyclic_connections() -> None:
    """A cycle stands for two links, so its label carries both values."""
    result = run_cli(CYCLIC_PROJECT, *CYCLIC_MODULES, "--metric", "edge_weight")
    assert "edge_weight=2/1" in result.stdout


# --- snapshot, render and diff ----------------------------------------------

_CYCLIC_SNAPSHOT = str(snapshot_path("cyclic"))
_EXAMPLE_SNAPSHOT = str(snapshot_path("example"))


def test_snapshot_rejects_drawing_options() -> None:
    result = run_cli(
        EXAMPLE_PROJECT,
        *EXAMPLE_MODULES,
        "-f",
        "json",
        "--metric",
        "fan_in",
        check=False,
    )
    assert result.returncode == _USAGE_ERROR
    assert "'render'" in result.stderr
    assert result.stdout == ""


def test_render_rejects_a_metric_the_snapshot_lacks(tmp_path: Path) -> None:
    text = Path(_CYCLIC_SNAPSHOT).read_text(encoding="utf-8")
    lean = tmp_path / "lean.json"
    lean.write_text(text.replace('"fan_in",', ""), encoding="utf-8")
    result = run_command("render", str(lean), "--metric", "fan_in", check=False)
    assert result.returncode == _USAGE_ERROR
    assert "holds no metric 'fan_in'" in result.stderr


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        pytest.param(
            ["render", "nope.json"],
            "cannot read snapshot",
            id="render_missing",
        ),
        pytest.param(["render", __file__], "not a JSON document", id="render_not_json"),
        pytest.param(
            ["diff", _CYCLIC_SNAPSHOT, "nope.json"],
            "cannot read",
            id="diff_missing",
        ),
        pytest.param(
            ["diff", _CYCLIC_SNAPSHOT, __file__],
            "not a JSON",
            id="diff_not_json",
        ),
        pytest.param(["diff", _CYCLIC_SNAPSHOT], "two snapshots", id="diff_one_input"),
        pytest.param(
            ["diff", _CYCLIC_SNAPSHOT, _CYCLIC_SNAPSHOT, "-m", "pkg_a.*"],
            "two snapshots",
            id="diff_files_with_modules",
        ),
        pytest.param(
            ["diff", "--base", "HEAD", "src"],
            "-m pattern",
            id="base_no_modules",
        ),
        pytest.param(
            ["diff", "--base", "HEAD", "no/such/dir", "-m", "x.*"],
            "no such project directory",
            id="base_missing_dir",
        ),
    ],
)
def test_render_and_diff_input_errors(args: list[str], expected: str) -> None:
    result = run_command(*args, check=False)
    assert result.returncode == _USAGE_ERROR
    assert expected in result.stderr
    assert "Traceback" not in result.stderr
    assert result.stdout == ""


def test_diff_of_equal_snapshots_exits_zero_with_a_diagram() -> None:
    result = run_command("diff", _CYCLIC_SNAPSHOT, _CYCLIC_SNAPSHOT)
    assert result.returncode == 0
    assert "No architectural changes" in result.stdout


def test_diff_of_different_snapshots_exits_one_and_still_draws() -> None:
    result = run_command("diff", _CYCLIC_SNAPSHOT, _EXAMPLE_SNAPSHOT, check=False)
    assert result.returncode == 1
    assert result.stdout.startswith("@startuml")
    assert result.stderr == ""


def test_diff_shows_new_cycle_details_on_request_only() -> None:
    """A diff is a quick look: the notes listing a cycle's imports are opt-in."""
    [new_cycle] = [case for case in DIFF_CASES if case.name == "new_cycle"]
    one_way = str(new_cycle.old)
    hidden = run_command("diff", one_way, _CYCLIC_SNAPSHOT, check=False).stdout
    shown = run_command(
        "diff",
        one_way,
        _CYCLIC_SNAPSHOT,
        "--cycle-details",
        check=False,
    ).stdout
    assert "note on link" in shown
    assert "note on link" not in hidden
    assert "NEW CYCLE" in hidden
