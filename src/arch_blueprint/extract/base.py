from __future__ import annotations

from typing import Protocol, runtime_checkable

from arch_blueprint.domain.graph import BlueprintGraph
from arch_blueprint.extract.source import GrimpSource


@runtime_checkable
class GraphExtractor(Protocol):
    """Turns a grimp source into a renderable :class:`BlueprintGraph`.

    Implementations decide what a node is (a module, a class, ...) and how edges
    between nodes are derived, while sharing the same downstream link/cycle/metric
    pipeline.
    """

    def __init__(self, source: GrimpSource) -> None: ...

    def extract(self) -> BlueprintGraph:
        """Build the graph of nodes and edges for the selected targets."""
        ...


def parent_namespace(module: str) -> str:
    """The dotted parent of a module, or the module itself when top-level."""
    if "." not in module:
        return module
    namespace, _ = module.rsplit(".", maxsplit=1)
    return namespace


def common_depth_namespaces(source: str, target: str) -> tuple[str, str]:
    """Split two dotted names at their first differing component.

    e.g. ``("app2.service", "app1.models")`` -> ``("app2", "app1")``; this is the
    namespace pair an edge between them aggregates on.
    """
    source_parts = source.split(".")
    target_parts = target.split(".")

    path_source: list[str] = []
    path_target: list[str] = []
    for first, second in zip(source_parts, target_parts):
        path_source.append(first)
        path_target.append(second)
        if first != second:
            break

    return ".".join(path_source), ".".join(path_target)
