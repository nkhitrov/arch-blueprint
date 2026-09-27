"""One class per way ``consumer.Consumer`` refers to a class, named after it.

Every class here but the ``NotBy...`` ones gets an arrow from ``Consumer``.
"""


class ByBase:
    """Consumer's base class."""


class ByMetaclass(type):
    """Consumer's metaclass."""


class ByDecorator:
    """Decorates Consumer."""

    def __init__(self, cls: type) -> None:
        self.cls = cls


class ByAnnotation:
    """A class-level annotation."""


class ByStringAnnotation:
    """A forward reference in quotes, imported only under TYPE_CHECKING."""


class ByInitParam:
    """A parameter of ``__init__``."""


class ByParam:
    """A parameter of another method."""


class ByReturn:
    """A method's return annotation."""


class ByBodyCall:
    """Instantiated in a method body."""


class ByLocalImport:
    """Imported inside a method."""


class ByAlias:
    """Imported under another name."""


class ByRelativeImport:
    """Imported with ``from .targets import``."""


class ByModuleAlias:
    """Reached as an attribute of an aliased module."""


class ByFactoryCall:
    """Reached through ``ByFactoryCall.create()``."""

    @classmethod
    def create(cls) -> "ByFactoryCall":
        return cls()


class ByNestedClass:
    """Referred to from a class nested in Consumer."""


class NotByShadowingParam:
    """Imported by consumer, but its name there is only ever a parameter."""


class ByModuleVariable:
    """Reached through a module-level alias, ``Alias = ByModuleVariable``."""


class ByTypeVarBound:
    """The bound of a ``TypeVar`` a method is generic in."""


class ByRegistry:
    """A value in a module-level dict a method looks up."""


class ByCastString:
    """Named in ``cast("ByCastString", ...)``."""


class ByMatchPattern:
    """A class pattern: ``case ByMatchPattern():``."""


class ByExcept:
    """Caught in an ``except`` clause."""


class NotByMatchCapture:
    """Imported by consumer, but its name there is only ever a match capture."""
