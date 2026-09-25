"""An album of a project's history: one frame per commit that changed its graph.

Each frame is the full diagram at that commit plus, from the second frame on,
the diff against the frame before it. Files are numbered so that sorting by name
is chronological; the date and short sha in the name are for the reader.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
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
class Page:
    """One diagram of the album: a frame's full diagram, or its diff."""

    #: The file name without its extension.
    name: str
    #: The diagram source.
    text: str


def pages(
    frames: Sequence[Frame],
    draw: Callable[[Snapshot], str],
    draw_diff: Callable[[Snapshot, Snapshot], str],
) -> list[Page]:
    """Every frame's diagrams in album order: the diff first, then the result."""
    result = []
    for frame in frames:
        if frame.previous is not None:
            text = draw_diff(frame.previous, frame.snapshot)
            result.append(Page(f"{frame.stem}.diff", text))
        result.append(Page(frame.stem, draw(frame.snapshot)))
    return result


def write(
    frames: Sequence[Frame],
    album: Sequence[Page],
    out_dir: Path,
    extension: str,
    images: Optional[Mapping[str, Optional[Path]]] = None,
) -> None:
    """Write the album's sources — or, given ``images``, only its images — and index.

    ``images`` maps a page name to its drawn image, ``None`` where drawing
    failed: that frame is left without a file rather than with a stale one. A
    file whose content is unchanged is not rewritten. Frame files of this
    extension that this run did not produce are removed.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    for page in album:
        path = out_dir / f"{page.name}.{extension}"
        if images is None:
            _write_if_changed(path, f"{page.text}\n".encode())
            continue
        image = images[page.name]
        if image is None:
            path.unlink(missing_ok=True)
        else:
            _write_if_changed(path, image.read_bytes())
    index = _index(frames, extension, images=images is not None)
    _write_if_changed(out_dir / INDEX_NAME, f"{index}\n".encode())
    _remove_stale(out_dir, album, extension)


def image_of(source: Path) -> Path:
    """Where an image tool draws a diagram: next to it, same name."""
    return source.with_name(f"{source.stem}.{IMAGE_EXTENSION}")


def _write_if_changed(path: Path, content: bytes) -> None:
    """Replace ``path`` atomically, and only when its bytes would change."""
    try:
        if path.read_bytes() == content:
            return
    except FileNotFoundError:
        pass
    partial = path.with_name(f".{path.name}.tmp")
    partial.write_bytes(content)
    partial.replace(path)


def _remove_stale(out_dir: Path, album: Sequence[Page], extension: str) -> None:
    """Remove frame files this run did not produce — a shorter or other range.

    Only this run's extension: an album of another kind in the same directory
    is left alone (though a png album of the other format shares its names).
    """
    ours = re.compile(rf"^{_FRAME_STEM}\.{re.escape(extension)}$")
    keep = {f"{page.name}.{extension}" for page in album}
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
            link = f"[{label}]({name}.{extension})"
            lines += ["", f"!{link}" if images else link]
    return "\n".join(lines)
