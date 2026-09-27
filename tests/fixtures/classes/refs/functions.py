"""Module-level functions: nodes of their own, between the classes.

``Assembler`` calls ``build_widget``, which uses ``Widget``: the chain is
drawn through the function, ``Assembler -> build_widget -> Widget``.
``handle`` depends on a function by its decorator and a default, and on
``Widget`` through a string naming a module-level alias. ``label`` is a D2
keyword, quoted where a nested D2 key spells it.
"""


class Widget:
    """Used by a function."""


def build_widget() -> Widget:
    return Widget()


def label(widget: Widget) -> str:
    return type(widget).__name__


class Assembler:
    def run(self) -> None:
        label(build_widget())


WidgetType = Widget


def register(function: object) -> object:
    return function


@register
def handle(widget: "WidgetType", factory=build_widget) -> None:
    factory()
