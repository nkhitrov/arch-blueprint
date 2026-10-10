"""``--deps``: what is drawn beside the ``-m`` selection, the focus.

Without it a diagram holds the selection alone, and an import of anything
outside it draws nothing. With it the selection is the focus, and the objects
next to it are drawn too — as neighbors (``BlueprintGraph.neighbors``), set
apart from it. The direction only picks *which* objects are neighbors: every
edge between the focus and a neighbor is drawn, whichever way it runs, so a
cycle through a neighbor is never half hidden. An edge between two neighbors
never is — only the focus's own dependencies are read.
"""

from __future__ import annotations

from typing import Final, Optional

#: ``--deps`` values. ``out``: what the focus depends on. ``in``: what depends
#: on the focus. ``both``: either.
DEPS_DIRECTIONS: Final = ("out", "in", "both")


def follows_out(deps: Optional[str]) -> bool:
    """Whether what the focus depends on is drawn."""
    return deps in {"out", "both"}


def follows_in(deps: Optional[str]) -> bool:
    """Whether what depends on the focus is drawn."""
    return deps in {"in", "both"}
