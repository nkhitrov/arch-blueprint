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
- Lint (with autofix): `uv run ruff check --fix src`
- Type-check (strict mypy): `uv run mypy ./src`
- Run the CLI against a project: `uv run arch-blueprint <project_dir> -m '<pattern>' [-f puml|d2]`
  - Example: `uv run arch-blueprint . -m 'arch_blueprint.*'`
  - `--modules`/`-m` accepts grimp glob patterns (`pkg.*`, `pkg.**`, `pkg.*.*.models.*`).
  - `-m` can be **repeated** to graph several top-level packages at once and draw the links
    between them — useful when `<project_dir>` is a root with no `__init__.py` containing sibling
    packages (e.g. `-m 'app1.*' -m 'app2.*'`). A cross-package link is drawn only when both
    endpoints are in the selected set.
  - `--format`/`-f` defaults to `puml`; `--no-cycle-details` hides per-module edges on cycles.
  - `--metric NAME` (repeatable) displays a metric. A node metric (`fan_in`, `fan_out`,
    `instability`) renders as a block on each node; a link metric (`edge_weight`) renders as a label
    on each connection.
- Runnable example fixture: `uv run arch-blueprint examples/project_root -m 'app1.*' -m 'app2.*' -m 'plugins.**'`
  (see `examples/README.md`) — exercises multi-root cross-links and namespace-package handling.

CI (`.github/workflows/test.yml`) has two jobs: a single-version `lint` job (`pre-commit`, skipping
pytest) and a `test` matrix running `pytest` across Python 3.9–3.14, on push to `master` and on PRs.

### Tests

`tests/` holds the suite. `tests/test_golden.py` runs the CLI as a subprocess over fixtures and
asserts byte-exact output against snapshots in `tests/golden/` — the regression guard; when output
*intentionally* changes, regenerate the affected golden file. `tests/test_units.py` covers the
domain, metrics, analyzer, and extractors. Fixtures: `examples/project_root` (multi-root + namespace
packages) and `tests/fixtures/cyclic` (a module cycle).

## Git conventions

- Do **not** add self-references to commit messages or PR bodies — no `Co-Authored-By: Claude`
  trailers, no "Generated with Claude Code" lines, no mention of the assistant. Keep commit
  messages about the change only.

## Architecture

`ArchBlueprint.run()` (`src/arch_blueprint/blueprint.py`) is a thin orchestrator over four layers:

1. **Source** (`extract/source.py`) — `GrimpSource` owns all grimp/`sys.path` mechanics: it appends
   `project_dir` to `sys.path`, resolves every `--modules` pattern to a top-level package, and builds
   the grimp graph (multiple roots supported). It handles PEP 420 namespace packages grimp can't
   build directly (expands them, skips ones with no analyzable source with a stderr warning). It
   exposes `selected_modules()` and `imports_of(module)`.
2. **Extract** (`extract/`) — a `GraphExtractor` (Protocol in `extract/base.py`) turns the source
   into a `BlueprintGraph`. `ModuleExtractor` emits one node per selected module. An extractor
   assigns each `Node` its `NodeKind` and namespace, so a new node kind is added by writing another
   extractor — the domain, metrics, and renderers do not change.
3. **Domain + metrics** — `domain/` holds the data model: `Node` (id, `NodeKind`, namespace — frozen
   and hashable, **no metric fields**), `Edge`, `Link`, `Cycle`, and `BlueprintGraph` (aggregates
   edges into `Link`s via `build_links`, stores metrics in side maps keyed by id/namespace-pair).
   `analyze/cycles.py` (`CycleAnalyzer`) finds bidirectional namespace dependencies — agnostic to
   node kind. Metrics are **compute-only plugins** (`metrics/`): each declares a `target`
   (`MetricTarget.NODE`/`LINK`), names a render plugin (`render`), and implements `compute(graph)`.
   `MetricRegistry.compute_all` routes results by target into `graph.node_metrics` (keyed by node id)
   or `graph.link_metrics` (keyed by namespace pair). **Render plugins** (`metrics/render.py`) are a
   separate, registerable layer: each implements the `RenderPlugin` protocol (`name`, `attaches_to`,
   `render(ctx, label, value) -> RenderFragment`) and is format-aware via `RenderContext.fmt`, so it
   can emit node-block text, edge labels, or edge shapes/colors. New render types are added without
   changing library code. `MetricDisplay` (`metrics/display.py`) is the separate config selecting
   which metrics to display.
4. **Render** (`renderer/`) — a `BlueprintRenderer` turns the graph into the output string.

### Adding a metric (Open/Closed)

Add one file under `src/arch_blueprint/metrics/` implementing the `Metric` protocol (`name`,
`target`, `applies_to`, `render`, `compute`) and register it in
`metrics/__init__.py:default_registry`. The extractor and renderer cores do not change. A node metric
sets `target = MetricTarget.NODE` and a `render` plugin name like `"text_row"`; a link metric sets
`target = MetricTarget.LINK` and e.g. `"edge_label"` (its `compute` is keyed by `(src_ns, tgt_ns)`).
`depth` is compute-only (`render = None`): it drives node fill color and is never displayed. Demo
metrics: `fan_in`/`fan_out`/`instability` (node blocks) and `edge_weight` (link label), shown when
requested via `--metric`. Link-metric labels apply to ordinary directed links; cyclic connections
keep their own cycle rendering.

### Adding a render type (plugin)

Implement the `RenderPlugin` protocol in a new class (`name`, `attaches_to`,
`render(ctx, label, value)` returning a `RenderFragment(text, style)`) and register it on a
`RenderRegistry` (add to `metrics/render.py:default_renders` for a built-in, or register on a
registry you construct — no library change needed). Branch on `ctx.fmt` (`"puml"`/`"d2"`) to emit
format-specific output; `text` becomes a node line / edge label, `style` is injected into the edge's
style slot by the renderer.

### Renderers (Template Method pattern)

`BlueprintRenderer` (`renderer/base.py`) defines the fixed, **stateless** `render(graph)` algorithm
and abstract hooks: `_format_node`, `_format_link(source, target, decoration)`, `_format_cycle`,
`_combine_output` (plus a `fmt` class attribute). The core resolves each shown metric's render plugin
itself and passes node-block text to `_format_node` and a `LinkDecoration(labels, styles)` to
`_format_link`. `_format_cycle` returns a `CycleRender(inline, deferred)` so a renderer that must
place cycle details elsewhere (D2) carries them out-of-band without mutating instance state. Shared
cycle-detail formatting lives in `renderer/cycles.py`. `RendererOptions` controls depth colors,
cycle details, and the color metric; metric *selection* is the separate `MetricDisplay` argument.
Cycles are highlighted with `CYCLE_HIGHLIGHT_COLOR` (kept distinct from every `depth_colors` entry).

To add a new output format:
1. Subclass `BlueprintRenderer` in a new `renderer/<name>.py` and implement the abstract hooks.
2. Register it in the `_RENDERERS` mapping in `__main__.py`.

Reference implementations: `renderer/puml.py` (`PlantUmlRenderer`) and `renderer/d2.py`
(`D2LangRenderer`). Both are stateless and reuse the shared helpers.
