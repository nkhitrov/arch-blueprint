from collections.abc import Sequence
from typing import Optional

import grimp

from arch_blueprint.modules import BlueprintModule
from arch_blueprint.puml import PlantUmlRenderer


class ArchBlueprint:
    """Generates architecture blueprints for Python applications."""

    def __init__(
        self,
        root: str,
        target_names: Sequence[str],
        renderer: Optional[PlantUmlRenderer] = None,
    ) -> None:
        self.root = root
        self.target_names = target_names
        self.graph = grimp.build_graph(self.root)
        self.renderer = renderer or PlantUmlRenderer()

    def run(self) -> None:
        blueprint_modules = self.collect_modules()
        self.renderer.render(blueprint_modules)

    def collect_modules(self) -> list[BlueprintModule]:
        module_names = self.prepare_modules_list()
        result = []
        for name in module_names:
            module = self.build_module(name, module_names)
            result.append(module)

        return result

    def prepare_modules_list(self) -> set[str]:
        module_names: set[str] = set()
        for name in self.target_names:
            modules = self.graph.find_matching_modules(name)
            module_names.update(modules)
        return self._exclude_sub_modules(module_names)

    def build_module(self, name: str, module_names: set[str]) -> BlueprintModule:
        dependencies = self._find_all_modules_imported_by(name)
        return BlueprintModule(
            name=name,
            dependencies=dependencies,
            selected_modules=module_names,
        )

    def _find_all_modules_imported_by(self, module: str) -> set[str]:
        result = set()
        descends = self.graph.find_descendants(module)
        if not descends:
            return self.graph.find_modules_directly_imported_by(module)

        for descend in descends:
            imported_mods = self.graph.find_modules_directly_imported_by(descend)
            result.update(imported_mods)

        return result

    @staticmethod
    def _exclude_sub_modules(modules: set[str]) -> set[str]:
        """Filter out names that are namespaces of other modules in the set."""
        sorted_names = sorted(modules, key=len, reverse=True)
        result: set[str] = set()

        for name in sorted_names:
            is_namespace = False
            for longer_name in list(result):
                if name in longer_name:
                    is_namespace = True
                    break

            if not is_namespace:
                result.add(name)

        return result
