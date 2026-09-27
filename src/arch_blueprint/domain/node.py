from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # annotation only: typing_extensions is no runtime dependency
    from typing_extensions import Self


class NodeKind(Enum):
    """The kind of entity a node represents in the blueprint graph.

    Each member is its name in a snapshot (``value``) and the one ``letter``
    a diagram marks its nodes with (PlantUML's spot) — declared together, so a
    new kind cannot be drawn with another kind's mark.
    """

    _value_: str
    letter: str

    MODULE = ("module", "M")
    CLASS = ("class", "C")
    FUNCTION = ("function", "F")

    def __new__(cls, value: str, letter: str) -> Self:
        member = object.__new__(cls)
        member._value_ = value
        member.letter = letter
        return member

    @classmethod
    def named(cls, value: str) -> NodeKind:
        """The kind a snapshot names ``value``; ``ValueError`` for none.

        ``NodeKind(value)`` works too, but reads to a type checker as a call
        of ``__new__``, which takes the letter as well.
        """
        for kind in cls:
            if kind.value == value:
                return kind
        msg = f"{value!r} is not a valid {cls.__name__}"
        raise ValueError(msg)


@dataclass(frozen=True)
class Node:
    """A single entity in the blueprint graph.

    A node is identified solely by ``id`` (its dotted, importable name), which
    keeps it hashable and lets metrics be stored alongside it without affecting
    equality. Where it is drawn is deliberately absent: the frame a node sits
    in is the renderer's choice (``renderer/layout.py``) and depends on what
    that drawing shows, which the extractor building nodes does not know.
    """

    id: str
    kind: NodeKind
