import importlib
import sys
from collections.abc import Sequence
from typing import Optional

import grimp
from grimp import ImportGraph

from arch_blueprint.modules import BlueprintModule
from arch_blueprint.renderer.base import BlueprintRenderer


class ArchBlueprint:
    """Generates architecture blueprints for Python applications."""

    graph: ImportGraph

    def __init__(
        self,
        project_dir: str,
        target_names: Sequence[str],
        renderer: BlueprintRenderer,
        sys_path: Optional[list[str]] = None,
    ) -> None:
        self.project_dir = project_dir
        self.sys_path = sys_path or sys.path
        self.target_names = target_names
        self.renderer = renderer

    def run(self) -> str:
        self.sys_path.append(self.project_dir)

        top_level_module = self._get_top_level_package(self.target_names[0])
        self.graph = grimp.build_graph(top_level_module)

        blueprint_modules = self.collect_modules()
        return self.renderer.render(blueprint_modules)

    @staticmethod
    def _get_top_level_package(module_name: str) -> str:
        components = module_name.split(".")
        for level in range(len(components)):
            candidate_name = ".".join(components[: level + 1])
            candidate = importlib.import_module(candidate_name)
            if candidate.__file__:
                return candidate_name
        raise ImportError(
            f"Can't import module '{module_name}'. Is it on the Python path?",
        )

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
            is_namespace = any(
                longer_name.startswith(name + ".") for longer_name in result
            )
            if not is_namespace:
                result.add(name)

        return result
