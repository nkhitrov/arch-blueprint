"""Diagram sources to images, through the format's own tool found on ``PATH``.

One class per format, registered in ``IMAGE_RENDERERS``. The tool is looked up
before any work is done: a run that builds a whole history and only then finds
no ``plantuml`` has wasted that work.
"""

from __future__ import annotations

import os
import subprocess
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from types import MappingProxyType
from typing import ClassVar, Final, Optional

from arch_blueprint.history.album import Page, image_of
from arch_blueprint.history.cache import ImageCache


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

    @property
    def settings(self) -> str:
        """What besides the source decides the image: part of its cache key."""
        return "" if self.scale is None else f"scale={self.scale:g}"

    def _env(self) -> Optional[dict[str, str]]:
        """The tool's environment; ``None`` inherits ours unchanged."""
        return None

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
                env=self._env(),
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

    #: PlantUML crops an image at 4096 px by default — a large project's full
    #: diagram loses its right-hand side. The user's own setting wins.
    LIMIT_VARIABLE: ClassVar[str] = "PLANTUML_LIMIT_SIZE"
    DEFAULT_LIMIT: ClassVar[str] = "16384"

    @property
    def settings(self) -> str:
        return f"limit={self._limit()}"

    def _limit(self) -> str:
        return os.environ.get(self.LIMIT_VARIABLE, self.DEFAULT_LIMIT)

    def _env(self) -> Optional[dict[str, str]]:
        return {**os.environ, self.LIMIT_VARIABLE: self._limit()}

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


def draw(
    album: Sequence[Page],
    fmt: str,
    renderer: ImageRenderer,
    cache: ImageCache,
) -> tuple[dict[str, Optional[Path]], list[tuple[str, str]]]:
    """An image for every page, drawing only those the cache does not hold.

    Returns each page's cached image (``None`` where drawing failed) and the
    failures with their reasons. Sources are written to a temporary directory
    under the page's own name, so the tool's messages name the frame.
    """
    keys = {page.name: cache.key(fmt, renderer.settings, page.text) for page in album}
    missing = [page for page in album if cache.get(keys[page.name]) is None]
    failed: list[tuple[str, str]] = []
    if missing:
        with TemporaryDirectory(prefix="arch-blueprint-") as tmp:
            sources = []
            for page in missing:
                source = Path(tmp) / f"{page.name}.{fmt}"
                source.write_text(f"{page.text}\n", encoding="utf-8")
                sources.append(source)
            failed = [
                (source.stem, reason) for source, reason in renderer.render(sources)
            ]
            failed_names = {name for name, _ in failed}
            for source in sources:
                if source.stem not in failed_names:
                    cache.store(keys[source.stem], image_of(source))
    return {page.name: cache.get(keys[page.name]) for page in album}, failed
