"""Link levels: which pair of names an import edge aggregates on.

An :class:`~arch_blueprint.domain.graph.Edge` keeps the real importer and the
real imported module; its namespaces are only the key links, cycles, groups and
link metrics are built on. A level chooses that key, so switching between
namespace arrows and module-to-module arrows changes nothing downstream.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from types import MappingProxyType
from typing import Final, Optional

from arch_blueprint.extract.base import common_depth_namespaces

#: ``(importer node, imported module, node ids) -> (source key, target key)``,
#: or ``None`` when the edge is internal at this level and draws nothing.
LinkLevel = Callable[[str, str, frozenset[str]], Optional[tuple[str, str]]]


def ancestors(module: str) -> Iterator[str]:
    """Every dotted prefix of ``module``, longest first, excluding itself."""
    cutoff = module.rfind(".")
    while cutoff != -1:
        module = module[:cutoff]
        yield module
        cutoff = module.rfind(".")


def namespace_level(
    source: str,
    target: str,
    nodes: frozenset[str],
) -> Optional[tuple[str, str]]:
    """Both names cut where they diverge: ``a.b.c → a.d.e`` is ``a.b → a.d``."""
    source_ns, target_ns = common_depth_namespaces(source, target)
    return None if source_ns == target_ns else (source_ns, target_ns)


def module_level(
    source: str,
    target: str,
    nodes: frozenset[str],
) -> Optional[tuple[str, str]]:
    """Node to node: ``a.b.c → a.d.e`` stays ``a.b.c → a.d.e``.

    The target is the node the import lands in — itself, or the selected package
    it lies under, since an arrow must point at something drawn. A package facade
    above the nodes stays as it is: it is drawn as their container. An import of
    the source itself or of a package it lies in draws nothing, as at the
    namespace level.
    """
    resolved = target
    if target not in nodes:
        resolved = next((name for name in ancestors(target) if name in nodes), target)
    if resolved == source or source.startswith(f"{resolved}."):
        return None
    return source, resolved


LINK_LEVELS: Final[MappingProxyType[str, LinkLevel]] = MappingProxyType(
    {
        "namespace": namespace_level,
        "module": module_level,
    },
)

DEFAULT_LINK_LEVEL: Final = "namespace"
