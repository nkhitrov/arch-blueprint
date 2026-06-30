# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

`arch-blueprint` is a CLI that generates architecture diagrams (PlantUML or D2) from a Python
project's module import graph. It is built on top of [`grimp`](https://github.com/seddonym/grimp),
which constructs the import graph.

## Commands

This project uses `uv` for environment and dependency management.

- Install/sync deps: `uv sync` (CI uses `uv sync --locked`)
- Run all checks (what CI runs): `uv run pre-commit run -a`
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
- Runnable example fixture: `uv run arch-blueprint examples/project_root -m 'app1.*' -m 'app2.*' -m 'plugins.**'`
  (see `examples/README.md`) — exercises multi-root cross-links and namespace-package handling.

CI (`.github/workflows/test.yml`) runs `pre-commit` across Python 3.9–3.14. There is currently
**no pytest test suite** in the repo (the `pyproject.toml` pytest/`tests/*` config is aspirational);
verification is done via the linters/type-checker and by running the CLI.

## Git conventions

- Do **not** add self-references to commit messages or PR bodies — no `Co-Authored-By: Claude`
  trailers, no "Generated with Claude Code" lines, no mention of the assistant. Keep commit
  messages about the change only.

## Architecture

`ArchBlueprint.run()` (`src/arch_blueprint/blueprint.py`) drives a three-stage pipeline:

1. **Build the import graph** — appends `project_dir` to `sys.path` (so the target project is
   importable without manual `PYTHONPATH`), then resolves **every** `--modules` pattern to a
   top-level package via `_resolve_grimp_packages()` and calls `grimp.build_graph(*packages)` with
   all of them (multiple roots are supported). `_expand_to_graphable()` handles PEP 420 namespace
   packages (no `__init__.py`), which grimp cannot build directly: it expands a namespace package to
   its regular sub-packages, and skips one that has no analyzable source (with a stderr warning)
   instead of crashing.
2. **Collect modules** — expands the `--modules` patterns against the graph, drops parent
   namespaces of already-selected modules (`_exclude_sub_modules`), and builds `BlueprintModule`s
   (`modules.py`). Each module derives its `namespace`/`depth` and aggregates its imports into
   `NamespaceLink`s via `find_namespace_links()`. Data classes live in `models.py`
   (`ModuleEdge`, `NamespaceLink`, `CyclicDependency`).
3. **Render** — a `BlueprintRenderer` turns modules + links into the output string.

### Renderers (Template Method pattern)

`BlueprintRenderer` (`src/arch_blueprint/renderer/base.py`) defines the fixed `render()` algorithm
and four abstract hooks: `_format_module`, `_format_link`, `_format_cycle`, `_combine_output`.
Cycle detection is shared: `CycleAnalyzer.detect_cycles` (`analyzer.py`) finds bidirectional
namespace dependencies, which renderers draw as highlighted cycles (`CYCLE_HIGHLIGHT_COLOR`).
`RendererOptions` controls depth colors and whether cycle details are shown.

To add a new output format:
1. Subclass `BlueprintRenderer` in a new `src/arch_blueprint/renderer/<name>.py` and implement the
   four abstract methods.
2. Register it in the `_RENDERERS` mapping in `src/arch_blueprint/__main__.py`.

Reference implementations: `renderer/puml.py` (`PlantUmlRenderer`) and `renderer/d2.py`
(`D2LangRenderer` — stateful: it accumulates `_cycle_notes` and resets them at the start of each
`render()`).
