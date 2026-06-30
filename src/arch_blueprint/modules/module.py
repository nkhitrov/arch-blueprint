from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from functools import cached_property

from arch_blueprint.modules.models import NamespaceLink, ModuleEdge


@dataclass
class BlueprintModule:
    """Module in the architecture blueprint with its dependencies."""

    name: str
    dependencies: set[str]
    selected_modules: set[str]

    @cached_property
    def namespace(self) -> str:
        return self._get_namespace_of_module(self.name)

    @cached_property
    def depth(self) -> int:
        return len(self.name.split("."))

    def get_namespace(self) -> str:
        return self.namespace

    def find_namespace_links(self) -> set[NamespaceLink]:
        """Find namespace links with full module edge information."""
        edges_by_namespace: dict[tuple[str, str], set[ModuleEdge]] = defaultdict(set)

        prefixes = [(m, m + ".") for m in self.selected_modules]
        for dep in self.dependencies:
            for selected_module, prefix in prefixes:
                if dep == selected_module or dep.startswith(prefix):
                    source_ns, target_ns = self.extract_namespaces_with_same_depth(dep)
                    if source_ns != target_ns:
                        edge = ModuleEdge(
                            source_module=self.name,
                            target_module=dep,
                            source_namespace=source_ns,
                            target_namespace=target_ns,
                        )
                        edges_by_namespace[(source_ns, target_ns)].add(edge)

        return {
            NamespaceLink(
                source_namespace=ns_pair[0],
                target_namespace=ns_pair[1],
                edges=frozenset(edges),
            )
            for ns_pair, edges in edges_by_namespace.items()
        }

    def find_dependencies_namespace_to_namespaces(self) -> set[tuple[str, str]]:
        """Find namespace-level dependencies (backward compatible)."""
        return {
            (link.source_namespace, link.target_namespace)
            for link in self.find_namespace_links()
        }

    def is_same_namespace(self, other: str) -> bool:
        other_namespace = self._get_namespace_of_module(other)
        return self.namespace == other_namespace

    def _get_namespace_of_module(self, module: str) -> str:
        if "." not in module:
            return module
        namespace, _ = module.rsplit(".", maxsplit=1)
        return namespace

    def extract_namespaces_with_same_depth(self, module: str) -> tuple[str, str]:
        from_ = self.name.split(".")
        to_ = module.split(".")

        path_from = []
        path_to = []
        for first, second in zip(from_, to_):
            path_from.append(first)
            path_to.append(second)
            if first != second:
                break

        return ".".join(path_from), ".".join(path_to)
