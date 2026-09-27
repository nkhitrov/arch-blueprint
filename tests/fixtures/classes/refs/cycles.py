"""A pair of classes that refer to each other, and a ring of three."""

from __future__ import annotations


class Chicken:
    def lay(self) -> Egg:
        return Egg()


class Egg:
    def hatch(self) -> Chicken:
        return Chicken()


class Rock:
    def beats(self) -> Scissors:
        return Scissors()


class Scissors:
    def beats(self) -> Paper:
        return Paper()


class Paper:
    def beats(self) -> Rock:
        return Rock()
