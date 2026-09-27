# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

`arch-blueprint` is a CLI that generates architecture diagrams (PlantUML or D2) from a Python
project's module import graph. It is built on top of [`grimp`](https://github.com/seddonym/grimp),
which constructs the import graph.

## Commands

This project uses `uv` for environment and dependency management.

- Install/sync deps: `uv sync` (CI uses `uv sync --locked`)
- Run all checks (what CI runs): `uv run pre-commit run -a` (lint, format, mypy, pytest)
- Run the test suite only: `uv run pytest`
- Format: `uv run ruff format`
- Lint (with autofix): `uv run ruff check --fix src tests`
- Type-check (strict mypy): `uv run mypy ./src ./tests`
- Run the CLI against a project: `uv run arch-blueprint draw <project_dir> [-m '<pattern>'] [-f FMT] [-o FILE]`
  - Example: `uv run arch-blueprint draw src -m 'arch_blueprint.*'`
  - Every command is explicit (`draw`, `diff`, `history`). The old implicit form
    `arch-blueprint <dir> -m ...` and the old `render SNAPSHOT` are gone; each gets an exit-2 hint
    naming the `draw` command to run instead. `draw` takes a project directory or a snapshot file
    (an existing file, or any `*.json`).
  - Without `-m`, `draw` and `diff --base` draw every package in `<project_dir>` whole
    (`extract/layout.py:detect_roots` → `pkg.**`, noted on stderr); `history` without ROOTs does
    the same at `--head`. A src-layout root (`src/` a namespace dir holding packages) is refused
    with a hint rather than drawn as `src.myapp`.
  - `-o FILE` writes to a file; without `-f` its extension picks the format (`.puml`, `.d2`,
    `.json`, `.png` → `puml-png`). `-f puml-png` / `d2-png` draw an image through the
    `IMAGE_RENDERERS` tool and require `-o`.
  - Graphing **this** project is a special case: `arch_blueprint` is already in `sys.modules`
    (the CLI *is* it), so `find_spec` resolves to the running copy whatever `<project_dir>` says.
    To graph a different checkout, put it first on `PYTHONPATH` so that copy is the one running.
  - `--modules`/`-m` accepts grimp glob patterns (`pkg.*`, `pkg.**`, `pkg.*.*.models.*`).
  - `-m` can be **repeated** to graph several top-level packages at once and draw the links
    between them — useful when `<project_dir>` is a root with no `__init__.py` containing sibling
    packages (e.g. `-m 'app1.*' -m 'app2.*'`). A cross-package link is drawn only when both
    endpoints belong to the selected set — which includes a dependency *on* a package whose
    children were selected, since `pkg.*` never selects `pkg` itself.
  - `--format`/`-f` defaults to `puml`. The notes listing a cycle's imports are opt-in in every
    command (`--cycle-details`), for a pair and a longer cycle alike. `diff` and `history` draw the diff over the whole graph;
    `--changes-only` draws just the changes and the modules they touch.
  - `--links namespace|module` (default `namespace`) chooses what an arrow connects: the
    namespaces where two modules' paths diverge, or the nodes themselves. Accepted by every command
    that *builds* a graph (`draw PROJECT_DIR`, `diff --base`, `history`), not by `draw SNAPSHOT`
    or a snapshot-file `diff` (`_reject_links`) — a snapshot records the level it was built at. Even an explicit
    `--links namespace` is rejected there (the parser default is `None`, resolved by
    `_link_level`), and a diff of two snapshots of different levels is exit 2.
    A level also says how it is drawn (`Level.nested` → `RendererOptions.nested`): `module` is
    flat — every node one box under its full name (PlantUML `set separator none`, d2 quoted keys),
    and every endpoint no node carries (a facade an arrow ends on) is declared as a node of its own
    (`flat_nodes`, from the endpoints — a facade above another facade has no group of its own). Containers only lengthen node-to-node arrows.
  - `--metric NAME` (repeatable) displays a metric. A node metric (`fan_in`, `fan_out`,
    `instability`) renders as a block on each node; a link metric (`edge_weight`) renders as a label
    on each connection, including cyclic ones (as `forward/backward`). An unknown name is an error,
    not a silent no-op. `diff` and `history` take it too: a changed value reads `old → new (±d)`.
- Snapshot / draw a snapshot / diff (see **Snapshot and diff** below):
  - `uv run arch-blueprint draw <project_dir> -m '<pattern>' -o graph.json` — graph snapshot.
  - `uv run arch-blueprint draw graph.json [-f FMT] [-o FILE] [--metric NAME]` — draw a snapshot.
  - `uv run arch-blueprint diff OLD.json NEW.json [-f FMT] [-o FILE] [--metric NAME]` — draw what
    changed.
  - `uv run arch-blueprint diff --base REV [--head REV] <project_dir> [-m '<pattern>']` — both sides
    built from git (`--head` defaults to the working tree).
  - `uv run arch-blueprint history <project_dir> [ROOT ...] [-m '<pattern>'] [--base REV]
    [--head REV] [-o DIR] [-f puml|d2|puml-png|d2-png]` — an album: a diagram and a diff per commit
    that changed the graph (see **History album** below).
- Runnable example fixture: `uv run arch-blueprint draw examples/project_root -m 'app1.*' -m 'app2.*' -m 'plugins.**'`
  (see `examples/README.md`) — exercises multi-root cross-links and namespace-package handling.

CI (`.github/workflows/test.yml`) has two jobs: a single-version `lint` job (`pre-commit`, skipping
pytest) and a `test` matrix running `pytest` across Python 3.9–3.14 on Linux plus one
`windows-latest` leg — that console is not UTF-8, and diagram output contains arrows, so an encoding
regression is invisible on Linux alone. Runs on push to `master` and on PRs.

### Tests

`tests/` holds the suite, one file per layer under test:

- `test_domain.py` — link aggregation, `CycleAnalyzer`, `GroupAnalyzer`.
- `test_metrics.py` — metric computation, registry routing, render plugins, `RenderPlan` validation.
- `test_renderers.py` — both renderers **in-process** (build a graph, render it, assert on the text).
- `test_source.py` — `GrimpSource`, interpreter-state hygiene, extraction, `detect_roots`.
- `test_cli.py` — exit codes, stderr messages and hints, output encoding, `-o` / PNG (through a
  stand-in tool from `conftest.stand_in_tool`), help / `--version` / `--list-metrics`.
- `test_golden_puml.py` / `test_golden_d2.py` — run the CLI as a subprocess over every scenario in
  `tests/conftest.py:SCENARIOS` and assert byte-exact output against `tests/golden/<fmt>/`. When
  output changes *intentionally*, regenerate the affected golden.
- `test_golden_structure.py` — invariants the goldens must satisfy, not just their bytes: every link
  endpoint is declared, and no package wraps a class of its own name. Covers diff goldens too.
- `test_snapshot.py` — golden snapshots (`tests/golden/json/<selection>.json`, one per
  `conftest.py:SELECTIONS`), and the key invariant: `draw` of a snapshot equals every
  `tests/golden/<fmt>/` diagram byte for byte. Plus validation errors.
- `test_diff.py` — `diff_graphs` logic and the diff renderers in-process.
- `test_golden_diff.py` — `diff` over `conftest.py:DIFF_CASES` against `tests/golden/diff/<fmt>/`,
  including the exit code. Inputs are golden snapshots or small edits of them in
  `tests/fixtures/diff/`.
- `test_diff_git.py` — `diff --base` end to end in a throwaway git repository.
- `test_history.py` — `history` end to end over a throwaway repository's commits (frames, cache,
  stale frames, `*-png` through a stand-in `plantuml` / `d2` on `PATH`), plus `collect` and the caches
  in-process.

A scenario is a `Selection` (project + `-m` patterns + `build_args` such as `--links module` — what
the snapshot golden is keyed by) plus `render_args` (drawing-only options, passed unchanged when
drawing the snapshot). A golden holding cycle notes has `CYCLE_DETAILS` in its `render_args`.

A hand-built `BlueprintGraph` has **empty `cycles` and `groups`** until the analyze step fills them.
A renderer test that needs either must populate them explicitly, or it will silently assert against
ungrouped nodes and plain arrows.

Fixtures: `examples/project_root` (multi-root + PEP 420 namespace package), `tests/fixtures/cyclic`
(a module cycle), `tests/fixtures/deep_ns` (single root whose link endpoints collide with node ids
and nest), `tests/fixtures/init_imports` (a package re-exporting through `__init__.py`),
`tests/fixtures/ancestor_dep` (an import of a package facade),
`tests/fixtures/package_nodes` (nodes that are packages, so every edge targets a submodule),
`tests/fixtures/diff` (snapshot edits used as diff inputs, every metric computed into them like a
`-o graph.json` snapshot; `cyclic_weighted.json` is `cyclic` plus one import inside an existing link
— a metric-only change; regenerate them if the snapshot format or a metric's counting changes). Fixture projects are excluded from
ruff and mypy — they are analysis subjects, not code we ship.

## Git conventions

- Do **not** add self-references to commit messages or PR bodies — no `Co-Authored-By: Claude`
  trailers, no "Generated with Claude Code" lines, no mention of the assistant. Keep commit
  messages about the change only.

## Architecture

`build_graph(...)` (`src/arch_blueprint/blueprint.py`) runs everything up to rendering: source →
extract → metrics → `analyze(graph)`. `ArchBlueprint` is a thin orchestrator around it (`build()`,
`render(graph)`, `run()`). The CLI calls `build_graph` directly because it must see the graph — an
empty selection is a user error, not a diagram — and because a snapshot or a diff side has no
renderer. `analyze()` (`analyze/__init__.py`) derives cycles then groups, and is the one place that
happens, for a fresh extraction and a loaded snapshot alike.

1. **Source** (`extract/source.py`) — `GrimpSource` owns all grimp/`sys.path` mechanics: resolves
   every `--modules` pattern to a top-level package and builds the grimp graph (multiple roots
   supported). It handles PEP 420 namespace packages grimp can't build directly (expands them, skips
   ones with no analyzable source with a stderr warning). It exposes `selected_modules()` and
   `imports_of(module)` (a module's own imports **and** its descendants').
   Resolution uses `importlib.util.find_spec`, never `import_module`: analysing a project must not
   execute it. The project dir goes to the **front** of `sys.path` — the project is usually also
   installed in the venv, and an older checkout of it (`diff --base`) must not resolve to the
   installed, current copy. `sys.path` and `sys.modules` are restored afterwards, which is what
   makes the library re-runnable in one process — restoring the path alone is not enough, since
   `sys.modules` is consulted first. `use_cache=False` bypasses grimp's cache, which is keyed by
   module **name** and mtime, not path: `git archive` stamps every file with the commit time, so two
   revisions committed within a second would otherwise share one graph. Diff sides always opt out.
2. **Extract** (`extract/`) — a `GraphExtractor` (Protocol in `extract/base.py`, no constructor
   dictated) turns the source into a `BlueprintGraph`. `ModuleExtractor` emits one node per selected
   module, and an edge when a selected module imports another across a boundary of its link level.
   A level (`extract/levels.py`, registry `LINK_LEVELS`, CLI `--links`) maps `(importer, imported,
   node ids)` to the edge's `(source_endpoint, target_endpoint)` — the aggregation key, nothing
   else; `Edge.source`/`target` stay the real import. `namespace_level` cuts both names where they
   diverge; `module_level` keeps the node, resolving an import to the selected node it lies under
   (a facade stays itself; drawn flat, it is a node of its own). `None` drops the edge (an import of itself or
   of its own package). Links, cycles, groups, metrics, snapshot and diff are untouched by the
   choice; `SnapshotCache.key` includes the level. Selection
   matches **both directions**: a dependency under a selected module, and a dependency *on* a package
   whose children are selected (`pkg.*` never selects `pkg`, so a re-exporting facade is otherwise
   unmatchable).
3. **Domain** (`domain/`) — `Node` (id + `NodeKind`; frozen, hashable, **no metric or grouping
   fields** — which group a node belongs to depends on links that do not exist when it is built),
   `Edge`, `Link`, `Cycle`, `Group`, and `BlueprintGraph`. `edges` is a `frozenset` because `links`,
   `cycles` and `groups` are all derived from it and would silently go stale behind a mutation.
   Metrics live in side maps keyed by node id / endpoint pair. `Edge.source`/`target` are the real
   import; `Edge.source_endpoint`/`target_endpoint`, `Link.source`/`target` and
   `Cycle.endpoint_from`/`endpoint_to` are link endpoints — namespaces or nodes, by link level.
   Only `Group.namespace` is always a namespace: a container is a dotted prefix no node carries.
4. **Metrics** (`metrics/`) — compute-only plugins. `NodeMetric` and `LinkMetric` are **separate**
   protocols (`metrics/base.py`); the registry holds them in separate collections, so the collection
   a metric sits in *is* its target and results route without a cast. Register with
   `register_node` / `register_link`. `MetricRegistry.compute(graph, names)` computes only what is
   asked for. `depth` is compute-only (`render = None`) and drives node fill color.
5. **Analyze** (`analyze/`) — `CycleAnalyzer.detect_cycles` finds mutual pairs of link endpoints
   (a `Cycle`, drawn as one two-headed arrow); `CycleAnalyzer.detect_tangles` finds every longer
   cycle as a strongly connected component (`networkx`) of the links **plus** `facade_edges` — the
   own imports of package facades (`__init__.py`), extracted but never drawn: importing `pkg` runs
   them, so a cycle through a facade exists, yet drawing every facade's imports would bury the
   diagram. A `Tangle` holds its members, drawn links and the hidden edges closing it; a lone mutual
   pair is only a `Cycle`, a pair inside a longer cycle is both. Renderers mark a tangle's one-way
   links with `cyclic_link_styles` and, with cycle details, add one note listing all its imports
   (hidden ones marked "package facade import, not drawn"), tied to every member by a dotted line.
   A pair on a tangle gets no note of its own (`_format_cycle(..., details=False)`), in a diff too:
   its imports are in the tangle's note, so a cycle of any length lists each import once. `GroupAnalyzer.build` decides which link endpoints
   need a container (see below). All are agnostic to node kind and run in the pipeline — **not**
   in a renderer. Snapshots store `facade_edges`; tangles are re-derived.
6. **Render** (`renderer/`) — a `BlueprintRenderer` turns the graph into the output string.

### Snapshot and diff

`snapshot.py` is the one intermediate format: `dump(graph, metrics, links)` / `load(text) ->
Snapshot` (graph + names of the metrics computed into it — stored, not inferred, since a graph with
no links has no `edge_weight` values yet computed it — + the link level it was built at, stored for
the same reason: endpoints alone cannot tell the levels apart). It holds **primary data only** — nodes (extractor
order, which renderers draw in), edges, node/link metrics — and `load` re-derives links, cycles and
groups via `analyze()`. `format` + `version` (2) and the link level are checked; anything unexpected is `SnapshotError`.
Rendering and diffing read snapshots, never rendered diagrams, so a new output format needs a
renderer and no parser. `-f json` computes every registered metric so a snapshot can be drawn with any of them;
`draw SNAPSHOT` rejects a `--metric` the snapshot does not hold.

`diff/` compares two analyzed graphs. `diff_graphs(old, new) -> GraphDiff` (`compute.py`):

- nodes and links by set difference; links by **directed** endpoint pair, so `A→B` becoming `A↔B`
  is a new cycle. A pair whose cycle appeared/disappeared is a `CycleDelta` (`NEW` carries the new
  side's `Cycle`, `RESOLVED` the old side's) and is **not** in `link_status` — drawn as one
  connection. A resolved one carries `remaining`, the direction that survived, and is drawn as that
  single arrow (a bare line when none did): who depends on whom afterwards is what a reviewer needs.
- context is everything unchanged by default: every node of both sides, every link present on both
  (`CONTEXT` in `link_status`), and every cycle present on both (`context_cycles`, not
  `cycle_changes`). With `changes_only=True` context is exact instead: unchanged modules that the
  changed links' edges actually connect (an edge endpoint may be a package facade, not a node —
  filtered), and no unchanged link. `is_empty` ignores context either way.
- `GraphDiff.graph` holds shown nodes + shown edges, with `groups` built but `cycles` left empty on
  purpose (cycle detection on a partial edge set would report a resolved cycle as present).
- tangles compare by their member set (`TangleDelta` NEW/RESOLVED, `context_tangles`); their links
  stay in `link_status` and are marked by `OnCycle` — an unchanged one on an unchanged tangle drawn
  as a plain diagram does, on a new/resolved one like a new/resolved pair. A changed tangle's links
  are shown even with `changes_only`, and `is_empty` counts tangle changes: a facade's imports can
  close a cycle with no drawn link changing.
- a change to the imports inside a link present on both sides is not a structural change — but it
  moves metrics, which is what `metrics=` is for.
- `diff_graphs(..., metrics=names)` compares those metrics from each side's computed values (the
  metric plugins stay compute-only; no registry is involved). Every shown node, link and cycle gets
  a `MetricChange(old, new)` per metric it has a value for, in `node_metrics` (by drawn id),
  `link_metrics` (by `link_status` pair) and `cycle_metrics` (by `frozenset` of the two
  endpoints); all keyed where drawn (a shadowed endpoint follows its node), read at each side's own endpoints. A side without the node/link has `None`, so added/removed need no special case. A
  cycle's value on each side is `domain.cycle_metric_values` — the same `forward/backward`
  combination a plain renderer draws, oriented as the cycle; on a side where the pair is one arrow it
  is that arrow's value, so a new cycle reads `2 → 2/1` and a resolved one `2/1 → 2`.
  `metrics_changed` is true when some value is on both sides and differs. `is_empty` stays
  structure only (tangle changes included), for every caller; "something changed" is `not is_empty or metrics_changed`. With
  `changes_only`, a node/link/cycle whose value changed is shown as context too (plus the modules
  such a link's edges connect); without `metrics` nothing about the diff changes.
- within one graph no node lies under another (the extractor keeps leaves), but a diff joins two:
  a module `pkg.py` removed and a package `pkg/` added are both shown. Such a node is drawn as
  `shadowed_id(pkg)` = `pkg.(module)` (not a possible module name), labelled via `display_name`, so
  it sits inside the `pkg` container — both formats reject a class that is also a container.
  A link endpoint that is such a node **on the side the link comes from** follows it
  (`compute.py:_Redraw`: added/unchanged links from the new side, removed ones from the old), so at
  the module level a removed arrow ends on `pkg.(module)`, not on the new container; renderers quote
  a shadowed endpoint (`_ref` / `_key_of`).

Diff renderers (`render_base.py` Template Method, `render_puml.py`, `render_d2.py`, registry
`diff/__init__.py:DIFF_RENDERERS`) reuse `wrap_groups` (`renderer/base.py`), `format_package` /
`format_cycle_note` (`renderer/puml.py`) and `quote_label` / `format_cycle_note` /
`format_cycle_notes_container` / `CYCLE_CONNECTION_TEMPLATE` (`renderer/d2.py`). Unchanged parts are
drawn as a plain diagram draws them — node fill by depth from `RendererOptions` (`depth_of` keeps a
shadowed node at its module's depth), plain arrows, cycles — and every change is dashed. So the
change colors in `render_base.py` must stay out of `depth_colors` and `CYCLE_HIGHLIGHT_COLOR`
(`test_diff.py` checks); every marker also carries text. An empty diff is still a valid diagram: the
graph with "No architectural changes" in the legend, or just that note when nothing is shown.
Connections are declared in the plain renderer's order (by first endpoint pair, a cycle at its
smaller pair), since the layout engine places things by declaration order: a diff of a graph with
itself equals its plain diagram less the legend (`test_diff.py` checks), so album frames lay out
alike.

A diff renderer takes an optional `RenderPlan` (`plan=`; `None` draws no metric) and draws metrics
through the same render plugins as a plain diagram, via the shared `metric_rows` / `decorate_link`
(`renderer/base.py`). Rendering stays formatting-only: `format_change` (`render_base.py`) writes a
`MetricChange` as the value handed to the plugin — the plain value when unchanged (same type, so
it prints as a plain diagram prints it), the one side's value when added/removed, else
`old → new (±difference)` (difference for numbers only). A changed link or cycle puts its status
label first, then the metric labels (`added edge_weight=1`, `NEW CYCLE edge_weight=2 → 2/1`); an
unchanged link on a changed longer cycle likewise (`_format_link(..., on_cycle, decoration)`). With
a plan that shows metrics the legend adds `metric: old → new (difference)`; the identity invariant
above holds with metrics too.

`git.py` (shared by `diff` and `history`): `checkout(project_dir, rev)` resolves the repo root,
`git archive`s only the project's subtree for that commit into a temp dir, and yields the project
path inside it.
`split_patterns` gives each side only the `-m` patterns whose top-level package it has code for
(`extract/layout.has_source`; a package added or removed wholesale is a diff, not an error); a pattern on neither
side goes to both, so a typo still fails.

### History album

`history/` builds on the snapshot and the diff; it adds no graph logic of its own.

- `git.first_parent_commits` lists the commits on `--head`'s first-parent line that touched the
  project (plus `--base` itself, as the start). `git.tree_id` is the cache key: a snapshot is a
  function of the project's tree, the patterns and the link level.
- `history/cache.py` — `SnapshotCache`: entries keyed by `sha256(tree, patterns, link level, snapshot version,
  tool version)`. Every metric is computed into a cached snapshot, so any `--metric` can be drawn
  from it. `ImageCache`: images keyed by `sha256(format, tool settings, diagram source)` — the
  settings being d2's scale or PlantUML's size limit — drawn once for every run and album showing
  the same diagram. Both write atomically and share one root with a
  `.gitignore` of `*`.
- `history/album.py` — pure: `collect(commits, snapshot_for, metrics=...)` keeps a commit only
  when `diff_graphs` against the previous kept frame is non-empty, or — given `metrics` (the CLI
  passes `--metric`) — when one of those metrics changed value (a leading empty graph — no root
  yet — is skipped). Without `--metric` only structure makes a frame; with it, a commit that only
  adds an import inside an existing link is a frame, so the last frame's values match `--head`.
  The diff frames are drawn with the same metrics, so every frame shows them. `pages()` is the one place frames become named diagrams — one per frame: the first
  plain, the rest a full-context diff (a plain second picture would repeat it); `write()` writes either the
  sources or, given the drawn images, only the images (an album holds one kind of file), rewrites
  only files whose bytes change, and removes this extension's frame files the run did not produce.
- `history/images.py` — `ImageRenderer` per format in `IMAGE_RENDERERS` (keys must match
  `_RENDERERS`, a test checks); `draw()` renders only the pages `ImageCache` lacks, from sources in
  a temporary directory named after the page. PlantUML runs one batch and, since it draws an error
  picture and only reports the batch's exit code, redoes a failed batch file by file to learn which
  failed. A failed source never gets an image. d2 refuses to rasterize past a fixed amount of work
  (a large project's full diagram): `D2Images` retries at half the scale up to `HALVINGS` times,
  starting from `--scale` if given (`scalable` renderers only; `--scale` elsewhere is exit 2).
- CLI (`_history`): `_DIAGRAM_FORMATS` (from `_formats()`, shared with `draw`; `diff`
  has `_DIFF_FORMATS`) maps `-f` to (diagram format, images?), built from the renderers and
  `IMAGE_RENDERERS` — a format with an image renderer gets `<fmt>-png`. Roots are positional and
  optional (default: `detect_roots` of the `--head` tree); `-m` defaults to `ROOT.**` and must lie
  under a root. A root is dropped for a commit where `extract/layout.has_source` finds no analyzable code (mirroring what `GrimpSource` can
  build, so grimp never warns); a commit with none is `no source yet`. A commit whose analysis fails
  is `skipped (reason)`. Exit 2 for bad input (including a missing image tool, checked before any
  work), 1 when images failed — caches keep everything else for the rerun.

### Render plan

`build_render_plan(registry, renders, display, fmt)` (`metrics/plan.py`) resolves requested metric
names to render plugins **once**, preserving `display.shown` order (metric blocks follow CLI
argument order, not registration order — `tests/golden/*/metrics_reordered.*` pins this). It is the
single place a bad request is rejected, with `MetricConfigError`: unknown metric, compute-only
metric, missing render plugin, plugin attached to the wrong side, unknown color metric. It also
reports `required_metrics`, which the pipeline computes — that keeps `color_metric` a single source
of truth, so a custom one cannot go uncomputed and paint every node `depth_colors[0]`.

### Adding a metric (Open/Closed)

Add one file under `src/arch_blueprint/metrics/` implementing `NodeMetric` (`name`, `applies_to`,
`render`, `compute` keyed by node id) or `LinkMetric` (`name`, `render`, `compute` keyed by
`(source_endpoint, target_endpoint)` — no `applies_to`, a link connects endpoints, not node kinds). Register it in
`metrics/__init__.py:default_registry` with the matching `register_*` call. The extractor and
renderer cores do not change. Demo metrics: `fan_in`/`fan_out`/`instability` (node blocks, sharing
`_degrees.degree_counts`) and `edge_weight` (link label). A cycle is one connection standing for two
links, so a link metric shows both values there as `forward/backward`.

### Adding a render type (plugin)

Implement the `RenderPlugin` protocol in a new class (`name`, `attaches_to`,
`render(ctx, label, value)` returning a `RenderFragment(text, style)`) and register it on a
`RenderRegistry` (add to `metrics/render.py:default_renders` for a built-in, or register on a
registry you construct — no library change needed). Branch on `ctx.fmt` (`"puml"`/`"d2"`) to emit
format-specific output; `text` becomes a node line / edge label, `style` is injected into the edge's
style slot by the renderer.

### Namespace grouping

Links aggregate to namespaces while nodes are modules, so most arrow endpoints are names no node
carries. PlantUML resolves them anyway — it infers a container from the dotted class names, and the
rendered picture is the same either way (verified by diffing renders before and after grouping).
Declaring them is about the emitted source naming everything it points at, and about being able to
style or label a container; it is **not** a fix for a broken image. `GroupAnalyzer.build` produces a
`Group` per endpoint that needs one, under three rules — each earned by a case that breaks
otherwise:

1. A namespace that **is** a node id gets no group: the endpoint is already declared, and
   `package a.b { class a.b }` is a PlantUML syntax error. Not an edge case — 18 of 23 endpoints hit
   it when this project graphs itself.
2. Namespaces nest, so a node joins the **deepest** one it lies under. Declaring a class in two
   containers does not error; it silently collapses to one entity.
3. A node under no endpoint namespace joins no group and is drawn as before.

### Renderers (Template Method pattern)

`BlueprintRenderer` (`renderer/base.py`) defines the fixed, **stateless** `render(graph)` algorithm.
It takes a `RenderPlan` (required — a missing one is a `TypeError`, never a silent metric-free
render) and `RendererOptions` (depth colors, cycle details). `fmt` is a `ClassVar` each renderer must
set; the constructor rejects a plan built for another format.

Abstract hooks: `_format_node`, `_format_link(source, target, decoration)`,
`_format_cycle(cycle, decoration, *, details)`, `_combine_output`. `details` is decided by the
template (cycle details on, the pair on no tangle), not by the renderer. `_format_group(namespace, nodes)` is
**concrete**, defaulting to no wrapping — D2 nests by dotted name on its own, and an abstract method
would break every renderer outside this package. `_format_cycle` returns a
`CycleRender(inline, deferred)` so a renderer that must place cycle details elsewhere (D2) carries
them out-of-band without mutating instance state. Shared cycle-detail formatting lives in
`renderer/cycles.py`. Cycles use `CYCLE_HIGHLIGHT_COLOR`, kept distinct from every
`depth_colors` entry. Containers carry **no** stereotype: PlantUML draws one on a package as literal
text inside the frame rather than as a colored spot, which is noise on every container.

To add a new output format:
1. Subclass `BlueprintRenderer` in a new `renderer/<name>.py`, set `fmt`, implement the abstract
   hooks, and override `_format_group` if the format does not nest by dotted name.
2. Register it in the `_RENDERERS` mapping in `__main__.py`.
3. Subclass `DiffRenderer` in `diff/render_<name>.py` and register it in `DIFF_RENDERERS` —
   `test_diff.py` fails while the two registries disagree. No parser is ever needed: diagrams and
   diffs are drawn from snapshots.

Reference implementations: `renderer/puml.py` (`PlantUmlRenderer`) and `renderer/d2.py`
(`D2LangRenderer`). Both are stateless and reuse the shared helpers.

### CLI behaviour

One `argparse` parser with required subcommands (`_COMMANDS`: `draw`, `diff`, `history`; each an `_add_*` builder that sets its handler). No arguments prints the help to stderr
(exit 2); a first argument that is an existing directory is the retired implicit form and gets a
hint naming `draw`. Top-level `--version` and `--list-metrics` (from each metric's `description`,
displayable ones only). Every subcommand's help ends with examples — keep them runnable.

Output is settled by `_output()` **before** any analysis: `-f` / `-o` agree or it is exit 2, an
image needs `-o`, and a missing image tool fails in a second rather than after the build. The
error hints (`_layout_hint`: a package passed instead of its parent, a src layout, the packages
that do exist) are built in the CLI from `PackageNotFoundError` — `extract/source.py` carries the
package name, not the wording.

Failures are one line on stderr with no
traceback: exit **2** for bad input (missing project directory, unresolvable pattern, no modules
matched, bad `--metric`, unreadable or invalid snapshot, `-f json` with drawing options), exit **1**
for an analysis that could not finish (`history`: images that could not be drawn; `draw`: an image the tool refused). `diff` exits
like `diff(1)` instead: **0** no change, **1** any change, **2** any trouble — an analysis failure there is 2, since 1 means "different". A
"change" is structural, or — only with `--metric` — a shown metric whose value moved; without
`--metric` the exit code is exactly as before. `diff --metric` is validated by the same
`build_render_plan` as `draw` (exit 2), a snapshot lacking the metric is exit 2, and `diff --base`
computes the requested metrics on both git sides (nothing else). The diff
diagram is written even on exit 1. Output is written through `sys.stdout.buffer` as UTF-8 — cycle
details contain arrows, and a non-UTF-8 console would otherwise raise `UnicodeEncodeError` after all
the work is done.
