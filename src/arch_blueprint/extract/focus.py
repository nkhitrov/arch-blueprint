"""``--deps``: what is drawn beside the ``-m`` selection, the focus.

Without it a diagram holds the selection alone, and an import of anything
outside it draws nothing. With it the selection is the focus, and the objects
it depends on are drawn too — as neighbors (``BlueprintGraph.neighbors``),
set apart from it.
"""

from __future__ import annotations

from typing import Final

#: ``--deps`` values. ``out``: what the focus depends on.
DEPS_DIRECTIONS: Final = ("out",)
