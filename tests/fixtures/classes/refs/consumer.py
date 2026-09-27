"""A class that refers to one class of ``targets`` per construct.

The four places a reference counts: the declarative part (bases, metaclass,
decorators, class-level annotations), ``__init__``, method signatures, and
method bodies — and a module-level variable standing for a class: an alias, a
``TypeVar``'s bound, a registry.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar, cast

import refs.targets as targets_module
from refs.exported import ByReExport
from refs.targets import (
    ByAnnotation,
    ByBase,
    ByBodyCall,
    ByDecorator,
    ByExcept,
    ByFactoryCall,
    ByInitParam,
    ByMatchPattern,
    ByMetaclass,
    ByModuleVariable,
    ByNestedClass,
    ByParam,
    ByRegistry,
    ByReturn,
    NotByMatchCapture,
    NotByShadowingParam,
)
from refs.targets import ByAlias as Aliased

from .targets import ByRelativeImport

if TYPE_CHECKING:
    from refs.targets import ByCastString, ByStringAnnotation, ByTypeVarBound

Alias = ByModuleVariable
Item = TypeVar("Item", bound="ByTypeVarBound")
REGISTRY = {"key": ByRegistry}


@ByDecorator
class Consumer(ByBase, metaclass=ByMetaclass):
    annotated: ByAnnotation
    exported: ByReExport

    class Inner:
        nested: ByNestedClass

    def __init__(self, init_param: ByInitParam) -> None:
        self.init_param = init_param

    def signature(self, param: ByParam) -> ByReturn:
        return ByReturn()

    def forward(self) -> "ByStringAnnotation":
        raise NotImplementedError

    def body(self) -> None:
        ByBodyCall()
        Aliased()
        ByRelativeImport()
        targets_module.ByModuleAlias()
        ByFactoryCall.create()

    def local_import(self) -> None:
        from refs.targets import ByLocalImport

        ByLocalImport()

    def shadowing(self, NotByShadowingParam: int) -> int:
        # The parameter shadows the import: no arrow to the class.
        return NotByShadowingParam

    def through_module_variables(self, item: Item) -> Item:
        Alias()
        return REGISTRY["key"]()

    def statements(self, obj: object) -> object:
        try:
            match obj:
                case ByMatchPattern():
                    return cast("ByCastString", obj)
                case [NotByMatchCapture]:
                    # A capture binds the name: no arrow to the class.
                    return NotByMatchCapture
        except ByExcept:
            pass
        return None

    def clone(self) -> Consumer:
        # A reference to itself: no arrow.
        return Consumer(ByInitParam())
