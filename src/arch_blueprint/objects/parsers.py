import os
from functools import cached_property
from pathlib import Path
from typing import List, Set, Dict

import gitmatch
import libcst as cst
from gitmatch import Gitignore

from arch_blueprint.objects.models import BlueprintPackage
from arch_blueprint.objects.visitors import BlueprintClassCollector, ClassInfoCollector


class BlueprintObjectParser:
    def __init__(
        self, root_path: str, sub_path: str, parent_classes: Set[str] | None = None
    ) -> None:
        self._default_ignore_patters = [
            ".git",
            "__pycache__",
            ".pytest_cache",
            ".venv",
            "venv",
            "*.pyc",
        ]
        self._target_parent_classes = parent_classes
        self.root_path = Path(root_path)
        self.sub_path = Path(sub_path)
        self.all_classes = {}

    @property
    def full_path(self):
        return self.root_path / self.sub_path

    def run(self) -> list[BlueprintPackage]:
        if not self.root_path.exists():
            raise ValueError(f"Invalid root path: {self.full_path}")

        if not self.full_path.exists():
            raise ValueError(f"Invalid path: {self.full_path}")

        self._load_all_classes()

        if self.full_path.is_file():
            package = self._analyze_file(self.full_path)
        elif self.full_path.is_dir():
            package = self._analyze_directory(self.full_path)
        else:
            raise ValueError(f"Unsupported path type: {self.full_path}")

        return _exclude_empty_packages([package])

    def _load_all_classes(self) -> None:
        for path in self.root_path.rglob("*.py"):
            path: Path
            if self._should_ignore(path):
                continue

            file_path = self.root_path / path
            self.all_classes.update(self._extract_class_bases(file_path))

        self.target_classes = self._filter_target_classes(self.all_classes)

    def _analyze_directory(self, path: Path) -> BlueprintPackage:
        rel_path = path.relative_to(self.root_path)
        name = str(rel_path).replace("/", ".")
        package = BlueprintPackage(name=name)

        for sub_file in path.iterdir():
            sub_file = Path(sub_file)
            if self._should_ignore(sub_file):
                continue

            if sub_file.is_dir():
                subpackage = self._analyze_directory(sub_file)
                package.packages.append(subpackage)
            elif sub_file.is_file() and sub_file.name.endswith(".py"):
                file_package = self._analyze_file(sub_file)
                package.objects.extend(file_package.objects)

        return package

    def _analyze_file(self, sub_path: Path) -> BlueprintPackage:
        file_path = self.root_path / sub_path
        with open(file_path, "rb") as file:
            code = file.read()

        # TODO: handler syntax errors
        module = cst.parse_module(code)
        package_name = os.path.splitext(file_path)[0]

        collector = BlueprintClassCollector(self.target_classes, package_name, methods=None, decorators=["router.get", "router.post", "shared_task"])
        module.visit(collector)

        return BlueprintPackage(name=package_name, objects=collector.objects)

    def _extract_class_bases(self, file_path: Path) -> dict[str, list[str]]:
        with open(file_path, "rb") as file:
            code = file.read()

        try:
            module = cst.parse_module(code)
            collector = ClassInfoCollector()
            module.visit(collector)
            return collector.class_bases
        except Exception:
            return {}

    def _should_ignore(self, path: Path) -> bool:
        rel_path = path.relative_to(self.root_path)
        return bool(self._gitignore.match(rel_path, is_dir=path.is_dir()))

    @cached_property
    def _gitignore(self) -> Gitignore[str]:
        gitignore_path = os.path.join(self.root_path, ".gitignore")
        patterns = []

        if os.path.exists(gitignore_path):
            with open(gitignore_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        patterns.append(line)

        patterns.extend(self._default_ignore_patters)
        return gitmatch.compile(patterns)

    def _filter_target_classes(self, all_classes: Dict[str, List[str]]) -> Set[str]:
        target_classes = set()

        def is_target_class(class_name: str, visited: Set[str] | None = None) -> bool:
            if visited is None:
                visited = set()

            if class_name in visited:
                return False
            if class_name not in all_classes:
                return False

            visited.add(class_name)

            for parent_class in all_classes[class_name]:
                if self._target_parent_classes is None:
                    return True
                if parent_class in self._target_parent_classes:
                    return True
                if is_target_class(parent_class, visited):
                    return True

            return False

        for class_name in all_classes.keys():
            if is_target_class(class_name):
                target_classes.add(class_name)

        return target_classes


def _exclude_empty_packages(packages: list[BlueprintPackage]) -> list[BlueprintPackage]:
    result = []
    for package in packages:
        sub_packages = _exclude_empty_packages(package.packages)
        package.packages = sub_packages

        if len(sub_packages) == 0:
            if len(package.objects) == 0:
                continue

        result.append(package)

    return result
