"""An album of a project's history: one frame per commit that changed its graph.

Each frame is the full diagram at that commit plus, from the second frame on,
the diff against the frame before it. Files are numbered so that sorting by name
is chronological; the date and short sha in the name are for the reader.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Optional

from arch_blueprint.diff import diff_graphs
from arch_blueprint.git import Commit
from arch_blueprint.snapshot import Snapshot

INDEX_NAME: Final = "index.md"
IMAGE_EXTENSION: Final = "png"

#: A frame's file name, less the extension; anything else in the directory is not ours.
_FRAME_STEM: Final = r"\d{4,}_\d{4}-\d{2}-\d{2}_[0-9a-f]+(\.diff)?"

SnapshotSource = Callable[[Commit], Optional[Snapshot]]
CommitReport = Callable[[Commit, Optional["Frame"]], None]


@dataclass(frozen=True)
class Frame:
    """A commit whose graph differs from the previous frame's."""

    index: int
    commit: Commit
    snapshot: Snapshot
    #: The frame before this one; ``None`` for the first frame, which has no diff.
    previous: Optional[Snapshot]

    @property
    def stem(self) -> str:
        return f"{self.index:04d}_{self.commit.date}_{self.commit.short}"


def collect(
    commits: Iterable[Commit],
    snapshot_for: SnapshotSource,
    report: Optional[CommitReport] = None,
) -> list[Frame]:
    """Keep the commits whose graph changed, compared by structure alone.

    ``snapshot_for`` returns ``None`` for a commit that cannot be graphed; it is
    skipped. Until the first frame, an empty graph (no selected root exists yet)
    is skipped too; after it, emptiness is a change like any other.
    """
    frames: list[Frame] = []
    previous: Optional[Snapshot] = None
    for commit in commits:
        snapshot = snapshot_for(commit)
        frame: Optional[Frame] = None
        if snapshot is not None and _is_change(previous, snapshot):
            frame = Frame(len(frames) + 1, commit, snapshot, previous)
            frames.append(frame)
            previous = snapshot
        if report is not None:
            report(commit, frame)
    return frames


def _is_change(previous: Optional[Snapshot], snapshot: Snapshot) -> bool:
    if previous is None:
        return bool(snapshot.graph.nodes)
    return not diff_graphs(previous.graph, snapshot.graph).is_empty


@dataclass(frozen=True)
class AlbumFiles:
    """Diagram sources of an album, in frame order, and which of them changed."""

    sources: tuple[Path, ...]
    changed: frozenset[Path]


def write(
    frames: Sequence[Frame],
    out_dir: Path,
    extension: str,
    draw: Callable[[Snapshot], str],
    draw_diff: Callable[[Snapshot, Snapshot], str],
    *,
    images: bool,
) -> AlbumFiles:
    """Write every frame's sources and the index; drop frames of earlier runs.

    A file whose content is unchanged is left alone, and so is its image: a
    rerun redraws only what changed. The image of a changed source is removed,
    since it no longer shows the source.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    sources: list[Path] = []
    changed: set[Path] = set()
    for frame in frames:
        pages = []
        if frame.previous is not None:
            pages.append(
                (f"{frame.stem}.diff", draw_diff(frame.previous, frame.snapshot)),
            )
        pages.append((frame.stem, draw(frame.snapshot)))
        for name, text in pages:
            path = out_dir / f"{name}.{extension}"
            sources.append(path)
            if _write_if_changed(path, text):
                changed.add(path)
                image_of(path).unlink(missing_ok=True)
    _write_if_changed(out_dir / INDEX_NAME, _index(frames, extension, images=images))
    _remove_stale(out_dir, sources, extension)
    return AlbumFiles(tuple(sources), frozenset(changed))


def image_of(source: Path) -> Path:
    """Where a diagram's image goes: next to it, same name."""
    return source.with_name(f"{source.stem}.{IMAGE_EXTENSION}")


def _write_if_changed(path: Path, text: str) -> bool:
    content = f"{text}\n"
    try:
        if path.read_text(encoding="utf-8") == content:
            return False
    except FileNotFoundError:
        pass
    path.write_text(content, encoding="utf-8")
    return True


def _remove_stale(out_dir: Path, sources: Sequence[Path], extension: str) -> None:
    """Remove frame files this run did not produce — a shorter or other range.

    Only this format's sources and images; the other format's sources are left
    alone. Images of both formats share names, so give each format its own
    directory.
    """
    ours = re.compile(
        rf"^{_FRAME_STEM}\.({re.escape(extension)}|{IMAGE_EXTENSION})$",
    )
    keep = {path.name for path in sources} | {image_of(path).name for path in sources}
    for path in out_dir.iterdir():
        if path.is_file() and ours.match(path.name) and path.name not in keep:
            path.unlink()


def _index(frames: Sequence[Frame], extension: str, *, images: bool) -> str:
    """A page listing the frames in order — the album to leaf through."""
    lines = ["# Architecture history"]
    for frame in frames:
        commit = frame.commit
        lines += ["", f"## {frame.index:04d} · {commit.date} · `{commit.short}`"]
        lines += ["", commit.subject]
        names = [f"{frame.stem}.diff", frame.stem] if frame.previous else [frame.stem]
        for name in names:
            label = "What changed" if name.endswith(".diff") else "Diagram"
            if images:
                lines += ["", f"![{label}]({name}.{IMAGE_EXTENSION})"]
            else:
                lines += ["", f"[{label}]({name}.{extension})"]
    return "\n".join(lines)
