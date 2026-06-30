import argparse
from types import MappingProxyType
from typing import Final

from arch_blueprint.blueprint import ArchBlueprint
from arch_blueprint.extract.module_extractor import ModuleExtractor
from arch_blueprint.metrics import default_registry
from arch_blueprint.renderer.base import (
    DEFAULT_OPTIONS,
    BlueprintRenderer,
    RendererOptions,
)
from arch_blueprint.renderer.d2 import D2LangRenderer
from arch_blueprint.renderer.puml import PlantUmlRenderer

_RENDERERS: Final[MappingProxyType[str, type[BlueprintRenderer]]] = MappingProxyType(
    {
        "puml": PlantUmlRenderer,
        "d2": D2LangRenderer,
    },
)


def main() -> None:
    """Main entry point for the arch_blueprint CLI."""
    parser = argparse.ArgumentParser(
        description="Generate architecture diagrams for Python applications",
    )
    parser.add_argument(
        "project_dir",
        type=str,
        help="Path to root directory of target project",
    )
    parser.add_argument(
        "--modules",
        "-m",
        required=True,
        type=str,
        nargs="*",
        action="extend",
        help=(
            "Selected modules for rendering "
            "(examples: 'myapp.somemodule', "
            "'myapp.somemodule.*', 'myapp.*.*.models.*', 'myapp.somemodule.**')"
        ),
    )
    parser.add_argument(
        "--format",
        "-f",
        required=False,
        default="puml",
        choices=_RENDERERS.keys(),
        help=f"Output format. Possible values: {list(_RENDERERS.keys())}",
    )
    parser.add_argument(
        "--metric",
        action="append",
        default=[],
        dest="metrics",
        metavar="NAME",
        help="Show a metric block on each node (repeatable). e.g. --metric fan_in",
    )
    parser.add_argument(
        "--no-cycle-details",
        action="store_false",
        dest="cycle_details",
        default=True,
        help="Hide detailed information for cyclic dependencies",
    )
    args = parser.parse_args()

    options = RendererOptions(
        depth_colors=DEFAULT_OPTIONS.depth_colors,
        show_cycle_details=args.cycle_details,
        shown_metrics=tuple(args.metrics),
    )
    registry = default_registry()
    renderer = _RENDERERS[args.format](options=options, registry=registry)
    result = ArchBlueprint(
        project_dir=args.project_dir,
        target_names=args.modules,
        renderer=renderer,
        extractor_cls=ModuleExtractor,
        registry=registry,
    ).run()
    print(result)  # noqa: T201


if __name__ == "__main__":
    main()
