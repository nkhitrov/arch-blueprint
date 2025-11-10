from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Optional, final

from arch_blueprint.modules import BlueprintModule


@dataclass(frozen=True)
@final
class RendererOptions:
    """
    Shared options for all renderers.

    Args:
        depth_colors:
            list of colors in hex format (with #) for different
            depths of elements.
    """

    depth_colors: Sequence[str]


DEFAULT_OPTIONS: Final = RendererOptions(
    depth_colors=[
        "#E74C3C",
        "#3498DB",
        "#2ECC71",
        "#1ABC9C",
        "#F39C12",
        "#9B59B6",
        "#27AE60",
        "#34495E",
        "#E67E22",
        "#8E44AD",
    ],
)


class BlueprintRenderer(ABC):
    """ABC used for all available renderers."""

    def __init__(self, options: Optional[RendererOptions] = None) -> None:
        self.options = options or DEFAULT_OPTIONS

    @abstractmethod
    def render(self, target_modules: list[BlueprintModule]) -> str:
        """Render a blueprint to source code."""
        raise NotImplementedError

    def get_color_for_depth(self, depth: int) -> str:
        return self.options.depth_colors[
            depth % len(self.options.depth_colors)
            # avoid IndexError by looping back to first color
        ]
