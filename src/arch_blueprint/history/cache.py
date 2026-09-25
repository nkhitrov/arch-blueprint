"""Snapshots kept on disk between runs, so a failed image render costs no rebuild.

A snapshot is a function of the project's tree and the ``-m`` patterns, so the
git tree id is the key: two commits that leave the project alone share one
entry, and a rerun over the same history builds nothing.
"""

from __future__ import annotations

import hashlib
import json
import os
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


class SnapshotCache:
    """Snapshot texts under ``<root>/snapshots/<key>.json``."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._dir = root / "snapshots"

    @staticmethod
    def key(tree: str, patterns: Sequence[str]) -> str:
        """The entry for a project tree graphed with ``patterns``.

        The versions are part of it: another snapshot format, or another
        release's extractor, may make another graph from the same tree.
        """
        material = json.dumps(
            [tree, sorted(patterns), SNAPSHOT_VERSION, _tool_version()],
        )
        return hashlib.sha256(material.encode()).hexdigest()

    def get(self, key: str) -> Optional[str]:
        try:
            return (self._dir / f"{key}.json").read_text(encoding="utf-8")
        except FileNotFoundError:
            return None

    def put(self, key: str, text: str) -> None:
        """Store an entry atomically: an interrupted run leaves no half of one."""
        self._ensure_dir()
        path = self._dir / f"{key}.json"
        partial = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        partial.write_text(text, encoding="utf-8")
        partial.replace(path)

    def _ensure_dir(self) -> None:
        if self._dir.is_dir():
            return
        self._dir.mkdir(parents=True, exist_ok=True)
        # The cache is made where the tool runs — usually inside a repository.
        ignore = self.root / ".gitignore"
        if not ignore.exists():
            ignore.write_text("# Created by arch-blueprint.\n*\n", encoding="utf-8")
