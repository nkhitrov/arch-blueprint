from __future__ import annotations

from collections.abc import Sequence
from typing import Optional

from arch_blueprint.extract.base import GraphExtractor
from arch_blueprint.extract.module_extractor import ModuleExtractor
from arch_blueprint.extract.source import GrimpSource
from arch_blueprint.metrics import MetricRegistry, default_registry
from arch_blueprint.renderer.base import BlueprintRenderer


class ArchBlueprint:
    """Generates architecture blueprints for Python applications.

    Drives the pipeline: build the import source, extract a graph (modules or
    classes), compute metrics, and render.
    """

    def __init__(
        self,
        project_dir: str,
        target_names: Sequence[str],
        renderer: BlueprintRenderer,
        extractor_cls: type[GraphExtractor] = ModuleExtractor,
        registry: Optional[MetricRegistry] = None,
        sys_path: Optional[list[str]] = None,
    ) -> None:
        self.project_dir = project_dir
        self.target_names = target_names
        self.renderer = renderer
        self.extractor_cls = extractor_cls
        self.registry = registry or default_registry()
        self.sys_path = sys_path

    def run(self) -> str:
        source = GrimpSource(self.project_dir, self.target_names, self.sys_path)
        extractor = self.extractor_cls(source)
        graph = extractor.extract()
        self.registry.compute_all(graph)
        return self.renderer.render(graph)
