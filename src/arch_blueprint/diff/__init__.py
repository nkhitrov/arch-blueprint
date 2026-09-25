from types import MappingProxyType
from typing import Final

from arch_blueprint.diff.compute import diff_graphs
from arch_blueprint.diff.model import (
    ChangeStatus,
    CycleChange,
    CycleDelta,
    GraphDiff,
    display_name,
    shadowed_id,
)
from arch_blueprint.diff.render_base import DiffRenderer
from arch_blueprint.diff.render_d2 import D2LangDiffRenderer
from arch_blueprint.diff.render_puml import PlantUmlDiffRenderer

#: One diff renderer per diagram format; keep the keys in step with the CLI's
#: diagram renderers so ``diff -f`` accepts what ``render -f`` does.
DIFF_RENDERERS: Final[MappingProxyType[str, type[DiffRenderer]]] = MappingProxyType(
    {
        "puml": PlantUmlDiffRenderer,
        "d2": D2LangDiffRenderer,
    },
)

__all__ = [
    "DIFF_RENDERERS",
    "ChangeStatus",
    "CycleChange",
    "CycleDelta",
    "D2LangDiffRenderer",
    "DiffRenderer",
    "GraphDiff",
    "PlantUmlDiffRenderer",
    "diff_graphs",
    "display_name",
    "shadowed_id",
]
