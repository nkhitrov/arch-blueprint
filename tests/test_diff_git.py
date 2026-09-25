"""``diff --base``: both sides built from git, end to end through the CLI."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tests.conftest import CYCLIC_MODULES, CYCLIC_PROJECT, CliResult, git, run_command

_DIFFERENT = 1
_TROUBLE = 2


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository whose committed project has no cycle: pkg_b does not import pkg_a.

    The project sits in a subdirectory, as ``src/`` usually does, so the path
    from the repository root to the project is exercised too.
    """
    project = tmp_path / "src"
    shutil.copytree(
        CYCLIC_PROJECT,
        project,
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    (project / "pkg_b" / "util.py").write_text("def work() -> None:\n    pass\n")
    git(tmp_path, "init", "-q")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "no cycle")
    return tmp_path


def _diff(repo: Path, *args: str) -> CliResult:
    return run_command(
        "diff",
        "--base",
        "HEAD",
        "src",
        *CYCLIC_MODULES,
        *args,
        check=False,
        cwd=repo,
    )


def _restore_backward_import(repo: Path) -> None:
    shutil.copy(
        CYCLIC_PROJECT / "pkg_b" / "util.py",
        repo / "src" / "pkg_b" / "util.py",
    )


def test_working_tree_equal_to_base_exits_zero(repo: Path) -> None:
    result = _diff(repo)
    assert result.returncode == 0, result.stderr
    assert "No architectural changes" in result.stdout


def test_cycle_introduced_in_the_working_tree(repo: Path) -> None:
    _restore_backward_import(repo)
    result = _diff(repo)
    assert result.returncode == _DIFFERENT, result.stderr
    assert "pkg_a <-[#C0392B,bold]-> pkg_b : NEW CYCLE" in result.stdout
    assert "- util → core" not in result.stdout  # the import notes are opt-in
    assert "- util → core" in _diff(repo, "--cycle-details").stdout


def test_head_revision_instead_of_the_working_tree(repo: Path) -> None:
    _restore_backward_import(repo)
    git(repo, "commit", "-q", "-am", "cycle")
    (repo / "src" / "pkg_b" / "util.py").write_text("")  # must be ignored
    result = _diff(repo, "--head", "HEAD", "-f", "d2")
    assert result.returncode == 0, result.stderr
    result = run_command(
        "diff",
        "--base",
        "HEAD~1",
        "--head",
        "HEAD",
        "src",
        *CYCLIC_MODULES,
        "-f",
        "d2",
        check=False,
        cwd=repo,
    )
    assert result.returncode == _DIFFERENT, result.stderr
    assert "pkg_a <-> pkg_b: NEW CYCLE" in result.stdout


def test_package_added_wholesale_is_a_diff_not_an_error(repo: Path) -> None:
    """At the base the new package does not exist; its -m must not fail the run."""
    shutil.copytree(repo / "src" / "pkg_b", repo / "src" / "pkg_c")
    result = _diff(repo, "-m", "pkg_c.*")
    assert result.returncode == _DIFFERENT, result.stderr
    assert "class pkg_c.util <<(+, #2ECC71) added>>" in result.stdout


def test_pattern_on_neither_side_is_still_an_error(repo: Path) -> None:
    result = _diff(repo, "-m", "no_such_pkg.*")
    assert result.returncode == _TROUBLE
    assert "no_such_pkg" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("rev", ["no-such-rev", "--output=x"])
def test_bad_revision_is_trouble(repo: Path, rev: str) -> None:
    result = run_command(
        "diff",
        f"--base={rev}",
        "src",
        *CYCLIC_MODULES,
        check=False,
        cwd=repo,
    )
    assert result.returncode == _TROUBLE
    assert result.stderr.startswith("arch-blueprint: ")
    assert "Traceback" not in result.stderr


def test_not_a_repository_is_trouble(tmp_path: Path) -> None:
    shutil.copytree(CYCLIC_PROJECT, tmp_path / "src")
    result = run_command(
        "diff",
        "--base",
        "HEAD",
        "src",
        *CYCLIC_MODULES,
        check=False,
        cwd=tmp_path,
    )
    assert result.returncode == _TROUBLE
    assert "git" in result.stderr
