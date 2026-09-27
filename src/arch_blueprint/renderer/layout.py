"""Where a drawing puts each name and what it labels it: the frames and the title.

A drawing names things by their dotted ids, and most of every id is noise
repeated on every box. Nested (``Level.nested``), each dotted prefix is a frame
around the names under it — and a deep project opens with a staircase of frames
that each hold nothing but the next one (``app`` → ``features`` → ``core``).
Such a chain is merged into one frame labelled by the joined path
(``app.features.core``). Flat, every box is labelled by its full name, and the
prefix every name shares is stripped from each label and shown once, as the
diagram's title.

Worked out once per drawing by :meth:`Layout.build`, from what is drawn — a
plain diagram's nodes and link endpoints, or a diff's — so a diagram and a diff
of a graph with itself lay out alike. Ids never change: arrows, snapshots and
diffs name the same things whatever the labels read.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, field
from typing import Union


@dataclass(frozen=True)
class Frame:
    """One drawn container: its full name, its label, and what it holds.

    ``namespace`` is the full dotted name — what an arrow ending on the frame
    names. ``label`` is that name relative to the enclosing frame: its own last
    part, or a merged chain's joined path. ``items`` are names and child
    frames, in the order the nodes are drawn.
    """

    namespace: str
    label: str
    items: tuple[LayoutItem, ...]


#: What a frame, or the top level of a drawing, holds: a drawn name or a frame.
LayoutItem = Union[str, Frame]


def _identity(name: str) -> str:
    return name


@dataclass(frozen=True)
class Layout:
    """Every frame of a drawing as a tree, and how each drawn name is labelled.

    ``items`` is the top level: the names under no frame, and the outermost
    frames. Flat, there are no frames: ``items`` are the names to declare in
    order — nodes, and the endpoints no node carries (package facades), each
    before the first node under it — and ``prefix`` is what every label drops,
    shown once as the ``title``. Nested, ``prefix`` is empty: the outermost
    frame's label already says it.
    """

    items: tuple[LayoutItem, ...] = ()
    prefix: str = ""
    _namespaces: frozenset[str] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        namespaces: set[str] = set()
        pending = list(self.items)
        while pending:
            item = pending.pop()
            if isinstance(item, Frame):
                namespaces.add(item.namespace)
                pending.extend(item.items)
        object.__setattr__(self, "_namespaces", frozenset(namespaces))

    @property
    def title(self) -> str:
        """What the diagram is headed with: the stripped prefix ('' for none)."""
        return self.prefix

    def path(self, name: str) -> tuple[str, ...]:
        """``name`` split at its frames: each enclosing frame's label, then its own.

        ``app.features.core.usecases.Run`` inside a merged frame
        ``app.features.core`` and a frame ``usecases`` is
        ``("app.features.core", "usecases", "Run")``. The last part holds a dot
        only where no frame splits it — always, when flat.
        """
        parts = name.split(".")
        path: list[str] = []
        start = 0
        for end in range(1, len(parts)):
            if ".".join(parts[:end]) in self._namespaces:
                path.append(".".join(parts[start:end]))
                start = end
        path.append(".".join(parts[start:]))
        return tuple(path)

    def label(self, name: str) -> str:
        """What ``name`` is labelled: its last part in a frame, less the prefix."""
        if self.prefix and name.startswith(f"{self.prefix}."):
            return name[len(self.prefix) + 1 :]
        return self.path(name)[-1]

    @staticmethod
    def build(
        node_ids: Sequence[str],
        endpoints: Collection[str],
        *,
        nested: bool,
        base: Callable[[str], str] = _identity,
    ) -> Layout:
        """The layout of ``node_ids`` (in drawing order) and arrow ``endpoints``.

        ``base`` gives the name a drawn id stands for, where they differ (a
        diff's shadowed module): the flat prefix is worked out on those.
        """
        if nested:
            return _nested(node_ids, endpoints)
        return _flat(node_ids, endpoints, base)


def _nested(node_ids: Sequence[str], endpoints: Collection[str]) -> Layout:
    """Frame every dotted prefix, merging each chain of frames that hold nothing.

    A prefix that is a node is no frame: the node is already declared, and a
    container of its own name is a PlantUML syntax error. A frame is merged
    into its one child frame when it holds no node, has no other child, and is
    no arrow's endpoint: an arrow ending on it needs it drawn. Merging repeats
    up the chain, so a chain of any length becomes one frame labelled by the
    joined path. A frame holding a node, or two frames, stays.
    """
    order = {node_id: index for index, node_id in enumerate(node_ids)}
    names = [*order, *(end for end in endpoints if end not in order)]
    candidates = {prefix for name in names for prefix in _proper_prefixes(name)}
    candidates |= set(endpoints)
    candidates -= order.keys()

    children: dict[str, int] = dict.fromkeys(candidates, 0)
    for frame in candidates:
        parent = _deepest(frame, candidates)
        if parent is not None:
            children[parent] += 1
    holds_node = {_deepest(node_id, candidates) for node_id in order}
    kept = {
        frame
        for frame in candidates
        if frame in endpoints or frame in holds_node or children[frame] != 1
    }
    return Layout(items=_tree(order, kept))


def _tree(order: dict[str, int], kept: Collection[str]) -> tuple[LayoutItem, ...]:
    """The frames ``kept`` as a tree holding the nodes of ``order``.

    An item sits where its first node is drawn; a frame with no node under it
    (an endpoint only) goes after every one that has.
    """
    last = len(order)
    parent_of = {frame: _deepest(frame, kept) for frame in kept}
    first = dict.fromkeys(kept, last)
    held: dict[str | None, list[tuple[int, str]]] = {}
    for node_id, index in order.items():
        owner = _deepest(node_id, kept)
        held.setdefault(owner, []).append((index, node_id))
        while owner is not None and first[owner] > index:
            first[owner] = index
            owner = parent_of[owner]
    subframes: dict[str | None, list[str]] = {}
    for frame, parent in parent_of.items():
        subframes.setdefault(parent, []).append(frame)

    def items(parent: str | None) -> tuple[LayoutItem, ...]:
        placed: list[tuple[int, str, LayoutItem]] = [
            (index, node_id, node_id) for index, node_id in held.get(parent, [])
        ]
        for frame in subframes.get(parent, []):
            label = frame if parent is None else frame[len(parent) + 1 :]
            placed.append((first[frame], frame, Frame(frame, label, items(frame))))
        return tuple(item for _, _, item in sorted(placed, key=lambda p: p[:2]))

    return items(None)


def _flat(
    node_ids: Sequence[str],
    endpoints: Collection[str],
    base: Callable[[str], str],
) -> Layout:
    """Every node, plus each endpoint no node carries, under one shared prefix.

    Flat, nothing contains anything, so a package an arrow ends on (its facade,
    ``__init__.py``) is declared as a node of its own. It goes before the first
    node under it, shallower first — where its container would have been — and
    last when no drawn node lies under it.
    """
    facades = sorted(set(endpoints) - set(node_ids))
    items: list[str] = []
    placed: set[str] = set()
    for node_id in node_ids:
        for facade in facades:  # sorted: a prefix before the names under it
            if facade not in placed and node_id.startswith(f"{facade}."):
                placed.add(facade)
                items.append(facade)
        items.append(node_id)
    items += [facade for facade in facades if facade not in placed]
    return Layout(items=tuple(items), prefix=common_prefix([base(i) for i in items]))


def common_prefix(names: Sequence[str]) -> str:
    """The dotted prefix every name shares, in whole parts, leaving each a label.

    ``a.b.c`` and ``a.b.d`` share ``a.b``; ``a.b`` and ``a.b.c`` share only
    ``a``, since ``a.b`` stripped of ``a.b`` is nothing; a lone ``a.b.c`` keeps
    ``c``. Names that differ in their first part share nothing.
    """
    if not names:
        return ""
    split = [name.split(".") for name in names]
    shared: list[str] = []
    for parts in zip(*split):
        if len(set(parts)) != 1:
            break
        shared.append(parts[0])
    shortest = min(len(parts) for parts in split)
    return ".".join(shared[: min(len(shared), shortest - 1)])


def _proper_prefixes(name: str) -> list[str]:
    parts = name.split(".")
    return [".".join(parts[:end]) for end in range(1, len(parts))]


def _deepest(name: str, frames: Collection[str]) -> str | None:
    """The longest of ``frames`` that ``name`` lies under, if any."""
    for prefix in reversed(_proper_prefixes(name)):
        if prefix in frames:
            return prefix
    return None
