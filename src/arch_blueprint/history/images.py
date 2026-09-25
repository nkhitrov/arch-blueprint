"""Diagram sources to images, through the format's own tool found on ``PATH``.

One class per format, registered in ``IMAGE_RENDERERS``. The tool is looked up
before any work is done: a run that builds a whole history and only then finds
no ``plantuml`` has wasted that work.
"""

from __future__ import annotations

import subprocess
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import ClassVar, Final, Optional

from arch_blueprint.history.album import image_of


class ImageRenderer(ABC):
    """Draw images next to their diagram sources with an external tool."""

    #: The executable looked up on ``PATH``.
    binary: ClassVar[str]
    #: Whether the tool takes an output scale (``--scale``).
    scalable: ClassVar[bool] = False

    def __init__(
        self,
        executable: str,
        scale: Optional[float] = None,
        report: Optional[Callable[[str], None]] = None,
    ) -> None:
        """``report`` receives a line about anything worth telling the user."""
        if scale is not None and not self.scalable:
            msg = f"{self.binary} images take no scale"
            raise ValueError(msg)
        self.executable = executable
        self.scale = scale
        self._report = report

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
    """``d2 [--scale S] SOURCE IMAGE``, one file at a time.

    d2 refuses to rasterize past a fixed amount of work, which a large project's
    full diagram exceeds at the default size. Such a diagram is redrawn at half
    the scale, and half again, rather than left without an image.
    """

    binary = "d2"
    scalable = True

    #: How many times a too-large diagram is halved before giving up.
    HALVINGS: ClassVar[int] = 3
    _TOO_LARGE: ClassVar[str] = "exceeds limit"

    def render(self, sources: Sequence[Path]) -> list[tuple[Path, str]]:
        failed = []
        for source in sources:
            reason = self._draw(source)
            if reason:
                image_of(source).unlink(missing_ok=True)
                failed.append((source, reason))
        return failed

    def _draw(self, source: Path) -> str:
        reason = self._run(
            *self._scale_args(self.scale),
            str(source),
            str(image_of(source)),
        )
        scale = 1.0 if self.scale is None else self.scale
        for _ in range(self.HALVINGS):
            if self._TOO_LARGE not in reason:
                break
            scale /= 2
            reason = self._run(
                *self._scale_args(scale),
                str(source),
                str(image_of(source)),
            )
            if not reason and self._report is not None:
                self._report(
                    f"{source.name}: too large for d2, drawn at scale {scale:g}",
                )
        return reason

    @staticmethod
    def _scale_args(scale: Optional[float]) -> list[str]:
        return [] if scale is None else [f"--scale={scale:g}"]


#: One image renderer per diagram format, keyed like the CLI's renderers.
IMAGE_RENDERERS: Final[MappingProxyType[str, type[ImageRenderer]]] = MappingProxyType(
    {
        "puml": PlantUmlImages,
        "d2": D2Images,
    },
)
