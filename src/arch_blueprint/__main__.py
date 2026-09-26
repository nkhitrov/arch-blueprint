import argparse
import os
import shlex
import shutil
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from tempfile import TemporaryDirectory
from types import MappingProxyType
from typing import Any, Final, NoReturn, Optional, TextIO

from grimp.exceptions import GrimpException

from arch_blueprint.blueprint import build_graph
from arch_blueprint.diff import DIFF_RENDERERS, diff_graphs
from arch_blueprint.domain.graph import BlueprintGraph
from arch_blueprint.extract.layout import detect_roots, has_source, is_package
from arch_blueprint.extract.module_extractor import ModuleExtractor
from arch_blueprint.extract.source import PackageNotFoundError
from arch_blueprint.git import (
    Commit,
    GitError,
    checkout,
    first_parent_commits,
    split_patterns,
    tree_id,
)
from arch_blueprint.history import (
    DEFAULT_CACHE_DIR,
    IMAGE_RENDERERS,
    Frame,
    ImageCache,
    ImageRenderer,
    SnapshotCache,
    collect,
    draw,
    pages,
    write,
)
from arch_blueprint.history.album import IMAGE_EXTENSION, image_of
from arch_blueprint.metrics import (
    Metric,
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

_PROG: Final = "arch-blueprint"

_RENDERERS: Final[MappingProxyType[str, type[BlueprintRenderer]]] = MappingProxyType(
    {
        "puml": PlantUmlRenderer,
        "d2": D2LangRenderer,
    },
)

#: Not a diagram: the graph snapshot every diagram and diff is drawn from.
_SNAPSHOT_FORMAT: Final = "json"

#: What each ``-f`` value is, for the help text.
_FORMAT_HELP: Final = MappingProxyType(
    {
        "puml": "PlantUML source",
        "d2": "D2 source",
        _SNAPSHOT_FORMAT: "a graph snapshot, to draw or diff later",
        f"puml-{IMAGE_EXTENSION}": "an image drawn by 'plantuml' (must be on PATH)",
        f"d2-{IMAGE_EXTENSION}": "an image drawn by 'd2' (must be on PATH)",
    },
)


def _formats(diagrams: Iterable[str]) -> MappingProxyType[str, tuple[str, bool]]:
    """``-f`` values, ``{value: (diagram format, image?)}``.

    Each diagram format as source, and as an image where a tool draws it.
    """
    diagram_formats = list(diagrams)
    return MappingProxyType(
        {
            **{fmt: (fmt, False) for fmt in diagram_formats},
            **{
                f"{fmt}-{IMAGE_EXTENSION}": (fmt, True)
                for fmt in diagram_formats
                if fmt in IMAGE_RENDERERS
            },
        },
    )


#: ``-f`` of ``history``; ``draw`` adds the snapshot.
_DIAGRAM_FORMATS: Final = _formats(_RENDERERS)
_DRAW_FORMATS: Final = MappingProxyType(
    {**_DIAGRAM_FORMATS, _SNAPSHOT_FORMAT: (_SNAPSHOT_FORMAT, False)},
)
_DIFF_FORMATS: Final = _formats(DIFF_RENDERERS)

#: ``-o`` extension -> the ``-f`` it implies; anything else keeps the default.
_EXTENSION_FORMATS: Final = MappingProxyType(
    {
        ".puml": "puml",
        ".d2": "d2",
        f".{_SNAPSHOT_FORMAT}": _SNAPSHOT_FORMAT,
        f".{IMAGE_EXTENSION}": f"puml-{IMAGE_EXTENSION}",
    },
)


#: Bad input from the user; 1 is reserved for an analysis that could not finish.
_EXIT_USAGE: Final = 2
_EXIT_FAILURE: Final = 1
#: ``diff`` exits like diff(1): 0 same, 1 different, 2 trouble of any kind.
_EXIT_DIFFERENT: Final = 1
_EXIT_DIFF_TROUBLE: Final = 2


def _abort(message: str, code: int) -> NoReturn:
    """Report a failure the way a CLI should: one line on stderr, no traceback."""
    _emit(sys.stderr, f"{_PROG}: {message}")
    raise SystemExit(code)


def _note(message: str) -> None:
    """Tell the user something about the run without failing it."""
    _emit(sys.stderr, f"{_PROG}: {message}")


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

_PATTERN_HELP: Final = (
    "Which modules to draw; repeat -m for more. 'pkg.*' = the modules directly "
    "in pkg, 'pkg.**' = everything under pkg, 'pkg.*.models' = a wildcard in "
    "the middle. Quote patterns so the shell leaves '*' alone."
)


def _add_modules_arg(parser: argparse.ArgumentParser, default: str) -> None:
    parser.add_argument(
        "--modules",
        "-m",
        type=str,
        nargs="*",
        action="extend",
        default=[],
        metavar="PATTERN",
        help=f"{_PATTERN_HELP} {default}",
    )


def _add_format_arg(
    parser: argparse.ArgumentParser,
    formats: Iterable[str],
    *,
    default: Optional[str],
    extra: str = "",
) -> None:
    choices = list(formats)
    described = "; ".join(f"{fmt} = {_FORMAT_HELP[fmt]}" for fmt in choices)
    parser.add_argument(
        "--format",
        "-f",
        default=default,
        choices=choices,
        help=f"Output format: {described}.{extra}",
    )


def _add_output_file_arg(
    parser: argparse.ArgumentParser,
    formats: Iterable[str],
) -> None:
    extensions = [ext for ext, fmt in _EXTENSION_FORMATS.items() if fmt in formats]
    parser.add_argument(
        "--output",
        "-o",
        metavar="FILE",
        help=(
            "Write to FILE instead of stdout. Without -f the extension picks the "
            f"format: {', '.join(extensions)} ({IMAGE_EXTENSION} = a PlantUML image)"
        ),
    )


def _displayable_metrics() -> list[tuple[str, Metric]]:
    """``(kind, metric)`` for each metric ``--metric`` can show."""
    registry = default_registry()
    metrics: list[tuple[str, Metric]] = [
        *(("module", metric) for metric in registry.node_metrics()),
        *(("link", metric) for metric in registry.link_metrics()),
    ]
    return [(kind, metric) for kind, metric in metrics if metric.render is not None]


def _add_metric_arg(parser: argparse.ArgumentParser) -> None:
    names = [metric.name for _, metric in _displayable_metrics()]
    parser.add_argument(
        "--metric",
        action="append",
        default=[],
        dest="metrics",
        metavar="NAME",
        help=(
            f"Show a metric; repeat for more: {', '.join(names)}. "
            "A module metric is drawn in each box, a link metric on each arrow. "
            f"'{_PROG} --list-metrics' says what each one means."
        ),
    )


def _add_cycle_details_arg(parser: argparse.ArgumentParser) -> None:
    """Opt-in everywhere: a note lists every import on both sides of a cycle.

    Detail for digging into one cycle; on a whole diagram it is most of the
    picture, so the red double arrow alone is the default.
    """
    parser.add_argument(
        "--cycle-details",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Add a note listing the imports on each cycle (default: off)",
    )


def _add_changes_only_arg(parser: argparse.ArgumentParser) -> None:
    """For ``diff`` and ``history``: drop the unchanged part of the graph."""
    parser.add_argument(
        "--changes-only",
        action="store_true",
        help=(
            "Draw only the changes and the modules they touch, not the whole "
            "graph with the changes marked on it"
        ),
    )


class _ListMetrics(argparse.Action):
    """``--list-metrics``: print what can be shown with ``--metric``, then exit."""

    def __init__(
        self,
        option_strings: Sequence[str],
        dest: str,
        help: Optional[str] = None,
    ) -> None:
        super().__init__(
            option_strings,
            dest,
            nargs=0,
            default=argparse.SUPPRESS,
            help=help,
        )

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: Any,
        option_string: Optional[str] = None,
    ) -> NoReturn:
        rows = [
            (kind, metric.name, metric.description)
            for kind, metric in _displayable_metrics()
        ]
        width = max(len(name) for _, name, _ in rows)
        for kind, name, description in rows:
            _write(f"{name:<{width}}  {kind:<6}  {description}")
        parser.exit()


# --- output ---------------------------------------------------------------


@dataclass(frozen=True)
class _Output:
    """Where a result goes and in which form, settled before any work starts.

    Settling it first is what makes a missing ``plantuml`` an error in a second,
    not after the whole project has been analyzed.
    """

    fmt: str  # a diagram format, or the snapshot format
    path: Optional[Path]
    images: Optional[ImageRenderer]

    def write(self, text: str, *, failure_code: int) -> None:
        if self.path is None:
            _write(text)
            return
        if self.images is None:
            self.path.write_bytes(f"{text}\n".encode())
            return
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / f"{self.path.stem}.{self.fmt}"
            source.write_bytes(f"{text}\n".encode())
            for _, reason in self.images.render([source]):
                _abort(f"could not draw {self.path}: {reason}", failure_code)
            shutil.move(str(image_of(source)), self.path)


def _output(
    fmt: Optional[str],
    path: Optional[str],
    formats: Mapping[str, tuple[str, bool]],
    *,
    code: int,
) -> _Output:
    """Settle ``-f`` and ``-o`` together: the extension decides a missing ``-f``."""
    implied = None if path is None else _EXTENSION_FORMATS.get(Path(path).suffix)
    if implied is not None and implied not in formats:
        implied = None  # e.g. -o x.json where no snapshot is written
    if fmt is None:
        fmt = implied or "puml"
    elif implied is not None and fmt != implied:
        both_images = formats[fmt][1] and formats[implied][1]  # -f d2-png -o x.png
        if not both_images:
            _abort(f"-f {fmt} does not fit -o {path}; drop -f or rename the file", code)
    diagram_fmt, as_image = formats[fmt]
    if as_image and path is None:
        _abort(f"-f {fmt} draws an image; give it a file with -o", code)
    images = _image_renderer(diagram_fmt, None, code) if as_image else None
    return _Output(diagram_fmt, None if path is None else Path(path), images)


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


def _check_project_dir(project_dir: str, code: int) -> None:
    if not Path(project_dir).is_dir():
        _abort(f"no such project directory: {project_dir}", code)


def _layout_hint(project_dir: str) -> str:
    """What the user probably meant, judging by what ``project_dir`` holds."""
    if is_package(project_dir):
        parent = os.path.relpath(Path(project_dir).resolve().parent)
        return (
            f"{project_dir} is itself a package — pass the directory that "
            f"contains it: {_PROG} draw {parent}"
        )
    src = _source_folder(project_dir)
    if src is not None:
        return f"{project_dir} keeps its packages in {src} — did you mean {src}?"
    roots = detect_roots(project_dir)
    if roots:
        return f"found: {', '.join(roots)}"
    return f"no Python packages in {project_dir}"


def _source_folder(project_dir: str) -> Optional[Path]:
    """``project_dir/src`` when it is a src layout's folder rather than a package.

    Such a folder passes for a namespace package, so drawing the repository root
    would draw ``src.myapp`` — a name nobody imports.
    """
    src = Path(project_dir) / "src"
    if is_package(str(src)) or not detect_roots(str(src)):
        return None
    return src


def _default_patterns(project_dir: str, code: int) -> list[str]:
    """Every package in ``project_dir``, whole — what no ``-m`` means."""
    roots = detect_roots(project_dir)
    if not roots:
        _abort(f"nothing to draw: {_layout_hint(project_dir)}", code)
    src = _source_folder(project_dir)
    if src is not None:
        _abort(
            f"{project_dir} keeps its packages in {src}: run '{_PROG} draw {src}', "
            "or choose with -m",
            code,
        )
    _note(f"drawing {', '.join(roots)} (all modules; narrow with -m)")
    return [f"{root}.**" for root in roots]


def _build(
    project_dir: str,
    modules: Sequence[str],
    metric_names: Optional[Iterable[str]],
    *,
    failure_code: int,
    use_cache: bool = True,
) -> BlueprintGraph:
    """Build a graph, turning every expected failure into one stderr line."""
    _check_project_dir(project_dir, _EXIT_USAGE)
    try:
        return build_graph(
            project_dir,
            modules,
            ModuleExtractor,
            default_registry(),
            metric_names,
            use_cache=use_cache,
        )
    except PackageNotFoundError as error:
        _abort(
            f"no package {error.package!r} in {project_dir} "
            f"({_layout_hint(project_dir)})",
            _EXIT_USAGE,
        )
    except ImportError as error:
        _abort(str(error), _EXIT_USAGE)
    except OSError as error:
        _abort(f"could not analyze {project_dir}: {error}", failure_code)


def _no_match(modules: Sequence[str]) -> NoReturn:
    patterns = ", ".join(repr(pattern) for pattern in modules)
    _abort(f"no modules matched: {patterns}", _EXIT_USAGE)


def _warn_single_boxes(
    project_dir: str,
    modules: Sequence[str],
    graph: BlueprintGraph,
) -> None:
    """A bare package name draws that package as one box — rarely what is meant."""
    ids = {node.id for node in graph.nodes}
    for pattern in modules:
        if "*" in pattern or pattern not in ids:
            continue
        if Path(project_dir, *pattern.split(".")).is_dir():
            _note(
                f"-m {pattern!r} draws the package as a single box; "
                f"use '{pattern}.*' for its modules or '{pattern}.**' for all of them",
            )


def _read_snapshot(path: str, code: int = _EXIT_USAGE) -> Snapshot:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        _abort(f"cannot read snapshot {path}: {error}", code)
    try:
        return load(text)
    except SnapshotError as error:
        _abort(f"{path}: {error}", code)


# --- commands -------------------------------------------------------------

_Handler = Callable[[argparse.Namespace], None]


def _subparser(
    commands: "argparse._SubParsersAction[argparse.ArgumentParser]",
    name: str,
    *,
    summary: str,
    description: str,
    examples: str,
    handler: _Handler,
) -> argparse.ArgumentParser:
    parser = commands.add_parser(
        name,
        help=summary,
        description=description,
        epilog=f"examples:\n{examples}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.set_defaults(handler=handler)
    return parser


def _add_draw(commands: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    parser = _subparser(
        commands,
        "draw",
        summary="draw a project's import graph, or a saved snapshot",
        description=(
            "Draw the import graph of the packages in PROJECT_DIR, or of a snapshot\n"
            "saved earlier with '-o graph.json'.\n\n"
            "Each box is a module. An arrow means some module on one side imports\n"
            "one on the other; arrows are drawn between the packages where the two\n"
            "modules' paths part. A red double arrow is a dependency cycle."
        ),
        examples=(
            "  arch-blueprint draw src                      every package in src/\n"
            "  arch-blueprint draw src -m 'myapp.*'         the modules directly "
            "in myapp\n"
            "  arch-blueprint draw src -o arch.png          an image (needs plantuml)\n"
            "  arch-blueprint draw src -o arch.d2           D2 source\n"
            "  arch-blueprint draw src -o graph.json        a snapshot, to draw "
            "or diff later\n"
            "  arch-blueprint draw graph.json -o arch.png   draw the snapshot\n"
            "  arch-blueprint draw . -m 'app1.*' -m 'app2.*' --metric fan_in"
        ),
        handler=_draw,
    )
    parser.add_argument(
        "source",
        nargs="?",
        metavar="PROJECT_DIR|SNAPSHOT",
        help=(
            "The directory the packages sit in (e.g. 'src', or the repository "
            "root) — not the package directory itself. Or a snapshot saved "
            "earlier with '-o graph.json', to draw it without the project."
        ),
    )
    _add_modules_arg(parser, "Default: every package in PROJECT_DIR, whole.")
    _add_format_arg(
        parser,
        _DRAW_FORMATS,
        default=None,
        extra=" Default: puml, or what -o's extension says.",
    )
    _add_output_file_arg(parser, _DRAW_FORMATS)
    _add_metric_arg(parser)
    _add_cycle_details_arg(parser)


def _draw(args: argparse.Namespace) -> None:
    """``arch-blueprint draw PROJECT_DIR|SNAPSHOT``: draw a project or a snapshot."""
    if args.source is None:
        swallowed = [pattern for pattern in args.modules if Path(pattern).is_dir()]
        if swallowed:
            _abort(
                f"-m took {swallowed[0]!r} as a pattern; put PROJECT_DIR before -m "
                "or pass one pattern per -m",
                _EXIT_USAGE,
            )
        _abort("draw needs a PROJECT_DIR (see 'arch-blueprint draw -h')", _EXIT_USAGE)
    output = _output(args.format, args.output, _DRAW_FORMATS, code=_EXIT_USAGE)
    if output.fmt == _SNAPSHOT_FORMAT and (args.metrics or args.cycle_details):
        _abort(
            "--metric and --cycle-details apply to drawing; a snapshot holds every "
            "metric — pass them when you draw the snapshot",
            _EXIT_USAGE,
        )
    if Path(args.source).is_file() or args.source.endswith(f".{_SNAPSHOT_FORMAT}"):
        _draw_snapshot(args, output)
    else:
        _draw_project(args, output)


def _draw_project(args: argparse.Namespace, output: _Output) -> None:
    _check_project_dir(args.source, _EXIT_USAGE)
    modules = args.modules or _default_patterns(args.source, _EXIT_USAGE)
    registry = default_registry()
    if output.fmt == _SNAPSHOT_FORMAT:
        graph = _build(args.source, modules, None, failure_code=_EXIT_FAILURE)
        if not graph.nodes:
            _no_match(modules)
        _warn_single_boxes(args.source, args.modules, graph)
        output.write(dump(graph, registry.names()), failure_code=_EXIT_FAILURE)
        return

    renderer = _renderer(
        output.fmt,
        args.metrics,
        cycle_details=args.cycle_details,
        registry=registry,
    )
    graph = _build(
        args.source,
        modules,
        renderer.plan.required_metrics,
        failure_code=_EXIT_FAILURE,
    )
    if not graph.nodes:
        _no_match(modules)
    _warn_single_boxes(args.source, args.modules, graph)
    output.write(renderer.render(graph), failure_code=_EXIT_FAILURE)


def _draw_snapshot(args: argparse.Namespace, output: _Output) -> None:
    """A snapshot is drawn byte for byte as its project would have been."""
    if args.modules:
        _abort(
            f"-m chooses modules in a project; {args.source} is a snapshot, "
            "already chosen",
            _EXIT_USAGE,
        )
    if output.fmt == _SNAPSHOT_FORMAT:
        _abort(f"{args.source} is a snapshot already", _EXIT_USAGE)
    snapshot = _read_snapshot(args.source)
    renderer = _renderer(
        output.fmt,
        args.metrics,
        cycle_details=args.cycle_details,
        registry=default_registry(),
    )
    missing = sorted(renderer.plan.required_metrics - snapshot.metrics)
    if missing:
        _abort(
            f"{args.source} holds no metric {', '.join(map(repr, missing))} "
            f"(it has: {', '.join(sorted(snapshot.metrics)) or 'none'})",
            _EXIT_USAGE,
        )
    output.write(renderer.render(snapshot.graph), failure_code=_EXIT_FAILURE)


def _add_diff(commands: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    parser = _subparser(
        commands,
        "diff",
        summary="draw what changed between two versions",
        description=(
            "Draw the graph with what changed marked on it: added and removed\n"
            "modules and dependencies, new and resolved cycles.\n\n"
            "Two ways to call it:\n"
            "  diff OLD.json NEW.json            two snapshots from 'draw -f json'\n"
            "  diff --base REV PROJECT_DIR       a git revision against the working\n"
            "                                    tree (or against --head REV)\n\n"
            "Exits like diff(1): 0 nothing changed, 1 something did, 2 an error.\n"
            "The diagram is written either way."
        ),
        examples=(
            "  arch-blueprint diff --base origin/main src -o diff.png\n"
            "  arch-blueprint diff --base v1.0 --head v2.0 src -m 'myapp.*'\n"
            "  arch-blueprint diff old.json new.json --changes-only\n"
            "  arch-blueprint diff --base origin/main src > diff.puml "
            "|| test $? -eq 1   # CI: fail on errors only"
        ),
        handler=_diff,
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        metavar="INPUT",
        help="OLD.json NEW.json, or PROJECT_DIR with --base",
    )
    parser.add_argument("--base", metavar="REV", help="Git revision to compare against")
    parser.add_argument(
        "--head",
        metavar="REV",
        help="Git revision to compare (default: the working tree)",
    )
    _add_modules_arg(
        parser,
        "With --base only. Default: every package in PROJECT_DIR on either side.",
    )
    _add_format_arg(
        parser,
        _DIFF_FORMATS,
        default=None,
        extra=" Default: puml, or what -o's extension says.",
    )
    _add_output_file_arg(parser, _DIFF_FORMATS)
    _add_cycle_details_arg(parser)
    _add_changes_only_arg(parser)


def _diff(args: argparse.Namespace) -> None:
    """``arch-blueprint diff``: draw what changed; exit 0 same, 1 different."""
    output = _output(args.format, args.output, _DIFF_FORMATS, code=_EXIT_DIFF_TROUBLE)
    if args.base is None:
        if len(args.inputs) != 2 or args.modules or args.head:
            _abort(
                "diff takes two snapshots (OLD.json NEW.json), "
                "or --base REV PROJECT_DIR [-m ...]",
                _EXIT_DIFF_TROUBLE,
            )
        old = _read_snapshot(args.inputs[0], _EXIT_DIFF_TROUBLE).graph
        new = _read_snapshot(args.inputs[1], _EXIT_DIFF_TROUBLE).graph
    else:
        if len(args.inputs) != 1:
            _abort("diff --base takes one PROJECT_DIR", _EXIT_DIFF_TROUBLE)
        old, new = _git_sides(args.inputs[0], args.modules, args.base, args.head)

    diff = diff_graphs(old, new, changes_only=args.changes_only)
    renderer = DIFF_RENDERERS[output.fmt](show_cycle_details=args.cycle_details)
    output.write(renderer.render(diff), failure_code=_EXIT_DIFF_TROUBLE)
    raise SystemExit(0 if diff.is_empty else _EXIT_DIFFERENT)


def _git_sides(
    project_dir: str,
    modules: Sequence[str],
    base: str,
    head: Optional[str],
) -> tuple[BlueprintGraph, BlueprintGraph]:
    """Build the graph at ``base`` and at ``head`` (default: the working tree)."""
    _check_project_dir(project_dir, _EXIT_DIFF_TROUBLE)
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
        if not modules:
            roots = sorted({*detect_roots(old_dir), *detect_roots(new_dir)})
            if not roots:
                _abort(
                    f"nothing to compare: {_layout_hint(project_dir)}",
                    _EXIT_DIFF_TROUBLE,
                )
            _note(f"comparing {', '.join(roots)} (all modules; narrow with -m)")
            modules = [f"{root}.**" for root in roots]
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


def _add_history(
    commands: "argparse._SubParsersAction[argparse.ArgumentParser]",
) -> None:
    parser = _subparser(
        commands,
        "history",
        summary="draw one diagram per commit that changed the graph",
        description=(
            "Walk the branch's first-parent history and, for every commit that\n"
            "changed the graph, write the full diagram and the diff against the\n"
            "previous one: numbered files to leaf through, plus an index.md.\n"
            "Commits that leave the graph alone are skipped.\n\n"
            "Snapshots and images are cached, so a rerun only does what is missing."
        ),
        examples=(
            "  arch-blueprint history src                    every package in src/\n"
            "  arch-blueprint history src myapp -f puml-png  images (needs plantuml)\n"
            "  arch-blueprint history src app1 app2 -m 'app1.*' -m 'app2.core.*'\n"
            "  arch-blueprint history src myapp --base v1.0 -o album"
        ),
        handler=_history,
    )
    parser.add_argument(
        "project_dir",
        metavar="PROJECT_DIR",
        help="The directory the packages sit in; must be inside a git repository",
    )
    parser.add_argument(
        "roots",
        nargs="*",
        metavar="ROOT",
        help=(
            "Top-level package(s) to draw, each whole unless -m narrows it "
            "(default: every package in PROJECT_DIR at --head)"
        ),
    )
    _add_modules_arg(parser, "Each must lie under one of the ROOTs.")
    parser.add_argument(
        "--base",
        metavar="REV",
        help="First commit of the album (default: the start of history)",
    )
    parser.add_argument(
        "--head",
        metavar="REV",
        default="HEAD",
        help="Last commit of the album (default: HEAD)",
    )
    parser.add_argument(
        "--output",
        "-o",
        metavar="DIR",
        default="blueprint-history",
        help="Directory to write the album to (default: ./blueprint-history)",
    )
    parser.add_argument(
        "--cache-dir",
        metavar="DIR",
        default=DEFAULT_CACHE_DIR,
        help=f"Snapshot and image cache (default: ./{DEFAULT_CACHE_DIR})",
    )
    _add_format_arg(
        parser,
        _DIAGRAM_FORMATS,
        default="puml",
        extra=" An album holds one kind of file. Default: puml.",
    )
    parser.add_argument(
        "--scale",
        type=_positive_float,
        metavar="FACTOR",
        help=(
            "d2-png only: scale of the images, e.g. 0.5 (default: d2's own). A "
            "diagram too large for d2 to rasterize is halved automatically."
        ),
    )
    _add_metric_arg(parser)
    _add_cycle_details_arg(parser)
    _add_changes_only_arg(parser)


def _history(args: argparse.Namespace) -> None:
    """``arch-blueprint history``: a diagram per commit that changed the graph."""
    diagram_fmt, as_images = _DIAGRAM_FORMATS[args.format]
    registry = default_registry()
    renderer = _renderer(
        diagram_fmt,
        args.metrics,
        cycle_details=args.cycle_details,
        registry=registry,
    )
    diff_renderer = DIFF_RENDERERS[diagram_fmt](show_cycle_details=args.cycle_details)
    if args.scale is not None and not (
        as_images and IMAGE_RENDERERS[diagram_fmt].scalable
    ):
        scalable = [
            f"{fmt}-{IMAGE_EXTENSION}"
            for fmt, cls in IMAGE_RENDERERS.items()
            if cls.scalable
        ]
        _abort(f"--scale applies to -f {' / '.join(scalable)}", _EXIT_USAGE)
    images = (
        _image_renderer(diagram_fmt, args.scale, _EXIT_USAGE) if as_images else None
    )
    _check_project_dir(args.project_dir, _EXIT_USAGE)

    try:
        roots = args.roots or _history_roots(args.project_dir, args.head)
        patterns = _history_patterns(roots, args.modules)
        commits = first_parent_commits(args.project_dir, args.base, args.head)
        if not commits:
            _abort(f"no commits touch {args.project_dir}", _EXIT_USAGE)
        cache = SnapshotCache(Path(args.cache_dir))
        statuses: dict[str, str] = {}
        frames = collect(
            commits,
            lambda commit: _history_snapshot(
                args.project_dir,
                patterns,
                commit,
                cache,
                registry,
                statuses,
            ),
            _progress_reporter(len(commits), statuses),
        )
    except GitError as error:
        _abort(str(error), _EXIT_USAGE)
    if not frames:
        _no_match(patterns)

    out_dir = Path(args.output)
    album = pages(
        frames,
        lambda snapshot: renderer.render(snapshot.graph),
        lambda old, new: diff_renderer.render(
            diff_graphs(old.graph, new.graph, changes_only=args.changes_only),
        ),
    )
    if images is None:
        write(frames, album, out_dir, diagram_fmt)
        failed: list[tuple[str, str]] = []
    else:
        image_cache = ImageCache(Path(args.cache_dir))
        drawn, failed = draw(album, diagram_fmt, images, image_cache)
        write(frames, album, out_dir, IMAGE_EXTENSION, drawn)
    _emit(
        sys.stderr,
        f"{len(frames)} frames from {len(commits)} commits in {out_dir}",
    )
    if failed:
        for name, reason in failed:
            _emit(sys.stderr, f"{_PROG}: {name}: {reason}")
        _abort(
            f"{len(failed)} of {len(album)} images failed; the rest and the "
            "cached snapshots are kept — rerun to retry",
            _EXIT_FAILURE,
        )


def _history_roots(project_dir: str, head: str) -> list[str]:
    """No ROOT given: every package the project has at ``head``."""
    with checkout(project_dir, head) as tree:
        roots = detect_roots(tree)
    if not roots:
        _abort(f"no Python packages in {project_dir} at {head}", _EXIT_USAGE)
    _note(f"drawing {', '.join(roots)} (as of {head}; name ROOTs to choose)")
    return roots


def _history_patterns(roots: Sequence[str], modules: Sequence[str]) -> list[str]:
    """``-m`` as given, each under one of the roots; else everything under each."""
    if not modules:
        return [f"{root}.**" for root in roots]
    outside = [
        pattern
        for pattern in modules
        if not any(pattern == root or pattern.startswith(f"{root}.") for root in roots)
    ]
    if outside:
        _abort(
            f"-m {', '.join(map(repr, outside))} is under none of the roots "
            f"{', '.join(map(repr, roots))}",
            _EXIT_USAGE,
        )
    return list(modules)


def _image_renderer(fmt: str, scale: Optional[float], code: int) -> ImageRenderer:
    renderer_cls = IMAGE_RENDERERS[fmt]
    executable = shutil.which(renderer_cls.binary)
    if executable is None:
        _abort(
            f"-f {fmt}-{IMAGE_EXTENSION} needs '{renderer_cls.binary}' on PATH",
            code,
        )
    return renderer_cls(executable, scale, lambda line: _emit(sys.stderr, line))


def _positive_float(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        value = 0.0
    if not value > 0:
        msg = f"expected a positive number, got {text!r}"
        raise argparse.ArgumentTypeError(msg)
    return value


def _history_snapshot(
    project_dir: str,
    patterns: Sequence[str],
    commit: Commit,
    cache: SnapshotCache,
    registry: MetricRegistry,
    statuses: dict[str, str],
) -> Optional[Snapshot]:
    """The snapshot at ``commit``: from the cache, or built and then cached.

    Every metric is computed, as for ``-f json``, so any ``--metric`` can be
    drawn from a cached snapshot. A commit that cannot be analyzed (broken code
    somewhere in the history) is reported and skipped, not fatal.
    """
    key = cache.key(tree_id(project_dir, commit.sha), patterns)
    text = cache.get(key)
    if text is not None:
        try:
            snapshot = load(text)
        except SnapshotError:
            pass  # damaged entry: build it again
        else:
            statuses[commit.sha] = _NO_SOURCE if not snapshot.graph.nodes else "cached"
            return snapshot
    with checkout(project_dir, commit.sha) as root:
        # A root the commit does not have yet is not an error: it appears later.
        present = [p for p in patterns if has_source(root, _root_of(p))]
        try:
            graph = _history_graph(root, present, registry)
        except (ImportError, OSError, GrimpException) as error:
            statuses[commit.sha] = f"skipped ({error})"
            return None
    names = registry.names()
    cache.put(key, dump(graph, names))
    statuses[commit.sha] = _NO_SOURCE if not graph.nodes else "built"
    return Snapshot(graph, frozenset(names))


#: A commit where no root has code to analyze yet — the start of a project.
_NO_SOURCE: Final = "no source yet"


def _history_graph(
    project_dir: str,
    patterns: Sequence[str],
    registry: MetricRegistry,
) -> BlueprintGraph:
    if not patterns:
        return BlueprintGraph(nodes=[], edges=frozenset())
    # No grimp cache: git archive stamps every file with the commit time.
    return build_graph(
        project_dir,
        patterns,
        ModuleExtractor,
        registry,
        None,
        use_cache=False,
    )


def _root_of(pattern: str) -> str:
    """The literal module path a pattern starts with, up to its first wildcard."""
    parts = []
    for part in pattern.split("."):
        if "*" in part:
            break
        parts.append(part)
    return ".".join(parts)


def _progress_reporter(
    total: int,
    statuses: dict[str, str],
) -> Callable[[Commit, Optional[Frame]], None]:
    counter = iter(range(1, total + 1))

    def report(commit: Commit, frame: Optional[Frame]) -> None:
        status = statuses.get(commit.sha, "")
        line = f"[{next(counter)}/{total}] {commit.short} {commit.date} {status}"
        if frame is not None:
            line = f"{line}: {frame.stem}"
        elif status != _NO_SOURCE and not status.startswith("skipped"):
            line = f"{line}: unchanged"
        _emit(sys.stderr, line)

    return report


# --- entry point ----------------------------------------------------------


_COMMANDS: Final = MappingProxyType(
    {
        "draw": _add_draw,
        "diff": _add_diff,
        "history": _add_history,
    },
)


def _version() -> str:
    try:
        return metadata.version(_PROG)
    except metadata.PackageNotFoundError:  # running from a bare checkout
        return "unknown"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=_PROG,
        description=(
            "Draw the import graph of a Python project as a diagram — PlantUML\n"
            "or D2 source, or a PNG — and see how it changes over time."
        ),
        epilog=(
            "examples:\n"
            "  arch-blueprint draw src                      every package in src/, "
            "as PlantUML\n"
            "  arch-blueprint draw src -m 'myapp.**' -o arch.png\n"
            "                                               one package, as an "
            "image (needs plantuml)\n"
            "  arch-blueprint diff --base origin/main src   what this branch "
            "changed\n"
            "  arch-blueprint history src -f d2-png         a picture per commit "
            "that changed it\n\n"
            f"Run '{_PROG} COMMAND -h' for a command's options and examples."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {_version()}")
    parser.add_argument(
        "--list-metrics",
        action=_ListMetrics,
        help="List the metrics '--metric' can show, then exit",
    )
    commands = parser.add_subparsers(
        title="commands",
        dest="command",
        required=True,
        metavar="COMMAND",
    )
    for add_command in _COMMANDS.values():
        add_command(commands)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
    """Main entry point for the arch_blueprint CLI."""
    args = sys.argv[1:] if argv is None else list(argv)
    parser = _parser()
    if not args:
        parser.print_help(sys.stderr)
        raise SystemExit(_EXIT_USAGE)
    if args[0] == "render":
        _abort(
            f"'render' is part of 'draw' now — run: "
            f"{_PROG} draw {shlex.join(args[1:])}",
            _EXIT_USAGE,
        )
    if args[0] not in _COMMANDS and Path(args[0]).is_dir():
        # The command used to be implicit: ``arch-blueprint DIR -m ...``.
        _abort(
            f"a command comes first now — run: {_PROG} draw {shlex.join(args)}",
            _EXIT_USAGE,
        )
    namespace = parser.parse_args(args)
    namespace.handler(namespace)


if __name__ == "__main__":
    main()
