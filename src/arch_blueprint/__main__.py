import argparse
from types import MappingProxyType
from typing import Final

from arch_blueprint.blueprint import ArchBlueprint
from arch_blueprint.renderer.d2 import D2LangRenderer
from arch_blueprint.renderer.puml import PlantUmlRenderer

_RENDERERS: Final = MappingProxyType(
    {
        "puml": PlantUmlRenderer,
        "d2": D2LangRenderer,
    },
)


def main() -> None:
    """Main entry point for the arch_blueprint CLI."""
    parser = argparse.ArgumentParser(
        description="Generate component diagrams in plantuml for python applications",
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
            "'myapp.somemodule.*', 'myapp.somemodule.**')"
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
    args = parser.parse_args()
    renderer = _RENDERERS[args.format]()
    result = ArchBlueprint(project_dir=args.project_dir, target_names=args.modules, renderer=renderer).run()
    print(result)


if __name__ == "__main__":
    main()
