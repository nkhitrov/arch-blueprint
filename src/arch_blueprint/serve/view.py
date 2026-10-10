"""One view of the viewer, as the JSON its page draws.

Every graph decision is made here, by the pipeline the CLI runs — extract,
fold, compute metrics, analyze — and the frames and labels by the layout the
diagrams use. The page only draws what it is given, so it never re-derives a
link, a cycle or a label in JavaScript.
"""

from __future__ import annotations

import shlex
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Optional

from arch_blueprint.analyze import analyze
from arch_blueprint.domain.graph import BlueprintGraph, Edge, cycle_metric_values
from arch_blueprint.extract import LINK_LEVELS
from arch_blueprint.extract.levels import module_level
from arch_blueprint.extract.module_extractor import ModuleExtractor
from arch_blueprint.extract.source import GrimpSource
from arch_blueprint.metrics import MetricRegistry
from arch_blueprint.renderer.base import CYCLE_HIGHLIGHT_COLOR, DEFAULT_OPTIONS
from arch_blueprint.renderer.layout import Frame, Layout, LayoutItem
from arch_blueprint.serve.fold import fold

#: The levels a view is drawn at. Both are nested — a viewer explores frames —
#: so ``class`` is the CLI's ``class-grouped``.
VIEW_LEVELS: Final = ("module", "class")

#: The ``--links`` value that draws a view's arrows from the CLI.
_CLI_LEVELS: Final = {"module": "module", "class": "class-grouped"}

_PROG: Final = "arch-blueprint"

FOLDED_NOTE: Final = (
    "# folded packages have no CLI equivalent; this draws them unfolded"
)


class NoModulesError(ValueError):
    """The patterns of a view select no module: nothing to draw."""

    def __init__(self, patterns: Sequence[str]) -> None:
        self.patterns = tuple(patterns)
        listed = ", ".join(repr(pattern) for pattern in patterns)
        super().__init__(f"no modules matched: {listed}")


@dataclass(frozen=True)
class ViewRequest:
    """What the page asks to see.

    ``patterns`` are ``-m`` patterns; ``folded`` the packages drawn as one node
    (module level only — a class view ignores them); ``links`` one of
    :data:`VIEW_LEVELS`.
    """

    patterns: tuple[str, ...]
    folded: frozenset[str] = field(default_factory=frozenset)
    links: str = "module"

    def __post_init__(self) -> None:
        if not self.patterns:
            msg = "a view needs at least one pattern"
            raise ValueError(msg)
        if self.links not in VIEW_LEVELS:
            msg = f"links must be one of {', '.join(VIEW_LEVELS)}, not {self.links!r}"
            raise ValueError(msg)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> ViewRequest:
        """The request a page sent; ``ValueError`` for anything malformed."""
        return cls(
            patterns=tuple(_strings(data, "patterns")),
            folded=frozenset(_strings(data, "folded", required=False)),
            links=str(data.get("links", "module")),
        )


def _strings(data: Mapping[str, Any], key: str, *, required: bool = True) -> list[str]:
    value = data.get(key)
    if value is None and not required:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        msg = f"{key} must be a list of strings"
        raise ValueError(msg)
    return value


def build_graph_for(source: GrimpSource, request: ViewRequest) -> BlueprintGraph:
    """The graph of a view, before metrics and analysis."""
    if request.links == "module":
        extracted = ModuleExtractor(source, level=module_level).extract()
        return fold(extracted, request.folded)
    return LINK_LEVELS["class-grouped"].extractor(source).extract()


def build_view(
    source: GrimpSource,
    request: ViewRequest,
    registry: MetricRegistry,
) -> dict[str, Any]:
    """The JSON of one view; :class:`NoModulesError` when it would be empty."""
    graph = build_graph_for(source, request)
    if not graph.nodes:
        raise NoModulesError(request.patterns)
    registry.compute(graph, None)
    analyze(graph)

    node_names = [m.name for m in registry.node_metrics() if m.render is not None]
    link_names = [m.name for m in registry.link_metrics() if m.render is not None]
    ids = [node.id for node in graph.nodes]
    endpoints = {end for link in graph.links for end in (link.source, link.target)}
    layout = Layout.build(ids, endpoints, nested=True)
    parents = dict(_parents(layout.items, None))

    paired = {frozenset((c.endpoint_from, c.endpoint_to)) for c in graph.cycles}
    on_tangle = {
        (link.source, link.target) for tangle in graph.tangles for link in tangle.links
    }
    folded = request.folded if request.links == "module" else frozenset()
    nodes = []
    for node in graph.nodes:
        values = graph.node_metrics.get(node.id, {})
        depth = int(values.get("depth", 0))
        nodes.append(
            {
                "id": node.id,
                "label": layout.label(node.id),
                "kind": node.kind.letter,
                "parent": parents.get(node.id),
                "folded": node.id in folded,
                "depth": depth,
                "color": DEFAULT_OPTIONS.get_color_for_depth(depth),
                "metrics": {
                    name: values[name] for name in node_names if name in values
                },
            },
        )
    links = [
        {
            "source": link.source,
            "target": link.target,
            "cyclic": (link.source, link.target) in on_tangle,
            "metrics": _pick(
                graph.link_metrics.get((link.source, link.target)),
                link_names,
            ),
            "imports": _imports(link.edges),
        }
        for link in sorted(graph.links, key=lambda link: (link.source, link.target))
        if frozenset((link.source, link.target)) not in paired
    ]
    cycles = [
        {
            "a": cycle.endpoint_from,
            "b": cycle.endpoint_to,
            "metrics": _pick(
                cycle_metric_values(
                    graph.link_metrics,
                    cycle.endpoint_from,
                    cycle.endpoint_to,
                ),
                link_names,
            ),
            "imports": _imports(cycle.forward_edges | cycle.backward_edges),
        }
        for cycle in graph.cycles
    ]
    return {
        "nodes": nodes,
        "frames": [
            {
                "id": frame.namespace,
                "label": frame.label,
                "parent": parents.get(frame.namespace),
            }
            for frame in _frames(layout.items)
        ],
        "links": links,
        "cycles": cycles,
        "tangles": [{"members": list(tangle.members)} for tangle in graph.tangles],
        "metrics": {"node": node_names, "link": link_names},
        "cycleColor": CYCLE_HIGHLIGHT_COLOR,
    }


def default_folds(patterns: Iterable[str], packages: Collection[str]) -> frozenset[str]:
    """What a view opens with folded: the packages just below each pattern's stem.

    ``app.**`` and ``app.*`` fold ``app``'s subpackages, ``app.core.*`` those of
    ``app.core`` — a small picture to unfold from, never the selection itself
    folded into one box. A bare name or a partial wildcard (``app.c*``) folds
    nothing.
    """
    folded: set[str] = set()
    for pattern in patterns:
        stem, _, last = pattern.rpartition(".")
        if last not in {"*", "**"} or not stem or "*" in stem:
            continue
        folded |= {name for name in packages if name.rpartition(".")[0] == stem}
    return frozenset(folded)


def cli_command(project_dir: str, request: ViewRequest, metric: Optional[str]) -> str:
    """The ``draw`` command closest to a view: same modules, arrows and metric.

    ``draw`` folds nothing: a view with folded packages gets a first line saying
    the command draws them unfolded.
    """
    args = [_PROG, "draw", project_dir]
    for pattern in request.patterns:
        args += ["-m", pattern]
    args += ["--links", _CLI_LEVELS[request.links]]
    if metric is not None:
        args += ["--metric", metric]
    command = shlex.join(args)
    if request.folded and request.links == "module":
        return f"{FOLDED_NOTE}\n{command}"
    return command


def _parents(
    items: Sequence[LayoutItem],
    parent: Optional[str],
) -> Iterator[tuple[str, Optional[str]]]:
    """``(name, enclosing frame)`` for every node and frame of a layout."""
    for item in items:
        if isinstance(item, Frame):
            yield item.namespace, parent
            yield from _parents(item.items, item.namespace)
        else:
            yield item, parent


def _frames(items: Sequence[LayoutItem]) -> Iterator[Frame]:
    """Every frame, outer before inner, in drawing order."""
    for item in items:
        if isinstance(item, Frame):
            yield item
            yield from _frames(item.items)


def _pick(values: Optional[Mapping[str, Any]], names: Sequence[str]) -> dict[str, Any]:
    if not values:
        return {}
    return {name: values[name] for name in names if name in values}


def _imports(edges: frozenset[Edge]) -> list[list[str]]:
    return sorted([edge.source, edge.target] for edge in edges)
