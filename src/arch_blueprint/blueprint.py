from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import Optional

from arch_blueprint.analyze import analyze
from arch_blueprint.domain.graph import BlueprintGraph
from arch_blueprint.extract.base import GraphExtractor
from arch_blueprint.extract.module_extractor import ModuleExtractor
from arch_blueprint.extract.source import GrimpSource
from arch_blueprint.metrics import MetricRegistry, default_registry
from arch_blueprint.renderer.base import BlueprintRenderer


def build_graph(
    project_dir: str,
    target_names: Sequence[str],
    extractor_factory: Callable[[GrimpSource], GraphExtractor] = ModuleExtractor,
    registry: Optional[MetricRegistry] = None,
    metric_names: Optional[Iterable[str]] = None,
    *,
    use_cache: bool = True,
) -> BlueprintGraph:
    """Everything up to rendering: extract, compute metrics, analyze.

    A function rather than only a method so a caller that never renders — a
    snapshot dump, either side of a diff — does not need a renderer to get here.
    ``metric_names=None`` computes every registered metric. ``use_cache=False``
    is for graphing several checkouts of one project (see ``GrimpSource``).
    """
    source = GrimpSource(project_dir, target_names, use_cache=use_cache)
    graph = extractor_factory(source).extract()
    (registry or default_registry()).compute(graph, metric_names)
    return analyze(graph)


class ArchBlueprint:
    """Generates architecture blueprints for Python applications.

    Drives the pipeline: build the import source, extract a graph, compute
    metrics, analyze it, and render.
    """

    def __init__(
        self,
        project_dir: str,
        target_names: Sequence[str],
        renderer: BlueprintRenderer,
        extractor_factory: Callable[[GrimpSource], GraphExtractor] = ModuleExtractor,
        registry: Optional[MetricRegistry] = None,
        metric_names: Optional[Iterable[str]] = None,
    ) -> None:
        self.project_dir = project_dir
        self.target_names = target_names
        self.renderer = renderer
        self.extractor_factory = extractor_factory
        self.registry = registry or default_registry()
        # None means "every registered metric"; the CLI narrows this to what the
        # render plan actually needs, color metric included.
        self.metric_names = metric_names

    def build(self) -> BlueprintGraph:
        """Everything up to rendering: extract, compute metrics, analyze.

        Exposed separately so a caller can inspect the graph — the CLI needs to
        know an empty selection produced nothing before it prints a diagram.
        """
        return build_graph(
            self.project_dir,
            self.target_names,
            self.extractor_factory,
            self.registry,
            self.metric_names,
        )

    def render(self, graph: BlueprintGraph) -> str:
        return self.renderer.render(graph)

    def run(self) -> str:
        return self.render(self.build())
