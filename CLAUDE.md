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
- Run the CLI against a project: `uv run arch-blueprint <project_dir> -m '<pattern>' [-f puml|d2]`
  - Example: `uv run arch-blueprint src -m 'arch_blueprint.*'`
  - Graphing **this** project is a special case: `arch_blueprint` is already in `sys.modules`
    (the CLI *is* it), so `find_spec` resolves to the running copy whatever `<project_dir>` says.
    To graph a different checkout, put it first on `PYTHONPATH` so that copy is the one running.
  - `--modules`/`-m` accepts grimp glob patterns (`pkg.*`, `pkg.**`, `pkg.*.*.models.*`).
  - `-m` can be **repeated** to graph several top-level packages at once and draw the links
    between them — useful when `<project_dir>` is a root with no `__init__.py` containing sibling
    packages (e.g. `-m 'app1.*' -m 'app2.*'`). A cross-package link is drawn only when both
    endpoints belong to the selected set — which includes a dependency *on* a package whose
    children were selected, since `pkg.*` never selects `pkg` itself.
  - `--format`/`-f` defaults to `puml`; `--no-cycle-details` hides per-module edges on cycles.
  - `--metric NAME` (repeatable) displays a metric. A node metric (`fan_in`, `fan_out`,
    `instability`) renders as a block on each node; a link metric (`edge_weight`) renders as a label
    on each connection, including cyclic ones (as `forward/backward`). An unknown name is an error,
    not a silent no-op.
- Regenerate goldens after an *intentional* output change:
  `uv run python scripts/regenerate_goldens.py`. Running it twice must leave the tree clean — a diff
  on the second run means the output is not deterministic, and that is the bug to fix first.
- Regenerate the README example images: `uv pip install --target /tmp/pkgs wemake-python-styleguide
  fastapi taskiq`, then `uv run arch-blueprint /tmp/pkgs -m '<pkg>.*' > docs/images/<name>.puml` and
  `plantuml -tpng docs/images/*.puml`. The committed `.puml` must stay byte-identical to what the
  CLI emits.
- Runnable example fixture: `uv run arch-blueprint examples/project_root -m 'app1.*' -m 'app2.*' -m 'plugins.**'`
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
- `test_source.py` — `GrimpSource`, interpreter-state hygiene, extraction.
- `test_cli.py` — exit codes, stderr messages, output encoding.
- `test_golden_puml.py` / `test_golden_d2.py` — run the CLI as a subprocess over every scenario in
  `tests/conftest.py:SCENARIOS` and assert byte-exact output against `tests/golden/<fmt>/`. When
  output changes *intentionally*, regenerate the affected golden.
- `test_golden_structure.py` — invariants the goldens must satisfy, not just their bytes: every link
  endpoint is declared, and no package wraps a class of its own name.

Two scenarios look redundant and are not. `metrics_reordered` is the only one whose `--metric` order
differs from registration order, so it is the only thing that would catch a render plan built by
iterating the registry. `deep` is the only single-root project whose link endpoints collide with node
ids and nest inside one another.

A hand-built `BlueprintGraph` has **empty `cycles` and `groups`** until the analyze step fills them.
A renderer test that needs either must populate them explicitly, or it will silently assert against
ungrouped nodes and plain arrows.

Fixtures: `examples/project_root` (multi-root + PEP 420 namespace package), `tests/fixtures/cyclic`
(a module cycle), `tests/fixtures/deep_ns` (single root whose link endpoints collide with node ids
and nest), `tests/fixtures/init_imports` (a package re-exporting through `__init__.py`),
`tests/fixtures/ancestor_dep` (an import of a package facade). Fixture projects are excluded from
ruff and mypy — they are analysis subjects, not code we ship.

## Gotchas

- `pre-commit run -a` reports the ruff hooks as **Failed** on the run that rewrites a file. Re-`git
  add` and run again; a second failure is a real one.
- Changing PlantUML output: **render a PNG and look at it**. `-syntax` / `-checkonly` only prove the
  diagram parses. A stereotype on a `package` passes every text check while rendering as caption
  text inside each frame — that regression shipped once and was caught only by comparing images.
- `plantuml -syntax` ignores file arguments and reads stdin only; `-checkonly` takes files. Distro
  builds differ: Ubuntu's `plantuml` 1.2020.02 carries no theme resources, so every golden fails
  there on the shared `!theme amiga` header. Do not put a PlantUML check in CI — assert our own
  invariants in `test_golden_structure.py` instead.
- `tests/golden/` and `docs/images/` are excluded from the whitespace fixers: both hold verbatim tool
  output, and a "fix" makes them stop matching it.

## Git conventions

- Do **not** add self-references to commit messages or PR bodies — no `Co-Authored-By: Claude`
  trailers, no "Generated with Claude Code" lines, no mention of the assistant. Keep commit
  messages about the change only.

## Architecture

`ArchBlueprint` (`src/arch_blueprint/blueprint.py`) is a thin orchestrator: `build()` runs
everything up to rendering, `render(graph)` draws, and `run()` is the two together. The CLI uses
`build()`/`render()` separately because it must see the graph — an empty selection is a user error,
not a diagram.

1. **Source** (`extract/source.py`) — `GrimpSource` owns all grimp/`sys.path` mechanics: resolves
   every `--modules` pattern to a top-level package and builds the grimp graph (multiple roots
   supported). It handles PEP 420 namespace packages grimp can't build directly (expands them, skips
   ones with no analyzable source with a stderr warning). It exposes `selected_modules()` and
   `imports_of(module)` (a module's own imports **and** its descendants').
   Resolution uses `importlib.util.find_spec`, never `import_module`: analysing a project must not
   execute it. `sys.path` and `sys.modules` are restored afterwards, which is what makes the library
   re-runnable in one process — restoring the path alone is not enough, since `sys.modules` is
   consulted first.
2. **Extract** (`extract/`) — a `GraphExtractor` (Protocol in `extract/base.py`, no constructor
   dictated) turns the source into a `BlueprintGraph`. `ModuleExtractor` emits one node per selected
   module, and an edge when a selected module imports another across a namespace boundary. Selection
   matches **both directions**: a dependency under a selected module, and a dependency *on* a package
   whose children are selected (`pkg.*` never selects `pkg`, so a re-exporting facade is otherwise
   unmatchable).
3. **Domain** (`domain/`) — `Node` (id + `NodeKind`; frozen, hashable, **no metric or grouping
   fields** — which group a node belongs to depends on links that do not exist when it is built),
   `Edge`, `Link`, `Cycle`, `Group`, and `BlueprintGraph`. `edges` is a `frozenset` because `links`,
   `cycles` and `groups` are all derived from it and would silently go stale behind a mutation.
   Metrics live in side maps keyed by node id / namespace pair.
4. **Metrics** (`metrics/`) — compute-only plugins. `NodeMetric` and `LinkMetric` are **separate**
   protocols (`metrics/base.py`); the registry holds them in separate collections, so the collection
   a metric sits in *is* its target and results route without a cast. Register with
   `register_node` / `register_link`. `MetricRegistry.compute(graph, names)` computes only what is
   asked for. `depth` is compute-only (`render = None`) and drives node fill color.
5. **Analyze** (`analyze/`) — `CycleAnalyzer.detect_cycles` finds bidirectional namespace
   dependencies; `GroupAnalyzer.build` decides which link endpoints need a container (see below).
   Both are agnostic to node kind, and both run in the pipeline — **not** in a renderer.
6. **Render** (`renderer/`) — a `BlueprintRenderer` turns the graph into the output string.

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
`(src_ns, tgt_ns)` — no `applies_to`, a link connects namespaces, not node kinds). Register it in
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
`_format_cycle(cycle, decoration)`, `_combine_output`. `_format_group(namespace, nodes)` is
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

Reference implementations: `renderer/puml.py` (`PlantUmlRenderer`) and `renderer/d2.py`
(`D2LangRenderer`). Both are stateless and reuse the shared helpers.

### CLI behaviour

`__main__.py` reports failures as one line on stderr with no traceback: exit **2** for bad input
(missing project directory, unresolvable pattern, no modules matched, bad `--metric`), exit **1** for
an analysis that could not finish. Output is written through `sys.stdout.buffer` as UTF-8 — cycle
details contain arrows, and a non-UTF-8 console would otherwise raise `UnicodeEncodeError` after all
the work is done.
