"""Snapshots kept on disk between runs, so a failed image render costs no rebuild.

A snapshot is a function of the project's tree, the ``-m`` patterns and the link
level, so the git tree id is the key: two commits that leave the project alone
share one entry, and a rerun over the same history builds nothing.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Sequence
from importlib import metadata
from pathlib import Path
from typing import Final, Optional

from arch_blueprint.snapshot import SNAPSHOT_VERSION

#: What ``history`` uses when no ``--cache-dir`` is given, relative to the cwd.
DEFAULT_CACHE_DIR: Final = ".arch-blueprint"


def _tool_version() -> str:
    try:
        return metadata.version("arch-blueprint")
    except metadata.PackageNotFoundError:  # pragma: no cover - run from source
        return "unknown"


def _make_dir(root: Path, name: str) -> Path:
    """``<root>/<name>``, created with a ``.gitignore`` of ``*`` in ``root``.

    The cache is made where the tool runs — usually inside a repository.
    """
    directory = root / name
    if not directory.is_dir():
        directory.mkdir(parents=True, exist_ok=True)
        ignore = root / ".gitignore"
        if not ignore.exists():
            ignore.write_text("# Created by arch-blueprint.\n*\n", encoding="utf-8")
    return directory


class SnapshotCache:
    """Snapshot texts under ``<root>/snapshots/<key>.json``."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._dir = root / "snapshots"

    @staticmethod
    def key(tree: str, patterns: Sequence[str], links: str) -> str:
        """The entry for a project tree graphed with ``patterns`` at ``links`` level.

        The versions are part of it: another snapshot format, or another
        release's extractor, may make another graph from the same tree.
        """
        material = json.dumps(
            [tree, sorted(patterns), links, SNAPSHOT_VERSION, _tool_version()],
        )
        return hashlib.sha256(material.encode()).hexdigest()

    def get(self, key: str) -> Optional[str]:
        try:
            return (self._dir / f"{key}.json").read_text(encoding="utf-8")
        except FileNotFoundError:
            return None

    def put(self, key: str, text: str) -> None:
        """Store an entry atomically: an interrupted run leaves no half of one."""
        path = _make_dir(self.root, "snapshots") / f"{key}.json"
        partial = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        partial.write_text(text, encoding="utf-8")
        partial.replace(path)


class ImageCache:
    """Drawn images under ``<root>/images/<key>.png``, keyed by what they show.

    The key is the diagram source itself (with the tool and its settings), so an
    image is drawn once for all runs, albums and frames that show the same
    thing, and a rerun after a failure draws only what is still missing.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    @staticmethod
    def key(fmt: str, settings: str, source: str) -> str:
        """The entry for ``source`` drawn as ``fmt`` with the tool's ``settings``."""
        material = json.dumps([fmt, settings, source])
        return hashlib.sha256(material.encode()).hexdigest()

    def get(self, key: str) -> Optional[Path]:
        path = self.root / "images" / f"{key}.png"
        return path if path.is_file() else None

    def store(self, key: str, drawn: Path) -> Path:
        """Copy a freshly drawn image in, atomically: no half image is ever cached."""
        path = _make_dir(self.root, "images") / f"{key}.png"
        partial = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        shutil.copyfile(drawn, partial)
        partial.replace(path)
        return path
