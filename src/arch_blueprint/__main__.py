import argparse
import sys
from pathlib import Path
from types import MappingProxyType
from typing import Final, NoReturn

from arch_blueprint.blueprint import ArchBlueprint
from arch_blueprint.extract.module_extractor import ModuleExtractor
from arch_blueprint.metrics import (
    MetricConfigError,
    MetricDisplay,
    build_render_plan,
    default_registry,
    default_renders,
)
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

#: Bad input from the user; 1 is reserved for an analysis that could not finish.
_EXIT_USAGE: Final = 2
_EXIT_FAILURE: Final = 1


def _abort(message: str, code: int) -> NoReturn:
    """Report a failure the way a CLI should: one line on stderr, no traceback."""
    sys.stderr.write(f"arch-blueprint: {message}\n")
    raise SystemExit(code)


def _write(text: str) -> None:
    """Write UTF-8 regardless of the console's encoding.

    Diagram output contains arrows, so printing through a non-UTF-8 stdout (a
    Windows console, a locale-restricted CI) raises UnicodeEncodeError and the
    run dies after doing all the work.
    """
    payload = f"{text}\n".encode()
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:  # a stdout replacement without a byte layer
        sys.stdout.write(f"{text}\n")
        return
    buffer.write(payload)
    buffer.flush()


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
        help=(
            "Display a metric (repeatable). A node metric renders as a block on "
            "each node (e.g. --metric fan_in); a link metric renders as a label "
            "on each connection (e.g. --metric edge_weight)."
        ),
    )
    parser.add_argument(
        "--no-cycle-details",
        action="store_false",
        dest="cycle_details",
        default=True,
        help="Hide detailed information for cyclic dependencies",
    )
    args = parser.parse_args()

    if not Path(args.project_dir).is_dir():
        _abort(f"no such project directory: {args.project_dir}", _EXIT_USAGE)

    options = RendererOptions(
        depth_colors=DEFAULT_OPTIONS.depth_colors,
        show_cycle_details=args.cycle_details,
    )
    registry = default_registry()
    renderer_cls = _RENDERERS[args.format]
    try:
        plan = build_render_plan(
            registry=registry,
            renders=default_renders(),
            display=MetricDisplay(shown=tuple(args.metrics)),
            fmt=renderer_cls.fmt,
        )
    except MetricConfigError as error:
        _abort(str(error), _EXIT_USAGE)

    blueprint = ArchBlueprint(
        project_dir=args.project_dir,
        target_names=args.modules,
        renderer=renderer_cls(plan=plan, options=options),
        extractor_factory=ModuleExtractor,
        registry=registry,
        metric_names=plan.required_metrics,
    )
    try:
        graph = blueprint.build()
    except ImportError as error:
        _abort(str(error), _EXIT_USAGE)
    except OSError as error:
        _abort(f"could not analyze {args.project_dir}: {error}", _EXIT_FAILURE)

    if not graph.nodes:
        patterns = ", ".join(repr(pattern) for pattern in args.modules)
        _abort(f"no modules matched: {patterns}", _EXIT_USAGE)

    _write(blueprint.render(graph))


if __name__ == "__main__":
    main()
