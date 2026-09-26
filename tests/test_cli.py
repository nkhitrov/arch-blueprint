from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import (
    CYCLIC_MODULES,
    CYCLIC_PROJECT,
    DIFF_CASES,
    EXAMPLE_MODULES,
    EXAMPLE_PROJECT,
    REPO_ROOT,
    posix_only,
    run_cli,
    run_command,
    snapshot_path,
    stand_in_tool,
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
            "no package 'nosuch' in",
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
        "--cycle-details",
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
    assert "when you draw the snapshot" in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        pytest.param(["-m", "pkg_a.*"], "is a snapshot, already chosen", id="modules"),
        pytest.param(["-f", "json"], "is a snapshot already", id="to_snapshot"),
    ],
)
def test_drawing_a_snapshot_rejects_project_options(
    args: list[str],
    expected: str,
) -> None:
    result = run_command("draw", _CYCLIC_SNAPSHOT, *args, check=False)
    assert result.returncode == _USAGE_ERROR
    assert expected in result.stderr


def test_the_retired_render_command_says_what_to_run() -> None:
    result = run_command("render", "graph.json", "-f", "d2", check=False)
    assert result.returncode == _USAGE_ERROR
    assert "run: arch-blueprint draw graph.json -f d2" in result.stderr


def test_render_rejects_a_metric_the_snapshot_lacks(tmp_path: Path) -> None:
    text = Path(_CYCLIC_SNAPSHOT).read_text(encoding="utf-8")
    lean = tmp_path / "lean.json"
    lean.write_text(text.replace('"fan_in",', ""), encoding="utf-8")
    result = run_command("draw", str(lean), "--metric", "fan_in", check=False)
    assert result.returncode == _USAGE_ERROR
    assert "holds no metric 'fan_in'" in result.stderr


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        pytest.param(
            ["draw", "nope.json"],
            "cannot read snapshot",
            id="render_missing",
        ),
        pytest.param(
            ["draw", __file__],
            "not a JSON document",
            id="render_not_json",
        ),
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


# --- finding one's way: commands, help, hints -------------------------------


def test_no_arguments_prints_the_commands() -> None:
    result = run_command(check=False)
    assert result.returncode == _USAGE_ERROR
    for command in ("draw", "diff", "history"):
        assert command in result.stderr
    assert result.stdout == ""


def test_version() -> None:
    result = run_command("--version")
    assert result.stdout.startswith("arch-blueprint ")


def test_list_metrics_describes_every_displayable_metric() -> None:
    lines = run_command("--list-metrics").stdout.splitlines()
    assert [line.split()[:2] for line in lines] == [
        ["fan_in", "module"],
        ["fan_out", "module"],
        ["instability", "module"],
        ["edge_weight", "link"],
    ]


def test_the_old_implicit_command_says_what_to_run() -> None:
    result = run_command(str(EXAMPLE_PROJECT), "-m", "app1.*", check=False)
    assert result.returncode == _USAGE_ERROR
    assert f"arch-blueprint draw {EXAMPLE_PROJECT} -m 'app1.*'" in result.stderr


def test_without_patterns_every_package_is_drawn_whole() -> None:
    detected = run_cli(EXAMPLE_PROJECT)
    explicit = run_cli(
        EXAMPLE_PROJECT,
        *("-m", "app1.**", "-m", "app2.**", "-m", "plugins.**"),
    )
    assert detected.stdout == explicit.stdout
    assert "drawing app1, app2, plugins" in detected.stderr


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        pytest.param(
            ["draw", str(EXAMPLE_PROJECT / "app1")],
            "pass the directory that contains it: arch-blueprint draw ",
            id="package_dir_instead_of_its_parent",
        ),
        pytest.param(
            ["draw", str(EXAMPLE_PROJECT), "-m", "nosuch.*"],
            "found: app1, app2, plugins",
            id="unknown_package_lists_the_known",
        ),
        pytest.param(
            ["draw", str(REPO_ROOT)],
            f"run 'arch-blueprint draw {REPO_ROOT / 'src'}'",
            id="src_layout_root",
        ),
        pytest.param(
            ["draw", "-m", "app1.*", str(EXAMPLE_PROJECT)],
            "put PROJECT_DIR before -m",
            id="directory_swallowed_by_m",
        ),
        pytest.param(
            ["draw", str(EXAMPLE_PROJECT), "-f", "d2", "-o", "x.puml"],
            "does not fit -o x.puml",
            id="format_contradicts_extension",
        ),
        pytest.param(
            ["draw", str(EXAMPLE_PROJECT), "-f", "puml-png"],
            "give it a file with -o",
            id="image_needs_a_file",
        ),
        pytest.param(
            ["draw", "x.json", "-o", "x.png", "-f", "d2"],
            "does not fit",
            id="render_format_contradicts_extension",
        ),
    ],
)
def test_hints_for_common_mistakes(args: list[str], expected: str) -> None:
    result = run_command(*args, check=False)
    assert result.returncode == _USAGE_ERROR
    assert expected in result.stderr
    assert result.stdout == ""


def test_a_bare_package_name_warns_about_the_single_box() -> None:
    result = run_cli(EXAMPLE_PROJECT, "-m", "app1", "-m", "app2.*")
    assert result.returncode == 0
    assert "'app1.*' for its modules" in result.stderr


# --- -o: the extension picks the format -------------------------------------


@pytest.mark.parametrize(
    ("name", "start"),
    [
        pytest.param("graph.puml", "@startuml", id="puml"),
        pytest.param("graph.d2", "direction:", id="d2"),
        pytest.param("graph.json", "{", id="json"),
        pytest.param("graph.txt", "@startuml", id="unknown_extension_keeps_puml"),
    ],
)
def test_output_file_format_follows_the_extension(
    tmp_path: Path,
    name: str,
    start: str,
) -> None:
    out = tmp_path / name
    result = run_cli(EXAMPLE_PROJECT, *EXAMPLE_MODULES, "-o", str(out))
    assert result.stdout == ""
    assert out.read_text(encoding="utf-8").startswith(start)


def test_diff_writes_its_file_and_keeps_its_exit_code(tmp_path: Path) -> None:
    out = tmp_path / "diff.d2"
    result = run_command(
        "diff",
        _CYCLIC_SNAPSHOT,
        _EXAMPLE_SNAPSHOT,
        "-o",
        str(out),
        check=False,
    )
    assert result.returncode == 1
    assert "direction:" in out.read_text(encoding="utf-8")


#: A stand-in plantuml: an image next to each source, naming the source.
_DRAWS = (
    'for f in "$@"; do case "$f" in -*) ;; '
    '*) echo "png of $(basename "$f")" > "${f%.*}.png";; esac; done'
)


@posix_only
def test_png_is_drawn_by_the_tool_into_the_output_file(tmp_path: Path) -> None:
    out = tmp_path / "arch.png"
    result = run_cli(
        EXAMPLE_PROJECT,
        *EXAMPLE_MODULES,
        "-o",
        str(out),
        extra_env=stand_in_tool(tmp_path, _DRAWS),
    )
    assert result.returncode == 0, result.stderr
    assert out.read_text() == "png of arch.puml\n"


@posix_only
def test_d2_png_by_name_of_format(tmp_path: Path) -> None:
    draws = 'echo "png" > "$2"'
    out = tmp_path / "arch.png"
    result = run_cli(
        EXAMPLE_PROJECT,
        *EXAMPLE_MODULES,
        "-f",
        "d2-png",
        "-o",
        str(out),
        extra_env=stand_in_tool(tmp_path, draws, name="d2"),
    )
    assert result.returncode == 0, result.stderr
    assert out.read_text() == "png\n"


@posix_only
def test_png_that_cannot_be_drawn_fails_and_writes_nothing(tmp_path: Path) -> None:
    out = tmp_path / "arch.png"
    result = run_cli(
        EXAMPLE_PROJECT,
        *EXAMPLE_MODULES,
        "-o",
        str(out),
        check=False,
        extra_env=stand_in_tool(tmp_path, "echo broken >&2; exit 1"),
    )
    assert result.returncode == 1
    assert "could not draw" in result.stderr
    assert "broken" in result.stderr
    assert not out.exists()


def test_png_without_the_tool_fails_before_any_work(tmp_path: Path) -> None:
    result = run_cli(
        EXAMPLE_PROJECT,
        "-o",
        str(tmp_path / "arch.png"),
        check=False,
        extra_env={"PATH": str(tmp_path)},
    )
    assert result.returncode == _USAGE_ERROR
    assert "'plantuml' on PATH" in result.stderr
    assert "drawing" not in result.stderr  # nothing was analyzed
