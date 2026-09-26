"""``history``: an album of diagrams over a throwaway repository's commits."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import pytest

from arch_blueprint.__main__ import _RENDERERS
from arch_blueprint.analyze import analyze
from arch_blueprint.extract.layout import has_source
from arch_blueprint.git import Commit
from arch_blueprint.history import IMAGE_RENDERERS, ImageCache, SnapshotCache, collect
from arch_blueprint.snapshot import Snapshot
from tests.conftest import (
    CliResult,
    git,
    make_edge,
    make_graph,
    posix_only,
    run_command,
    stand_in_tool,
)

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


def test_roots_default_to_every_package_at_head(repo: Path) -> None:
    assert _history(repo).returncode == 0
    result = run_command(
        "history",
        "src",
        "-o",
        "detected",
        "--cache-dir",
        "cache",
        check=False,
        cwd=repo,
    )
    assert result.returncode == 0, result.stderr
    assert "drawing pkg_a, pkg_b (as of HEAD" in result.stderr
    named = {path.name: path.read_bytes() for path in (repo / "album").iterdir()}
    detected = {path.name: path.read_bytes() for path in (repo / "detected").iterdir()}
    assert detected == named


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


@pytest.mark.parametrize(("args", "shown"), [((), True), (("--changes-only",), False)])
def test_diff_frame_shows_the_whole_graph(
    tmp_path: Path,
    args: tuple[str, ...],
    shown: bool,
) -> None:
    """A module no change touches is on the diff too, unless --changes-only."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    _commit(
        repo,
        "pkg_a",
        {"src/pkg_a/__init__.py": "", "src/pkg_a/core.py": "", "src/pkg_a/idle.py": ""},
    )
    _commit(
        repo,
        "pkg_b",
        {"src/pkg_b/__init__.py": "", "src/pkg_b/util.py": "from pkg_a import core\n"},
    )
    assert _history(repo, *args).returncode == 0
    [diff] = (repo / "album").glob("0002_*.diff.puml")
    text = diff.read_text(encoding="utf-8")
    assert "pkg_b.util <<(+" in text
    assert ("class pkg_a.idle " in text) is shown


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
    (album / "0009_2020-01-01_abcdef0.png").write_text("another kind of album")
    (album / "notes.txt").write_text("mine")
    assert _history(repo).returncode == 0
    names = _names(album)
    assert "0009_2020-01-01_abcdef0.puml" not in names
    assert "0009_2020-01-01_abcdef0.png" in names
    assert "notes.txt" in names


def test_not_a_repository_is_an_error(tmp_path: Path) -> None:
    (tmp_path / "src" / "pkg_a").mkdir(parents=True)
    result = run_command("history", "src", "pkg_a", check=False, cwd=tmp_path)
    assert result.returncode == _USAGE
    assert "git" in result.stderr


def test_root_without_code_yet_is_no_source(tmp_path: Path) -> None:
    """A project's first commits often have the package directory and no Python."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    _commit(repo, "skeleton", {"src/pkg_a/README": "soon\n"})
    _commit(repo, "code", {"src/pkg_a/__init__.py": "", "src/pkg_a/core.py": ""})
    result = run_command(
        "history",
        "src",
        "pkg_a",
        "-o",
        "album",
        "--cache-dir",
        "cache",
        check=False,
        cwd=repo,
    )
    assert result.returncode == 0, result.stderr
    first, second = result.stderr.splitlines()[:2]
    assert first.endswith(" no source yet")
    [frame] = (repo / "album").glob("0001_*")
    assert second.endswith(f" built: {frame.stem}")
    assert "warning" not in result.stderr
    assert "skipped" not in result.stderr


@pytest.mark.parametrize(
    ("layout", "expected"),
    [
        ({"pkg.py": ""}, True),
        ({"pkg/__init__.py": ""}, True),
        ({"pkg/ns/inner/__init__.py": ""}, True),  # a namespace package
        ({"pkg/README": "", "pkg/loose/notes.txt": ""}, False),
        ({"other.py": ""}, False),
    ],
)
def test_has_source(tmp_path: Path, layout: dict[str, str], expected: bool) -> None:
    for name, text in layout.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text)
    assert has_source(str(tmp_path), "pkg") is expected


# --- images through a stand-in tool on PATH --------------------------------

_posix_only = posix_only
_tool = stand_in_tool


def _calls(tmp_path: Path) -> list[str]:
    log = tmp_path / "bin" / "calls"
    return log.read_text().splitlines() if log.exists() else []


_DRAWS = """for f in "$@"; do case "$f" in
  -*) ;;
  *) echo "png of $(basename "$f")" > "${f%.puml}.png";;
esac; done"""


@_posix_only
def test_png_album_holds_images_only(repo: Path, tmp_path: Path) -> None:
    result = _history(repo, "-f", "puml-png", env=_tool(tmp_path, _DRAWS))
    assert result.returncode == 0, result.stderr
    names = _names(repo / "album")
    assert names[-1] == "index.md"
    assert len(names) == 6, names
    assert all(re.match(rf"^{_FRAME}(\.diff)?\.png$", name) for name in names[:-1])
    index = (repo / "album" / "index.md").read_text(encoding="utf-8")
    assert "![Diagram](0001_" in index
    assert ".puml" not in index
    # Each image is the one drawn from that frame's own source.
    for path in (repo / "album").glob("*.png"):
        assert path.read_text() == f"png of {path.stem}.puml\n"


@_posix_only
def test_png_rerun_draws_nothing(repo: Path, tmp_path: Path) -> None:
    env = _tool(tmp_path, _DRAWS)
    assert _history(repo, "-f", "puml-png", env=env).returncode == 0
    album = repo / "album"
    before = {path.name: path.stat().st_mtime_ns for path in album.iterdir()}
    (tmp_path / "bin" / "calls").unlink()
    result = _history(repo, "-f", "puml-png", env=env)
    assert result.returncode == 0, result.stderr
    assert _calls(tmp_path) == []
    assert {path.name: path.stat().st_mtime_ns for path in album.iterdir()} == before
    # Another album of the same history reuses the drawn images as well.
    other = _history(repo, "-f", "puml-png", "-o", "elsewhere", env=env)
    assert other.returncode == 0, other.stderr
    assert _calls(tmp_path) == []


@_posix_only
def test_failed_images_keep_the_work_for_a_rerun(repo: Path, tmp_path: Path) -> None:
    env = _tool(tmp_path, "echo broken >&2; exit 1")
    failed = _history(repo, "-f", "puml-png", env=env)
    assert failed.returncode == _FAILURE
    assert "broken" in failed.stderr
    assert not list((repo / "album").glob("*.png"))

    retried = _history(repo, "-f", "puml-png", env=_tool(tmp_path, _DRAWS))
    assert retried.returncode == 0, retried.stderr
    assert "built" not in retried.stderr
    assert len(list((repo / "album").glob("*.png"))) == 5


@_posix_only
def test_plantuml_is_not_cropped_at_its_default_size(
    repo: Path,
    tmp_path: Path,
) -> None:
    body = 'echo "$PLANTUML_LIMIT_SIZE" >> "$(dirname "$0")/limits"\n' + _DRAWS
    assert _history(repo, "-f", "puml-png", env=_tool(tmp_path, body)).returncode == 0
    assert set((tmp_path / "bin" / "limits").read_text().split()) == {"16384"}
    # The user's own limit wins — and is another image, so it is drawn again.
    (tmp_path / "bin" / "limits").unlink()
    env = {**_tool(tmp_path, body), "PLANTUML_LIMIT_SIZE": "8192"}
    assert _history(repo, "-f", "puml-png", env=env).returncode == 0
    assert set((tmp_path / "bin" / "limits").read_text().split()) == {"8192"}


def test_missing_image_tool_fails_before_any_work(repo: Path, tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    result = _history(repo, "-f", "puml-png", env={"PATH": str(empty)})
    assert result.returncode == _USAGE
    assert "'plantuml' on PATH" in result.stderr
    assert not (repo / "cache").exists()


# A d2 that, like the real one, refuses a diagram too large to rasterize — here
# anything drawn above scale 0.25.
_D2_TOO_LARGE = """for a in "$@"; do last=$a; done
case "$1" in --scale=0.25|--scale=0.125) : > "$last"; exit 0;; esac
echo "err: d2raster: scanline work 5 exceeds limit 4" >&2; exit 1"""


@_posix_only
def test_d2_too_large_is_drawn_at_a_smaller_scale(repo: Path, tmp_path: Path) -> None:
    env = _tool(tmp_path, _D2_TOO_LARGE, "d2")
    result = _history(repo, "-f", "d2-png", env=env)
    assert result.returncode == 0, result.stderr
    assert len(list((repo / "album").glob("*.png"))) == 5
    assert "too large for d2, drawn at scale 0.25" in result.stderr
    first = [call.split()[0] for call in _calls(tmp_path)[:3]]
    # The default size first, then halved twice.
    assert not first[0].startswith("--scale")
    assert first[1:] == ["--scale=0.5", "--scale=0.25"]


@_posix_only
def test_d2_scale_is_passed_and_halved_from(repo: Path, tmp_path: Path) -> None:
    env = _tool(tmp_path, _D2_TOO_LARGE, "d2")
    result = _history(repo, "-f", "d2-png", "--scale", "0.5", env=env)
    assert result.returncode == 0, result.stderr
    first = [call.split()[0] for call in _calls(tmp_path)[:2]]
    assert first == ["--scale=0.5", "--scale=0.25"]


@_posix_only
def test_d2_too_large_at_every_scale_fails(repo: Path, tmp_path: Path) -> None:
    env = _tool(tmp_path, 'echo "exceeds limit" >&2; exit 1', "d2")
    result = _history(repo, "-f", "d2-png", env=env)
    assert result.returncode == _FAILURE
    assert "exceeds limit" in result.stderr
    assert not list((repo / "album").glob("*.png"))
    # Each source: the default size, then three halvings.
    assert len(_calls(tmp_path)) == 5 * (1 + 3)


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["-f", "puml-png", "--scale", "0.5"], "--scale applies to -f d2-png"),
        (["-f", "d2", "--scale", "0.5"], "--scale applies to -f d2-png"),
        (["-f", "d2-png", "--scale", "0"], "expected a positive number"),
        (["--png"], "unrecognized arguments: --png"),
    ],
)
def test_option_misuse_is_rejected(repo: Path, args: list[str], expected: str) -> None:
    result = _history(repo, *args)
    assert result.returncode == _USAGE
    assert expected in result.stderr


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


def test_image_cache_is_keyed_by_what_the_image_shows(tmp_path: Path) -> None:
    cache = ImageCache(tmp_path / "cache")
    key = cache.key("d2", "", "a -> b")
    assert cache.get(key) is None
    drawn = tmp_path / "drawn.png"
    image = b"png"
    drawn.write_bytes(image)
    stored = cache.store(key, drawn)
    assert cache.get(key) == stored
    assert stored.read_bytes() == image
    assert cache.key("d2", "scale=0.5", "a -> b") != key  # other settings, other image
    assert cache.key("puml", "", "a -> b") != key
    assert cache.key("d2", "", "a -> c") != key
    assert not list((tmp_path / "cache").rglob("*.tmp"))
