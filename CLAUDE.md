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
  - `--metric NAME` (repeatable) shows a per-node metric block (`fan_in`, `fan_out`, `instability`).
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
   node kind. Metrics are **self-contained plugins** (`metrics/`): each implements `compute(graph)`
   and `render_block(value, builder)`; `MetricRegistry.compute_all` fills `graph.node_metrics`.
4. **Render** (`renderer/`) — a `BlueprintRenderer` turns the graph into the output string.

### Adding a metric (Open/Closed)

Add one file under `src/arch_blueprint/metrics/` implementing the `Metric` protocol (`name`,
`applies_to`, `compute`, `render_block`) and register it in `metrics/__init__.py:default_registry`.
The extractor and renderer cores do not change. `depth` drives node fill color; the demo metrics
`fan_in`/`fan_out`/`instability` render as additive node blocks when requested via `--metric`.

### Renderers (Template Method pattern)

`BlueprintRenderer` (`renderer/base.py`) defines the fixed, **stateless** `render(graph)` algorithm
and abstract hooks: `_block_builder`, `_format_node`, `_format_link`, `_format_cycle`,
`_combine_output`. `_format_cycle` returns a `CycleRender(inline, deferred)` so a renderer that must
place cycle details elsewhere (D2) carries them out-of-band without mutating instance state. Shared
cycle-detail formatting lives in `renderer/cycles.py`. `RendererOptions` controls depth colors,
cycle details, the color metric, and which metric blocks are shown. Cycles are highlighted with
`CYCLE_HIGHLIGHT_COLOR` (kept distinct from every `depth_colors` entry).

To add a new output format:
1. Subclass `BlueprintRenderer` in a new `renderer/<name>.py` and implement the abstract hooks.
2. Register it in the `_RENDERERS` mapping in `__main__.py`.

Reference implementations: `renderer/puml.py` (`PlantUmlRenderer`) and `renderer/d2.py`
(`D2LangRenderer`). Both are stateless and reuse the shared helpers.
