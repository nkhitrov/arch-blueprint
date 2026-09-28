from __future__ import annotations

from collections.abc import Collection
from typing import TYPE_CHECKING, Final, Optional

from arch_blueprint.domain.graph import BlueprintGraph, Edge
from arch_blueprint.domain.node import Node, NodeKind
from arch_blueprint.extract.levels import ancestors
from arch_blueprint.extract.source import GrimpSource

if TYPE_CHECKING:
    from arch_blueprint.extract.symbols import SymbolIndex

#: Inserted into the id of a definition in a package's ``__init__.py`` that is
#: named like one of the package's modules: ``pkg.mod`` would otherwise be both
#: a box and the frame of the definitions in ``pkg/mod.py``.
FACADE_MODULE: Final = "__init__"


def _id(node: Node) -> str:
    return node.id


class DefinitionExtractor:
    """Extracts a graph whose nodes are definitions — classes, functions — not modules.

    ``kinds`` names what becomes a node: the top-level definitions of those
    kinds in every module a pattern matches, every module below it, and the
    package a ``pkg.*`` pattern selects the insides of (its ``__init__.py``).
    An edge runs from a node to each other node its code refers to anywhere
    (see ``extract/symbols.py``), always node to node, so both endpoints are
    the definitions themselves.

    A reference to a definition of a kind outside ``kinds`` draws nothing and is
    not followed.

    A node id is the definition's dotted path, ``pkg.mod.Foo``. No node lies
    under another, as at the module levels: a definition in ``pkg/__init__.py``
    named like a module of ``pkg`` is ``pkg.__init__.mod``, since ``pkg.mod``
    names the frame of that module's own definitions.

    No ``facade_edges``: a name a package facade re-exports is followed to where
    it is defined, so no cycle runs through a facade unseen.

    With ``--deps`` (``source.deps``), a definition of those kinds that a node
    refers to but no pattern selects is a neighbor node, wherever in the
    project it is defined. Only the focus's references are followed: a
    neighbor has no edges of its own.
    """

    def __init__(self, source: GrimpSource, kinds: Collection[NodeKind]) -> None:
        self.source = source
        self.kinds = frozenset(kinds)

    def extract(self) -> BlueprintGraph:
        # Imported here, not at the top: libcst is only needed at these levels,
        # and a module in ``sys.modules`` is what ``find_spec`` finds first — a
        # project named ``libcst`` would be drawn as the installed copy.
        from arch_blueprint.extract.symbols import SymbolIndex  # noqa: PLC0415

        index = SymbolIndex(self.source)
        modules = sorted(
            {
                module
                for matched in self.source.matching_modules()
                for module in self.source.modules_under(matched)
            }
            | set(self.source.pattern_stems()),
        )
        owned: dict[str, frozenset[str]] = {}
        kinds: dict[str, NodeKind] = {}
        for module in modules:
            symbols = index.symbols(module)
            if symbols is None:
                continue
            for name, kind in symbols.definitions.items():
                if kind in self.kinds:
                    kinds[name] = kind
                    owned[name] = symbols.references[name]
        outside: dict[str, NodeKind] = {}
        if self.source.deps is not None:
            for references in owned.values():
                for reference in references:
                    for target in index.resolve(reference):
                        found = self._kind_of(index, target)
                        if target not in kinds and found in self.kinds:
                            outside[target] = found
        ids = self._node_ids({**kinds, **outside})
        # Sorted by id, as module nodes are: renderers declare nodes in graph
        # order and a diff in id order, and both must declare them alike for
        # a diff of a graph with itself to lay out as its plain diagram. The
        # focus first, then its neighbors, as at the module levels.
        nodes = [
            *sorted((Node(ids[name], kind) for name, kind in kinds.items()), key=_id),
            *sorted((Node(ids[name], kind) for name, kind in outside.items()), key=_id),
        ]
        neighbors = frozenset(ids[name] for name in outside)

        edges = {
            Edge(
                source=ids[name],
                target=ids[target],
                source_endpoint=ids[name],
                target_endpoint=ids[target],
            )
            for name, references in owned.items()
            for reference in references
            for target in index.resolve(reference)
            if target != name and target in ids
        }
        return BlueprintGraph(
            nodes=nodes,
            edges=frozenset(edges),
            neighbors=neighbors,
        )

    @staticmethod
    def _kind_of(index: SymbolIndex, definition: str) -> Optional[NodeKind]:
        """What ``definition`` is — a top-level one, so its module is its parent."""
        symbols = index.symbols(definition.rpartition(".")[0])
        return None if symbols is None else symbols.definitions.get(definition)

    def _node_ids(self, definitions: Collection[str]) -> dict[str, str]:
        """Each definition's node id: its name, unless a module is named alike."""
        taken = set(self.source.graph.modules)
        taken.update(parent for name in definitions for parent in ancestors(name))
        ids: dict[str, str] = {}
        for name in definitions:
            if name in taken:
                module, _, short = name.rpartition(".")
                ids[name] = f"{module}.{FACADE_MODULE}.{short}"
            else:
                ids[name] = name
        return ids
