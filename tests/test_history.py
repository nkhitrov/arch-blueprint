"""``history``: an album of diagrams over a throwaway repository's commits."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Optional

import pytest

from arch_blueprint.__main__ import _RENDERERS
from arch_blueprint.analyze import analyze
from arch_blueprint.git import Commit
from arch_blueprint.history import IMAGE_RENDERERS, SnapshotCache, collect
from arch_blueprint.snapshot import Snapshot
from tests.conftest import CliResult, git, make_edge, make_graph, run_command

_USAGE = 2
_FAILURE = 1
_FRAME = r"\d{4}_\d{4}-\d{2}-\d{2}_[0-9a-f]{7}"


def _commit(repo: Path, message: str, files: dict[str, str]) -> None:
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", message)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Four commits to the project in ``src/``, and one beside it.

    1. only ``pkg_a`` — the second root does not exist yet;
    2. ``pkg_b`` appears, depending on ``pkg_a``;
    3. a change that leaves the graph alone;
    4. ``pkg_a`` depends back on ``pkg_b``: a cycle.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    _commit(
        repo,
        "only pkg_a",
        {
            "src/pkg_a/__init__.py": "",
            "src/pkg_a/core.py": "def run() -> None:\n    pass\n",
        },
    )
    _commit(
        repo,
        "add pkg_b",
        {
            "src/pkg_b/__init__.py": "",
            "src/pkg_b/util.py": "from pkg_a import core\n",
        },
    )
    _commit(repo, "docs outside the project", {"README.md": "hello\n"})
    _commit(repo, "reword", {"src/pkg_a/core.py": "def run() -> None:\n    ...\n"})
    _commit(repo, "close a cycle", {"src/pkg_a/core.py": "from pkg_b import util\n"})
    return repo


def _history(
    repo: Path,
    *args: str,
    env: Optional[dict[str, str]] = None,
) -> CliResult:
    return run_command(
        "history",
        "src",
        "pkg_a",
        "pkg_b",
        "-o",
        "album",
        "--cache-dir",
        "cache",
        *args,
        check=False,
        cwd=repo,
        extra_env=env,
    )


def _names(directory: Path) -> list[str]:
    return sorted(path.name for path in directory.iterdir())


def test_album_has_a_frame_per_graph_change(repo: Path) -> None:
    result = _history(repo)
    assert result.returncode == 0, result.stderr
    names = _names(repo / "album")
    assert names[-1] == "index.md"
    frames = names[:-1]
    assert all(re.match(rf"^{_FRAME}(\.diff)?\.puml$", name) for name in frames)
    # The first frame has nothing to diff against; the other two have a diff.
    assert [name[:4] for name in frames] == ["0001", "0002", "0002", "0003", "0003"]
    assert not any(name.startswith("0001") and ".diff" in name for name in frames)
    [cycle_diff] = (repo / "album").glob("0003_*.diff.puml")
    [cycle_full] = [
        path for path in (repo / "album").glob("0003_*.puml") if path != cycle_diff
    ]
    assert "NEW CYCLE" in cycle_diff.read_text(encoding="utf-8")
    # A quick look: neither the diff nor the diagram lists the cycle's imports.
    assert "note " not in cycle_diff.read_text(encoding="utf-8")
    assert "note " not in cycle_full.read_text(encoding="utf-8")
    index = (repo / "album" / "index.md").read_text(encoding="utf-8")
    assert len([line for line in index.splitlines() if line.startswith("## ")]) == 3
    assert "close a cycle" in index
    assert "reword" not in index
    assert "unchanged" in result.stderr


def test_rerun_builds_nothing_and_rewrites_nothing(repo: Path) -> None:
    assert _history(repo).returncode == 0
    album = repo / "album"
    before = {path.name: path.stat().st_mtime_ns for path in album.iterdir()}
    result = _history(repo)
    assert result.returncode == 0, result.stderr
    assert "built" not in result.stderr
    assert result.stderr.count("cached") == 4  # the commits touching src/
    assert {path.name: path.stat().st_mtime_ns for path in album.iterdir()} == before
    assert (repo / "cache" / ".gitignore").read_text().splitlines()[-1] == "*"


def test_cycle_details_on_request(repo: Path) -> None:
    assert _history(repo, "--cycle-details").returncode == 0
    for path in (repo / "album").glob("0003_*.puml"):
        assert "note " in path.read_text(encoding="utf-8"), path.name


def test_modules_narrow_the_roots(repo: Path) -> None:
    result = _history(repo, "-m", "pkg_b.*")
    assert result.returncode == 0, result.stderr
    # pkg_b only: its first frame is the commit that adds it, and a cycle with
    # an unselected pkg_a is no change to what is drawn.
    assert len(list((repo / "album").glob("*.puml"))) == 1


def test_modules_outside_the_roots_are_rejected(repo: Path) -> None:
    result = _history(repo, "-m", "other.*")
    assert result.returncode == _USAGE
    assert "'other.*' is under none of the roots" in result.stderr
    assert not (repo / "album").exists()


def test_root_on_no_commit_is_an_error(repo: Path) -> None:
    result = run_command(
        "history",
        "src",
        "nope",
        "-o",
        "album",
        check=False,
        cwd=repo,
    )
    assert result.returncode == _USAGE
    assert "no modules matched: 'nope.**'" in result.stderr


def test_base_and_head_bound_the_range(repo: Path) -> None:
    result = _history(repo, "--base", "HEAD~3", "--head", "HEAD~1", "-f", "d2")
    assert result.returncode == 0, result.stderr
    # HEAD~3 (pkg_b added) is the first frame; the reword after it changes nothing.
    assert len(list((repo / "album").glob("*.d2"))) == 1


def test_frames_of_an_earlier_run_are_removed(repo: Path) -> None:
    album = repo / "album"
    album.mkdir()
    (album / "0009_2020-01-01_abcdef0.puml").write_text("stale")
    (album / "0009_2020-01-01_abcdef0.png").write_text("stale")
    (album / "0009_2020-01-01_abcdef0.d2").write_text("other format")
    (album / "notes.txt").write_text("mine")
    assert _history(repo).returncode == 0
    names = _names(album)
    assert "0009_2020-01-01_abcdef0.puml" not in names
    assert "0009_2020-01-01_abcdef0.png" not in names
    assert "0009_2020-01-01_abcdef0.d2" in names
    assert "notes.txt" in names


def test_not_a_repository_is_an_error(tmp_path: Path) -> None:
    (tmp_path / "src" / "pkg_a").mkdir(parents=True)
    result = run_command("history", "src", "pkg_a", check=False, cwd=tmp_path)
    assert result.returncode == _USAGE
    assert "git" in result.stderr


# --- images through a stand-in tool on PATH --------------------------------

_posix_only = pytest.mark.skipif(
    sys.platform == "win32",
    reason="the stand-in tool is a shell script",
)


def _tool(tmp_path: Path, body: str) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    tool = bin_dir / "plantuml"
    tool.write_text(f"#!/bin/sh\n{body}\n")
    tool.chmod(0o755)
    return {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}


_DRAWS = 'for f in "$@"; do case "$f" in -*) ;; *) : > "${f%.puml}.png";; esac; done'


@_posix_only
def test_png_images_are_drawn_next_to_the_sources(repo: Path, tmp_path: Path) -> None:
    result = _history(repo, "--png", env=_tool(tmp_path, _DRAWS))
    assert result.returncode == 0, result.stderr
    album = repo / "album"
    sources = sorted(path.stem for path in album.glob("*.puml"))
    assert sorted(path.stem for path in album.glob("*.png")) == sources
    assert "(0001_" in (album / "index.md").read_text(encoding="utf-8")


@_posix_only
def test_failed_images_keep_the_work_for_a_rerun(repo: Path, tmp_path: Path) -> None:
    failed = _history(repo, "--png", env=_tool(tmp_path, "echo broken >&2; exit 1"))
    assert failed.returncode == _FAILURE
    assert "broken" in failed.stderr
    assert len(list((repo / "album").glob("*.puml"))) == 5
    assert not list((repo / "album").glob("*.png"))

    retried = _history(repo, "--png", env=_tool(tmp_path, _DRAWS))
    assert retried.returncode == 0, retried.stderr
    assert "built" not in retried.stderr
    assert len(list((repo / "album").glob("*.png"))) == 5


def test_missing_image_tool_fails_before_any_work(repo: Path, tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    result = _history(repo, "--png", env={"PATH": str(empty)})
    assert result.returncode == _USAGE
    assert "'plantuml' on PATH" in result.stderr
    assert not (repo / "cache").exists()


def test_every_diagram_format_has_an_image_renderer() -> None:
    assert set(IMAGE_RENDERERS) == set(_RENDERERS)


# --- in process -------------------------------------------------------------


def _snapshot(*edges: tuple[str, str]) -> Snapshot:
    graph = make_graph(
        ["a.x", "b.y"],
        [make_edge(f"{s}.m", f"{t}.m", s, t) for s, t in edges],
    )
    return Snapshot(analyze(graph), frozenset())


def _commits(count: int) -> list[Commit]:
    return [Commit(f"{n:040x}", "2026-01-01", f"c{n}") for n in range(count)]


def test_collect_keeps_changes_only() -> None:
    empty = Snapshot(make_graph([], []), frozenset())
    one_way = _snapshot(("a", "b"))
    snapshots = [
        empty,
        None,
        one_way,
        one_way,
        _snapshot(("a", "b"), ("b", "a")),
        empty,
    ]
    commits = _commits(len(snapshots))
    by_sha = dict(zip([c.sha for c in commits], snapshots))
    frames = collect(commits, lambda commit: by_sha[commit.sha])
    # A leading empty graph is no frame; a trailing one is: everything went.
    assert [frame.commit.subject for frame in frames] == ["c2", "c4", "c5"]
    assert [frame.index for frame in frames] == [1, 2, 3]
    assert frames[0].previous is None
    assert frames[1].previous is one_way


def test_cache_round_trip_and_key(tmp_path: Path) -> None:
    cache = SnapshotCache(tmp_path / "cache")
    key = cache.key("tree", ["a.**"])
    assert cache.get(key) is None
    cache.put(key, "text")
    assert cache.get(key) == "text"
    assert cache.key("tree", ["a.**"]) == key
    assert cache.key("tree", ["a.*"]) != key
    assert cache.key("other", ["a.**"]) != key
    assert not list((tmp_path / "cache").rglob("*.tmp"))
