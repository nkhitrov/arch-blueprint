from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class NodeKind(Enum):
    """The kind of entity a node represents in the blueprint graph."""

    MODULE = "module"
    CLASS = "class"


@dataclass(frozen=True)
class Node:
    """A single entity in the blueprint graph (a module or a class).

    A node is identified solely by ``id`` (its dotted, importable name), which
    keeps it hashable and lets metrics be stored alongside it without affecting
    equality. ``namespace`` is assigned by the extractor rather than derived from
    ``id`` so that different node kinds can group differently (e.g. a class groups
    under its defining module).
    """

    id: str
    kind: NodeKind
    namespace: str
