"""The registered link levels: what a node is, what an arrow connects, how it is drawn.

A level is what ``--links`` names and a snapshot records. Kept apart from
``extract/levels.py`` because it names the extractors, and the module extractor
itself imports the endpoint functions defined there.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from arch_blueprint.domain.node import NodeKind
from arch_blueprint.extract.base import GraphExtractor
from arch_blueprint.extract.definition_extractor import DefinitionExtractor
from arch_blueprint.extract.levels import module_level, namespace_level
from arch_blueprint.extract.module_extractor import ModuleExtractor
from arch_blueprint.extract.source import GrimpSource


@dataclass(frozen=True)
class Level:
    """A registered link level: its extractor, and how a diagram draws its nodes.

    ``extractor`` builds the graph — what a node is, and the endpoints an edge
    aggregates on.

    ``nested`` draws nodes inside frames of the namespaces their dotted names
    spell — the module a class sits in, its package, and so on up, each chain
    of empty frames merged into one — so an arrow can end on a container. Off,
    every node is a flat box labelled by its name, less the prefix all names
    share: node-to-node arrows need no container, and routing them through the
    frames makes them long. The drawing is ``renderer/layout.py``'s.
    """

    extractor: Callable[[GrimpSource], GraphExtractor]
    nested: bool


#: What the class levels draw: classes and module-level functions, together —
#: a class that calls a function using another class depends on that class, and
#: only drawing the function shows it.
_DEFINITIONS: Final = frozenset({NodeKind.CLASS, NodeKind.FUNCTION})


LINK_LEVELS: Final[MappingProxyType[str, Level]] = MappingProxyType(
    {
        "namespace": Level(
            functools.partial(ModuleExtractor, level=namespace_level),
            nested=True,
        ),
        "module": Level(
            functools.partial(ModuleExtractor, level=module_level),
            nested=False,
        ),
        "class": Level(
            functools.partial(DefinitionExtractor, kinds=_DEFINITIONS),
            nested=False,
        ),
        "class-grouped": Level(
            functools.partial(DefinitionExtractor, kinds=_DEFINITIONS),
            nested=True,
        ),
    },
)

DEFAULT_LINK_LEVEL: Final = "namespace"
