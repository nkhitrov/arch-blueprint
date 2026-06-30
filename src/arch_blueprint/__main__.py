import argparse
from types import MappingProxyType
from typing import Final

from arch_blueprint.blueprint import ArchBlueprint
from arch_blueprint.modules.renderers import (
    DEFAULT_OPTIONS,
    BlueprintModuleRenderer,
    RendererOptions,
)
from arch_blueprint.modules.renderers import D2ModuleRenderer
from arch_blueprint.modules.renderers import PlantUmlModuleRenderer

_RENDERERS: Final[MappingProxyType[str, type[BlueprintModuleRenderer]]] = (
    MappingProxyType(
        {
            "puml": PlantUmlModuleRenderer,
            "d2": D2ModuleRenderer,
        },
    )
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
        help=f"Output format. Possible values: {_RENDERERS.keys()}",
    )
    parser.add_argument(
        "--no-cycle-details",
        action="store_false",
        dest="cycle_details",
        default=True,
        help="Hide detailed module-level information for cyclic dependencies",
    )
    args = parser.parse_args()
    options = RendererOptions(
        depth_colors=DEFAULT_OPTIONS.depth_colors,
        show_cycle_details=args.cycle_details,
    )
    renderer = _RENDERERS[args.format](options=options)
    try:
        result = ArchBlueprint(
            project_dir=args.project_dir,
            target_names=args.modules,
            renderer=renderer,
        ).run()
    except ValueError as e:
        result = "Error: {}".format(e)

    print(result)  # noqa: T201
    exit(1)


if __name__ == "__main__":
    main()
