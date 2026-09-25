"""Diagram sources to images, through the format's own tool found on ``PATH``.

One class per format, registered in ``IMAGE_RENDERERS``. The tool is looked up
before any work is done: a run that builds a whole history and only then finds
no ``plantuml`` has wasted that work.
"""

from __future__ import annotations

import subprocess
from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path
from types import MappingProxyType
from typing import ClassVar, Final

from arch_blueprint.history.album import image_of


class ImageRenderer(ABC):
    """Draw images next to their diagram sources with an external tool."""

    #: The executable looked up on ``PATH``.
    binary: ClassVar[str]

    def __init__(self, executable: str) -> None:
        self.executable = executable

    @abstractmethod
    def render(self, sources: Sequence[Path]) -> list[tuple[Path, str]]:
        """Draw every source; return the ones that failed, each with a reason.

        A failed source has no image afterwards — a half-written or error image
        would pass for a drawn frame on the next run.
        """

    def _run(self, *args: str) -> str:
        """Run the tool; the empty string on success, its complaint otherwise."""
        try:
            # The user's own tool from PATH, fed our own generated files.
            result = subprocess.run(  # noqa: S603
                [self.executable, *args],
                capture_output=True,
                check=False,
            )
        except OSError as error:
            return str(error)
        if result.returncode == 0:
            return ""
        output = (result.stderr or result.stdout).decode(errors="replace").strip()
        return output.splitlines()[-1] if output else f"exit {result.returncode}"


class PlantUmlImages(ImageRenderer):
    """``plantuml -tpng``: one JVM for the whole batch, file by file on failure.

    PlantUML draws an error picture for a broken diagram and reports only the
    batch's exit code, so a failed batch is redone per file to learn which.
    """

    binary = "plantuml"

    def render(self, sources: Sequence[Path]) -> list[tuple[Path, str]]:
        if not sources or not self._run("-tpng", *map(str, sources)):
            return []
        failed = []
        for source in sources:
            reason = self._run("-tpng", str(source))
            if reason:
                image_of(source).unlink(missing_ok=True)
                failed.append((source, reason))
        return failed


class D2Images(ImageRenderer):
    """``d2 SOURCE IMAGE``, one file at a time."""

    binary = "d2"

    def render(self, sources: Sequence[Path]) -> list[tuple[Path, str]]:
        failed = []
        for source in sources:
            reason = self._run(str(source), str(image_of(source)))
            if reason:
                image_of(source).unlink(missing_ok=True)
                failed.append((source, reason))
        return failed


#: One image renderer per diagram format, keyed like the CLI's renderers.
IMAGE_RENDERERS: Final[MappingProxyType[str, type[ImageRenderer]]] = MappingProxyType(
    {
        "puml": PlantUmlImages,
        "d2": D2Images,
    },
)
