import argparse
import sys
from collections.abc import Callable, Iterable, Sequence
from contextlib import ExitStack
from pathlib import Path
from types import MappingProxyType
from typing import Final, NoReturn, Optional, TextIO

from arch_blueprint.blueprint import build_graph
from arch_blueprint.diff import DIFF_RENDERERS, diff_graphs
from arch_blueprint.diff.git import GitError, checkout, split_patterns
from arch_blueprint.domain.graph import BlueprintGraph
from arch_blueprint.extract.module_extractor import ModuleExtractor
from arch_blueprint.metrics import (
    MetricConfigError,
    MetricDisplay,
    MetricRegistry,
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
from arch_blueprint.snapshot import Snapshot, SnapshotError, dump, load

_RENDERERS: Final[MappingProxyType[str, type[BlueprintRenderer]]] = MappingProxyType(
    {
        "puml": PlantUmlRenderer,
        "d2": D2LangRenderer,
    },
)

#: Not a diagram: the graph snapshot every diagram and diff is drawn from.
_SNAPSHOT_FORMAT: Final = "json"

#: Bad input from the user; 1 is reserved for an analysis that could not finish.
_EXIT_USAGE: Final = 2
_EXIT_FAILURE: Final = 1
#: ``diff`` exits like diff(1): 0 same, 1 different, 2 trouble of any kind.
_EXIT_DIFFERENT: Final = 1
_EXIT_DIFF_TROUBLE: Final = 2


def _abort(message: str, code: int) -> NoReturn:
    """Report a failure the way a CLI should: one line on stderr, no traceback."""
    _emit(sys.stderr, f"arch-blueprint: {message}")
    raise SystemExit(code)


def _write(text: str) -> None:
    """Write the result to stdout as UTF-8 (see ``_emit``)."""
    _emit(sys.stdout, text)


def _emit(stream: TextIO, text: str) -> None:
    """Write a line as UTF-8 regardless of the console's encoding.

    Diagram output contains arrows, and messages may carry any path or git
    error, so writing through a non-UTF-8 stream (a Windows console, a
    locale-restricted CI) either raises UnicodeEncodeError after all the work
    is done or hands the reader bytes that are not UTF-8.
    """
    buffer = getattr(stream, "buffer", None)
    if buffer is None:  # a stream replacement without a byte layer
        stream.write(f"{text}\n")
        return
    stream.flush()  # keep order with anything already written as text
    buffer.write(f"{text}\n".encode())
    buffer.flush()


# --- argument groups ------------------------------------------------------


def _add_modules_arg(parser: argparse.ArgumentParser, *, required: bool) -> None:
    parser.add_argument(
        "--modules",
        "-m",
        required=required,
        type=str,
        nargs="*",
        action="extend",
        default=[],
        help=(
            "Selected modules for rendering "
            "(examples: 'myapp.somemodule', "
            "'myapp.somemodule.*', 'myapp.*.*.models.*', 'myapp.somemodule.**')"
        ),
    )


def _add_format_arg(parser: argparse.ArgumentParser, formats: Iterable[str]) -> None:
    choices = list(formats)
    parser.add_argument(
        "--format",
        "-f",
        required=False,
        default="puml",
        choices=choices,
        help=f"Output format. Possible values: {choices}",
    )


def _add_metric_arg(parser: argparse.ArgumentParser) -> None:
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


def _add_cycle_details_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--no-cycle-details",
        action="store_false",
        dest="cycle_details",
        default=True,
        help="Hide detailed information for cyclic dependencies",
    )


# --- shared steps ---------------------------------------------------------


def _renderer(
    fmt: str,
    metrics: Sequence[str],
    *,
    cycle_details: bool,
    registry: MetricRegistry,
) -> BlueprintRenderer:
    renderer_cls = _RENDERERS[fmt]
    try:
        plan = build_render_plan(
            registry=registry,
            renders=default_renders(),
            display=MetricDisplay(shown=tuple(metrics)),
            fmt=renderer_cls.fmt,
        )
    except MetricConfigError as error:
        _abort(str(error), _EXIT_USAGE)
    options = RendererOptions(
        depth_colors=DEFAULT_OPTIONS.depth_colors,
        show_cycle_details=cycle_details,
    )
    return renderer_cls(plan=plan, options=options)


def _build(
    project_dir: str,
    modules: Sequence[str],
    metric_names: Optional[Iterable[str]],
    *,
    failure_code: int,
    use_cache: bool = True,
) -> BlueprintGraph:
    """Build a graph, turning every expected failure into one stderr line."""
    if not Path(project_dir).is_dir():
        _abort(f"no such project directory: {project_dir}", _EXIT_USAGE)
    try:
        return build_graph(
            project_dir,
            modules,
            ModuleExtractor,
            default_registry(),
            metric_names,
            use_cache=use_cache,
        )
    except ImportError as error:
        _abort(str(error), _EXIT_USAGE)
    except OSError as error:
        _abort(f"could not analyze {project_dir}: {error}", failure_code)


def _no_match(modules: Sequence[str]) -> NoReturn:
    patterns = ", ".join(repr(pattern) for pattern in modules)
    _abort(f"no modules matched: {patterns}", _EXIT_USAGE)


def _read_snapshot(path: str) -> Snapshot:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        _abort(f"cannot read snapshot {path}: {error}", _EXIT_USAGE)
    try:
        return load(text)
    except SnapshotError as error:
        _abort(f"{path}: {error}", _EXIT_USAGE)


# --- commands -------------------------------------------------------------


def _generate(argv: Sequence[str]) -> None:
    """``arch-blueprint <project_dir> -m ...``: graph a project."""
    parser = argparse.ArgumentParser(
        description=(
            "Generate architecture diagrams for Python applications. "
            "Subcommands: 'render' draws a snapshot, 'diff' compares two."
        ),
    )
    parser.add_argument(
        "project_dir",
        type=str,
        help="Path to root directory of target project",
    )
    _add_modules_arg(parser, required=True)
    _add_format_arg(parser, [*_RENDERERS, _SNAPSHOT_FORMAT])
    _add_metric_arg(parser)
    _add_cycle_details_arg(parser)
    args = parser.parse_args(argv)

    registry = default_registry()
    if args.format == _SNAPSHOT_FORMAT:
        if args.metrics or not args.cycle_details:
            _abort(
                "--metric and --no-cycle-details apply to drawing; a snapshot "
                "holds every metric — pass them to 'render' instead",
                _EXIT_USAGE,
            )
        graph = _build(args.project_dir, args.modules, None, failure_code=_EXIT_FAILURE)
        if not graph.nodes:
            _no_match(args.modules)
        _write(dump(graph, registry.names()))
        return

    renderer = _renderer(
        args.format,
        args.metrics,
        cycle_details=args.cycle_details,
        registry=registry,
    )
    graph = _build(
        args.project_dir,
        args.modules,
        renderer.plan.required_metrics,
        failure_code=_EXIT_FAILURE,
    )
    if not graph.nodes:
        _no_match(args.modules)
    _write(renderer.render(graph))


def _render(argv: Sequence[str]) -> None:
    """``arch-blueprint render SNAPSHOT``: draw a snapshot."""
    parser = argparse.ArgumentParser(
        prog="arch-blueprint render",
        description="Draw a diagram from a snapshot made with '-f json'.",
    )
    parser.add_argument("snapshot", help="Snapshot file ('-f json' output)")
    _add_format_arg(parser, _RENDERERS)
    _add_metric_arg(parser)
    _add_cycle_details_arg(parser)
    args = parser.parse_args(argv)

    snapshot = _read_snapshot(args.snapshot)
    renderer = _renderer(
        args.format,
        args.metrics,
        cycle_details=args.cycle_details,
        registry=default_registry(),
    )
    missing = sorted(renderer.plan.required_metrics - snapshot.metrics)
    if missing:
        _abort(
            f"{args.snapshot} holds no metric {', '.join(map(repr, missing))} "
            f"(it has: {', '.join(sorted(snapshot.metrics)) or 'none'})",
            _EXIT_USAGE,
        )
    _write(renderer.render(snapshot.graph))


def _diff(argv: Sequence[str]) -> None:
    """``arch-blueprint diff``: draw what changed; exit 0 same, 1 different."""
    parser = argparse.ArgumentParser(
        prog="arch-blueprint diff",
        description=(
            "Draw what changed between two snapshots (diff OLD.json NEW.json), or "
            "between a git revision and the working tree "
            "(diff --base REV PROJECT_DIR -m ...). Exits 0 when nothing changed, "
            "1 when something did, 2 on error. Graphing arch_blueprint itself "
            "always resolves to the running copy."
        ),
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        metavar="INPUT",
        help="OLD.json NEW.json, or PROJECT_DIR with --base",
    )
    parser.add_argument("--base", metavar="REV", help="Revision to compare against")
    parser.add_argument(
        "--head",
        metavar="REV",
        help="Revision to compare (default: the working tree)",
    )
    _add_modules_arg(parser, required=False)
    _add_format_arg(parser, DIFF_RENDERERS)
    _add_cycle_details_arg(parser)
    args = parser.parse_args(argv)

    if args.base is None:
        if len(args.inputs) != 2 or args.modules or args.head:
            _abort(
                "diff takes two snapshots (OLD.json NEW.json), "
                "or --base REV PROJECT_DIR -m ...",
                _EXIT_DIFF_TROUBLE,
            )
        old = _read_snapshot(args.inputs[0]).graph
        new = _read_snapshot(args.inputs[1]).graph
    else:
        if len(args.inputs) != 1 or not args.modules:
            _abort(
                "diff --base takes one PROJECT_DIR and at least one -m pattern",
                _EXIT_DIFF_TROUBLE,
            )
        old, new = _git_sides(args.inputs[0], args.modules, args.base, args.head)

    diff = diff_graphs(old, new)
    renderer = DIFF_RENDERERS[args.format](show_cycle_details=args.cycle_details)
    _write(renderer.render(diff))
    raise SystemExit(0 if diff.is_empty else _EXIT_DIFFERENT)


def _git_sides(
    project_dir: str,
    modules: Sequence[str],
    base: str,
    head: Optional[str],
) -> tuple[BlueprintGraph, BlueprintGraph]:
    """Build the graph at ``base`` and at ``head`` (default: the working tree)."""
    if not Path(project_dir).is_dir():
        _abort(f"no such project directory: {project_dir}", _EXIT_DIFF_TROUBLE)
    with ExitStack() as stack:
        try:
            old_dir = stack.enter_context(checkout(project_dir, base))
            new_dir = (
                project_dir
                if head is None
                else stack.enter_context(checkout(project_dir, head))
            )
        except GitError as error:
            _abort(str(error), _EXIT_DIFF_TROUBLE)
        old_modules, new_modules = split_patterns(modules, old_dir, new_dir)
        old = _side(old_dir, old_modules)
        new = _side(new_dir, new_modules)
    if not old.nodes and not new.nodes:
        _no_match(modules)
    return old, new


def _side(project_dir: str, modules: Sequence[str]) -> BlueprintGraph:
    if not modules:  # this side has none of the selected packages
        return BlueprintGraph(nodes=[], edges=frozenset())
    # No metrics: a diff compares structure only. No cache: grimp would take two
    # checkouts whose files share an mtime (git archive stamps the commit time)
    # for one and the same project.
    return _build(
        project_dir,
        modules,
        (),
        failure_code=_EXIT_DIFF_TROUBLE,
        use_cache=False,
    )


_SUBCOMMANDS: Final[MappingProxyType[str, Callable[[Sequence[str]], None]]] = (
    MappingProxyType({"render": _render, "diff": _diff})
)


def main(argv: Optional[Sequence[str]] = None) -> None:
    """Main entry point for the arch_blueprint CLI.

    A first argument naming a subcommand selects it; anything else is the
    original ``<project_dir> -m ...`` interface, unchanged.
    """
    args = sys.argv[1:] if argv is None else list(argv)
    if args and args[0] in _SUBCOMMANDS:
        _SUBCOMMANDS[args[0]](args[1:])
    else:
        _generate(args)


if __name__ == "__main__":
    main()
