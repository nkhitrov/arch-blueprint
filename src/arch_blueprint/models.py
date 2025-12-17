from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModuleEdge:
    """A single module-to-module dependency with namespace context."""

    source_module: str
    target_module: str
    source_namespace: str
    target_namespace: str


@dataclass(frozen=True)
class NamespaceLink:
    """Aggregated namespace-level link with contributing module edges."""

    source_namespace: str
    target_namespace: str
    edges: frozenset[ModuleEdge]


@dataclass(frozen=True)
class CyclicDependency:
    """Bidirectional dependency between namespaces with edges for both directions."""

    namespace_from: str
    namespace_to: str
    forward_edges: frozenset[ModuleEdge]
    backward_edges: frozenset[ModuleEdge]
