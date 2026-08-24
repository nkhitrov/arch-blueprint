from __future__ import annotations

import ast
from typing import Optional

from arch_blueprint.domain.graph import BlueprintGraph, Edge
from arch_blueprint.domain.node import Node, NodeKind
from arch_blueprint.extract.base import parent_namespace
from arch_blueprint.extract.source import GrimpSource


class ClassExtractor:
    """Extracts a class-level graph from the source of the selected modules.

    Each top-level class becomes a node grouped under its defining module. A
    class depends on another *selected* class when it references it through base
    classes, annotations, or calls — resolved via the module's imports. Because a
    class's namespace is its module, class edges feed the same module-level
    link/cycle pipeline as :class:`ModuleExtractor`, with class names shown in the
    cycle details.

    The relationship rules live in :meth:`_referenced_class_ids`, deliberately
    isolated so they can evolve (e.g. to add composition or usage) without
    touching the rest of the pipeline.
    """

    def __init__(self, source: GrimpSource) -> None:
        self.source = source

    def extract(self) -> BlueprintGraph:
        modules = self.source.selected_modules()
        trees: dict[str, ast.Module] = {}
        module_classes: dict[str, list[ast.ClassDef]] = {}
        class_ids: set[str] = set()

        for module in modules:
            tree = self._parse(module)
            if tree is None:
                continue
            trees[module] = tree
            classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
            module_classes[module] = classes
            class_ids.update(f"{module}.{cls.name}" for cls in classes)

        nodes = [
            Node(id=f"{module}.{cls.name}", kind=NodeKind.CLASS, namespace=module)
            for module in modules
            if module in trees
            for cls in module_classes[module]
        ]

        edges: set[Edge] = set()
        for module, tree in trees.items():
            import_map = self._build_import_map(tree, module)
            local_classes = {cls.name for cls in module_classes[module]}
            for cls in module_classes[module]:
                source_id = f"{module}.{cls.name}"
                referenced = self._referenced_class_ids(
                    cls,
                    module,
                    import_map,
                    local_classes,
                    class_ids,
                )
                for target_id in referenced:
                    target_module = parent_namespace(target_id)
                    if target_module != module:
                        edges.add(
                            Edge(
                                source=source_id,
                                target=target_id,
                                source_namespace=module,
                                target_namespace=target_module,
                            ),
                        )

        return BlueprintGraph(nodes=nodes, edges=edges)

    def _parse(self, module: str) -> Optional[ast.Module]:
        path = self.source.module_file(module)
        if path is None or path.suffix != ".py":
            return None
        try:
            return ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            return None

    def _referenced_class_ids(
        self,
        cls: ast.ClassDef,
        module: str,
        import_map: dict[str, str],
        local_classes: set[str],
        class_ids: set[str],
    ) -> set[str]:
        """Class ids referenced by ``cls`` (bases, annotations, calls)."""
        result: set[str] = set()
        for node in ast.walk(cls):
            candidate: Optional[str] = None
            if isinstance(node, ast.Name):
                candidate = self._resolve_name(
                    node.id,
                    module,
                    import_map,
                    local_classes,
                )
            elif isinstance(node, ast.Attribute):
                candidate = self._resolve_attribute(node, import_map)
            if candidate is not None and candidate in class_ids:
                result.add(candidate)
        return result

    @staticmethod
    def _resolve_name(
        name: str,
        module: str,
        import_map: dict[str, str],
        local_classes: set[str],
    ) -> Optional[str]:
        if name in import_map:
            return import_map[name]
        if name in local_classes:
            return f"{module}.{name}"
        return None

    def _resolve_attribute(
        self,
        node: ast.Attribute,
        import_map: dict[str, str],
    ) -> Optional[str]:
        dotted = self._attribute_to_dotted(node)
        if dotted is None:
            return None
        head, _, rest = dotted.partition(".")
        if head not in import_map:
            return None
        base = import_map[head]
        return f"{base}.{rest}" if rest else base

    @staticmethod
    def _attribute_to_dotted(node: ast.Attribute) -> Optional[str]:
        parts: list[str] = []
        current: ast.expr = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if not isinstance(current, ast.Name):
            return None
        parts.append(current.id)
        parts.reverse()
        return ".".join(parts)

    def _build_import_map(self, tree: ast.Module, module: str) -> dict[str, str]:
        """Map each locally bound name to the dotted target it refers to."""
        mapping: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.asname:
                        mapping[alias.asname] = alias.name
                    else:
                        top = alias.name.split(".")[0]
                        mapping[top] = top
            elif isinstance(node, ast.ImportFrom):
                base = self._resolve_from_base(node, module)
                if base is None:
                    continue
                for alias in node.names:
                    bound = alias.asname or alias.name
                    mapping[bound] = f"{base}.{alias.name}"
        return mapping

    @staticmethod
    def _resolve_from_base(node: ast.ImportFrom, module: str) -> Optional[str]:
        if node.level == 0:
            return node.module
        parts = module.split(".")
        if node.level > len(parts):
            return None
        base_parts = parts[: len(parts) - node.level]
        if node.module:
            base_parts = base_parts + node.module.split(".")
        return ".".join(base_parts) if base_parts else None
