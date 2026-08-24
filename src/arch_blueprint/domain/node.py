from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class NodeKind(Enum):
    """The kind of entity a node represents in the blueprint graph."""

    MODULE = "module"


@dataclass(frozen=True)
class Node:
    """A single entity in the blueprint graph.

    A node is identified solely by ``id`` (its dotted, importable name), which
    keeps it hashable and lets metrics be stored alongside it without affecting
    equality. Grouping is deliberately absent: which group a node belongs to
    depends on the links, which do not exist yet when the extractor builds nodes.
    """

    id: str
    kind: NodeKind
