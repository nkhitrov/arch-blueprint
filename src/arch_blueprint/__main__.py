import argparse
import functools
import shutil
import sys
from collections.abc import Callable, Iterable, Sequence
from contextlib import ExitStack
from pathlib import Path
from types import MappingProxyType
from typing import Final, NoReturn, Optional, TextIO

from grimp.exceptions import GrimpException

from arch_blueprint.blueprint import build_graph
from arch_blueprint.diff import DIFF_RENDERERS, diff_graphs
from arch_blueprint.domain.graph import BlueprintGraph
from arch_blueprint.extract import DEFAULT_LINK_LEVEL, LINK_LEVELS, ModuleExtractor
from arch_blueprint.extract.base import GraphExtractor
from arch_blueprint.extract.source import GrimpSource
from arch_blueprint.git import (
    Commit,
    GitError,
    checkout,
    first_parent_commits,
    has_source,
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
from arch_blueprint.history.album import IMAGE_EXTENSION
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

#: ``history -f``: each diagram format as sources, and as images where a tool
#: draws them — an album holds one kind of file, so it is easy to leaf through.
_HISTORY_FORMATS: Final[MappingProxyType[str, tuple[str, bool]]] = MappingProxyType(
    {
        **{fmt: (fmt, False) for fmt in _RENDERERS},
        **{f"{fmt}-{IMAGE_EXTENSION}": (fmt, True) for fmt in IMAGE_RENDERERS},
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


def _add_links_arg(parser: argparse.ArgumentParser) -> None:
    """For every command that builds a graph: what an arrow connects."""
    choices = list(LINK_LEVELS)
    parser.add_argument(
        "--links",
        default=DEFAULT_LINK_LEVEL,
        choices=choices,
        metavar="LEVEL",
        help=(
            "What an arrow connects: 'namespace' aggregates imports to the "
            "namespaces where two modules' paths diverge (a.b.c -> a.d.e is "
            "drawn a.b -> a.d), 'module' draws them node to node. "
            f"Possible values: {choices} (default: {DEFAULT_LINK_LEVEL})"
        ),
    )


def _extractor(links: str) -> Callable[[GrimpSource], GraphExtractor]:
    return functools.partial(ModuleExtractor, level=LINK_LEVELS[links])


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


def _add_quick_look_cycle_details_arg(parser: argparse.ArgumentParser) -> None:
    """For ``diff`` and ``history``: a quick look, so the import notes are opt-in.

    A note lists every import on both sides of a cycle — detail for digging
    into one, noise when the question is what changed.
    """
    parser.add_argument(
        "--cycle-details",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Add a note listing the imports on each cycle",
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
    links: str,
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
            _extractor(links),
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
            "Subcommands: 'render' draws a snapshot, 'diff' compares two, "
            "'history' draws one diagram per commit that changed the graph."
        ),
    )
    parser.add_argument(
        "project_dir",
        type=str,
        help="Path to root directory of target project",
    )
    _add_modules_arg(parser, required=True)
    _add_links_arg(parser)
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
        graph = _build(
            args.project_dir,
            args.modules,
            None,
            links=args.links,
            failure_code=_EXIT_FAILURE,
        )
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
        links=args.links,
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
    _add_links_arg(parser)
    _add_format_arg(parser, DIFF_RENDERERS)
    _add_quick_look_cycle_details_arg(parser)
    _add_changes_only_arg(parser)
    args = parser.parse_args(argv)

    if args.base is None:
        if (
            len(args.inputs) != 2
            or args.modules
            or args.head
            or args.links != DEFAULT_LINK_LEVEL
        ):
            _abort(
                "diff takes two snapshots (OLD.json NEW.json), "
                "or --base REV PROJECT_DIR -m ... [--links LEVEL]",
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
        old, new = _git_sides(
            args.inputs[0],
            args.modules,
            args.base,
            args.head,
            links=args.links,
        )

    diff = diff_graphs(old, new, changes_only=args.changes_only)
    renderer = DIFF_RENDERERS[args.format](show_cycle_details=args.cycle_details)
    _write(renderer.render(diff))
    raise SystemExit(0 if diff.is_empty else _EXIT_DIFFERENT)


def _git_sides(
    project_dir: str,
    modules: Sequence[str],
    base: str,
    head: Optional[str],
    *,
    links: str,
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
        old = _side(old_dir, old_modules, links)
        new = _side(new_dir, new_modules, links)
    if not old.nodes and not new.nodes:
        _no_match(modules)
    return old, new


def _side(project_dir: str, modules: Sequence[str], links: str) -> BlueprintGraph:
    if not modules:  # this side has none of the selected packages
        return BlueprintGraph(nodes=[], edges=frozenset())
    # No metrics: a diff compares structure only. No cache: grimp would take two
    # checkouts whose files share an mtime (git archive stamps the commit time)
    # for one and the same project.
    return _build(
        project_dir,
        modules,
        (),
        links=links,
        failure_code=_EXIT_DIFF_TROUBLE,
        use_cache=False,
    )


def _history_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="arch-blueprint history",
        description=(
            "Walk the first-parent history of the branch and draw, for every "
            "commit that changed the graph, the full diagram and the diff "
            "against the previous frame — numbered files to leaf through. "
            "Snapshots are cached, so a rerun (after a failed image render, "
            "say) builds only what it has not built before."
        ),
    )
    parser.add_argument("project_dir", help="Path to root directory of target project")
    parser.add_argument(
        "roots",
        nargs="+",
        metavar="ROOT",
        help="Top-level package(s) to graph; without -m, everything under each",
    )
    _add_modules_arg(parser, required=False)
    _add_links_arg(parser)
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
        help=f"Snapshot cache, read and written (default: ./{DEFAULT_CACHE_DIR})",
    )
    _add_format_arg(parser, _HISTORY_FORMATS)
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
    _add_quick_look_cycle_details_arg(parser)
    _add_changes_only_arg(parser)
    return parser


def _history(argv: Sequence[str]) -> None:
    """``arch-blueprint history``: a diagram per commit that changed the graph."""
    args = _history_parser().parse_args(argv)

    patterns = _history_patterns(args.roots, args.modules)
    diagram_fmt, as_images = _HISTORY_FORMATS[args.format]
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
            f"{fmt}-png" for fmt, cls in IMAGE_RENDERERS.items() if cls.scalable
        ]
        _abort(f"--scale applies to -f {' / '.join(scalable)}", _EXIT_USAGE)
    images = _image_renderer(diagram_fmt, args.scale) if as_images else None
    if not Path(args.project_dir).is_dir():
        _abort(f"no such project directory: {args.project_dir}", _EXIT_USAGE)

    try:
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
                args.links,
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
            _emit(sys.stderr, f"arch-blueprint: {name}: {reason}")
        _abort(
            f"{len(failed)} of {len(album)} images failed; the rest and the "
            "cached snapshots are kept — rerun to retry",
            _EXIT_FAILURE,
        )


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


def _image_renderer(fmt: str, scale: Optional[float]) -> ImageRenderer:
    renderer_cls = IMAGE_RENDERERS[fmt]
    executable = shutil.which(renderer_cls.binary)
    if executable is None:
        _abort(
            f"-f {fmt}-{IMAGE_EXTENSION} needs '{renderer_cls.binary}' on PATH",
            _EXIT_USAGE,
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
    links: str,
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
    key = cache.key(tree_id(project_dir, commit.sha), patterns, links)
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
            graph = _history_graph(root, present, links, registry)
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
    links: str,
    registry: MetricRegistry,
) -> BlueprintGraph:
    if not patterns:
        return BlueprintGraph(nodes=[], edges=frozenset())
    # No grimp cache: git archive stamps every file with the commit time.
    return build_graph(
        project_dir,
        patterns,
        _extractor(links),
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


_SUBCOMMANDS: Final[MappingProxyType[str, Callable[[Sequence[str]], None]]] = (
    MappingProxyType({"render": _render, "diff": _diff, "history": _history})
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
