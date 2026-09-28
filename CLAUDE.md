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
    A level also says how it is drawn (`Level.nested` → `RendererOptions.nested`), laid out by
    `renderer/layout.py` (see **Frames and labels** below): `namespace` and the `-grouped` levels
    are nested — every dotted prefix a frame, a chain of frames that hold nothing but one frame
    merged into one labelled by the joined path (`app.features.core.executory_processes`). `module`
    and `class` are flat — every node one box labelled by its dotted name less the prefix
    all drawn names share, which is shown once as the diagram title; every endpoint no node carries
    (a facade an arrow ends on) is declared as a node of its own. Containers only lengthen
    node-to-node arrows.
  - `--links class|class-grouped` make the nodes **definitions**, not modules: the top-level
    classes **and** module-level functions of every selected module, always together — a class
    that calls a function using another class depends on it through that function, drawn as two
    arrows. Arrows are always definition to definition, wherever a definition's code names another
    — bases, metaclass, decorators, class-level annotations, `__init__`, signatures, defaults and
    bodies (string annotations included). `class` is flat; `class-grouped` is nested
    (`Level.nested`), so every node sits in its module's frame. One edge per definition pair,
    so `edge_weight` is always 1 there. `-m 'pkg.**'` also takes the definitions of
    `pkg/__init__.py` (`GrimpSource.pattern_stems`). These levels parse every module's source with
    libcst — about ten times slower than the module levels.
    Example: `uv run arch-blueprint draw tests/fixtures/classes -m 'refs.**' --links class-grouped`.
  - `--deps out` (`extract/focus.py:DEPS_DIRECTIONS`; `in`/`both` — the reverse view — are a
    later PR) makes `-m` the **focus** and also draws every object the focus directly depends on,
    wherever in `<project_dir>` it lives, as a **neighbor** (`BlueprintGraph.neighbors`): muted and
    dashed (`NEIGHBOR_COLOR`, `_format_neighbor`), no metric blocks, labelled by its full name
    when flat (the flat prefix is the focus's; a facade endpoint no focused node lies under is a
    neighbor too — `Layout.neighbors`). Only the focus's imports / references are followed: no
    edge leaves a neighbor, and stdlib / third-party code is never a node. Accepted where `--links`
    is (`_reject_deps` on snapshots); `--metric` with it is exit 2 (`_check_deps`, also for a
    snapshot built with it) — a neighbor's own imports are not read, so its numbers would lie; a
    `--deps` snapshot / history cache entry computes only the compute-only metrics
    (`_undrawn_metrics`). Example: `uv run arch-blueprint draw tests/fixtures/focus_deps -m
    'app.features.core.executory_processes.**' --deps out --links class`.
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

Releases (`.github/workflows/release.yml`, on a published GitHub release): `build` sets the version
from the tag, builds once and smoke-tests the wheel's `--version`; then `testpypi` and, only after
it, `pypi` upload that same `dist/` through trusted publishing (OIDC, no token secret) — one
publisher per index, bound to the `testpypi` / `pypi` environments.

### Tests

`tests/` holds the suite, one file per layer under test:

- `test_domain.py` — link aggregation, `CycleAnalyzer`.
- `test_layout.py` — `Layout`: frames and chain merging (nested), the shared prefix (flat).
- `test_metrics.py` — metric computation, registry routing, render plugins, `RenderPlan` validation.
- `test_renderers.py` — both renderers **in-process** (build a graph, render it, assert on the text).
- `test_source.py` — `GrimpSource`, interpreter-state hygiene, extraction, `detect_roots`.
- `test_symbols.py` — `extract/symbols.py` in-process over small `tmp_path` modules. `_FORMS` is the
  catalogue of every way a top-level class or function refers to another — one case per syntactic
  form of the declaration (decorators and their arguments, bases, class keywords, PEP 695 type
  parameters, every kind of parameter, defaults, return, string annotations nested any way) and of
  the body (calls, attribute chains, `except` / `raise` / `with`, comprehensions, lambdas, nested
  definitions, `match` class and value patterns, f-strings, local imports, `cast("Foo")`), plus the
  `not_*` cases deliberately no dependency (a parameter, local, comprehension / loop / `except as`
  / match capture or type parameter shadowing an import, `Literal` and other value strings).
  `_ALIASES` covers dependencies through a module-level name; then re-exports, star imports,
  conditional imports, and `GrimpSource.module_file` / `modules_under` (nothing imported or
  executed). A new form gets a case here first.
- `test_cli.py` — exit codes, stderr messages and hints, output encoding, `-o` / PNG (through a
  stand-in tool from `conftest.stand_in_tool`), help / `--version` / `--list-metrics`.
- `test_golden_puml.py` / `test_golden_d2.py` — run the CLI as a subprocess over every scenario in
  `tests/conftest.py:SCENARIOS` and assert byte-exact output against `tests/golden/<fmt>/`. When
  output changes *intentionally*, regenerate the affected golden.
- `test_golden_structure.py` — invariants the goldens must satisfy, not just their bytes: every link
  endpoint is declared, no package wraps a class of its own name, and no package holds nothing but
  one package unless an arrow ends on it. Covers diff goldens too.
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

A hand-built `BlueprintGraph` has **empty `cycles` and `tangles`** until the analyze step fills
them. A renderer test that needs either must populate them explicitly (or call `analyze`), or it
will silently assert against plain arrows. Frames need nothing: the renderer lays them out.

Fixtures: `examples/project_root` (multi-root + PEP 420 namespace package), `tests/fixtures/cyclic`
(a module cycle), `tests/fixtures/deep_ns` (single root whose link endpoints collide with node ids
and nest), `tests/fixtures/init_imports` (a package re-exporting through `__init__.py`),
`tests/fixtures/ancestor_dep` (an import of a package facade),
`tests/fixtures/package_nodes` (nodes that are packages, so every edge targets a submodule),
`tests/fixtures/classes` (the class levels: `refs/consumer.py` refers to one class of
`refs/targets.py` per construct, each named after it — `ByBase`, `ByInitParam`, `ByBodyCall`,
`ByModuleVariable`, `ByTypeVarBound`, `ByRegistry`, `ByMatchPattern`, … — plus `NotBy...` classes
(a shadowing parameter, a match capture) that must draw nothing, a re-export through `refs/exported/`, definitions in
`refs/__init__.py` (the function `exported` is named like a subpackage, so its id is
`refs.__init__.exported`), a pair and a ring of classes in `refs/cycles.py`, and module functions in
`refs/functions.py` — `Assembler → build_widget → Widget` runs through a function; `handle` depends
through its decorator, a default and a string naming a module-level alias),
`tests/fixtures/focus_deps` (`--deps out`: a focus `app.features.core.executory_processes`
depending on `legal_cases` — a class through a facade re-export, the facade and a module under it —
and on another top-level package `billing`; `legal_cases.models` imports `app.shared.clock`,
which must not be drawn),
`tests/fixtures/diff` (snapshot edits used as diff inputs, every metric computed into them like a
`-o graph.json` snapshot; `cyclic_weighted.json` is `cyclic` plus one import inside an existing link
— a metric-only change; `classes_class_edited.json` / `classes_class_grouped_edited.json` are the
class snapshots with a class added, an arrow removed and a pair resolved — regenerate them from
their golden snapshot, with the same three edits, when that golden changes;
`focus_deps_module_links_no_billing.json` is that golden less the `billing.invoices` dependency; all of them when the
snapshot format or a metric's counting changes). Fixture projects are excluded from
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
renderer. `analyze()` (`analyze/__init__.py`) derives cycles then tangles, and is the one place that
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
   `sys.modules` is consulted first. grimp's own cache is never used (`cache_dir=None`): it sits in
   the cwd and is keyed by module **name** and mtime, not path — `git archive` stamps every file
   with the commit time, and concurrent runs interleave its separate meta/data files — so another
   checkout's imports could be drawn silently (#39). Rebuilding is cheap; `history` has its own
   `SnapshotCache`. With `deps` (`--deps`) it also builds every package of `<project_dir>`
   (`detect_roots`, only those `find_spec` locates inside it — `_lies_in`), so a dependency in a
   sibling top-level package is in the graph and parseable; the selection is unchanged.
2. **Extract** (`extract/`) — a `GraphExtractor` (Protocol in `extract/base.py`, no constructor
   dictated) turns the source into a `BlueprintGraph`. `ModuleExtractor` emits one node per selected
   module, and an edge when a selected module imports another across a boundary of its link level.
   A module level's endpoints function (`extract/levels.py`, CLI `--links`) maps `(importer, imported,
   node ids)` to the edge's `(source_endpoint, target_endpoint)` — the aggregation key, nothing
   else; `Edge.source`/`target` stay the real import. `namespace_level` cuts both names where they
   diverge; `module_level` keeps the node, resolving an import to the selected node it lies under
   (a facade stays itself; drawn flat, it is a node of its own). `None` drops the edge (an import of itself or
   of its own package). Links, cycles, metrics, snapshot and diff are untouched by the
   choice; `SnapshotCache.key` includes the level. Selection
   matches **both directions**: a dependency under a selected module, and a dependency *on* a package
   whose children are selected (`pkg.*` never selects `pkg`, so a re-exporting facade is otherwise
   unmatchable). With `source.deps`, an import of a focused module that matches neither is
   collected instead of dropped; the neighbor nodes are its **leaves** (`GrimpSource.leaves`, the
   rule `selected_modules` uses — no node under another), an ancestor of one stays a facade
   endpoint, and the level resolves over focus ∪ neighbors. Neighbors follow the focus in node
   order, sorted.
   The level registry is `extract/registry.py:LINK_LEVELS` (apart from `levels.py`, which the
   module extractor imports): a `Level` carries its `extractor` factory and `nested`, so `__main__._extractor`, `--links` choices, `snapshot.load` and
   `SnapshotCache.key` all read one table — a new link level is one entry. A new node kind is a
   `NodeKind` member too, declaring its snapshot name and its diagram `letter` together (no map
   to keep in sync, no fallback letter).
   `DefinitionExtractor(source, kinds)` (`extract/definition_extractor.py`) is the extractor of the
   class levels: a node per top-level definition of a wanted `NodeKind` (`CLASS` and `FUNCTION`,
   `registry.py:_DEFINITIONS`; a new kind, such as methods, is a `NodeKind` member added there) in every module
   under a match (`GrimpSource.matching_modules` + `modules_under`, and `pattern_stems` for
   `pkg/__init__.py`), sorted by id; an edge per reference that resolves to another node, both
   endpoints the definitions themselves; no `facade_edges` (a re-export is followed to where the
   name is defined). A definition in `pkg/__init__.py` named like a module of `pkg` gets the id
   `pkg.__init__.name` (`FACADE_MODULE`) — `pkg.name` is the frame of that module's definitions.
   With `source.deps`, a resolved target of a wanted kind that no pattern selects is a neighbor
   (its kind read from its module's `definitions`, `_kind_of`), ids assigned over both sets.
   `extract/symbols.py` is the only libcst user, imported lazily by the extractor.
   `ModuleSymbols.parse` runs one `QualifiedNameProvider` pass per module: `definitions`,
   `exports` (module-level imports, `TYPE_CHECKING` / `try` / `if` ones included — what a facade
   re-exports; a name imported in two branches keeps both), `aliases` (every other module-level
   variable → the names its values mention: `Alias = Foo | Bar`, `T = TypeVar("T", bound=Foo)`,
   `type A = Foo`, `HANDLERS = {"a": Foo}`, `HANDLERS["b"] = Bar`, `HANDLERS |= {...}`,
   `ITEMS += [Foo]`, `settings = Settings()`, and a function's `global settings; settings = ...` —
   which still counts for the function too), star
   imports, and per definition every absolute name its subtree references — declaration and body
   alike (nested classes and functions count for the outer one; `<locals>` names — parameters,
   even one named like an import — and builtins dropped). libcst misses two kinds of local, shadowed
   here by name: PEP 695 type parameters and `match` captures (`_Collector._locals`). A body's
   captures are pushed for the body alone (`visit_FunctionDef_body`), so they never shadow the
   function's own signature or decorators, and a class body's are not seen by its methods. libcst
   is not flow-sensitive either: in `class C: x: t.T; t = 0` it gives `t` only the class-local
   meaning, so a name a class body binds is also resolved around the class
   (`_outside_class`). It does not
   look inside strings either: a string is re-parsed and resolved in its own scope when it sits
   where a type goes — an annotation, a subscript of a `typing` / `collections.abc` / builtin
   generic (`Optional["Foo"]`, `list["Foo"]`, even outside an annotation), `cast`'s first
   argument, a `TypeVar`'s constraints / `bound`, a PEP 695 bound or default, the value of a
   `TypeAlias` or `type` statement, a string inside such a string — and not in a `Literal`,
   `Annotated` metadata or another call's arguments (a context stack, innermost wins).
   `SymbolIndex.resolve` maps a name to the **set** of definitions it ends on: longest defined
   prefix (`m.Foo.create` → `m.Foo`), else follow the deepest module's exports, aliases (each value
   name, the rest of the dotted name appended — `settings.x` → `Settings.x` → `Settings`) and star
   imports, with a visited set against loops; memoized per index. Files are found by
   `GrimpSource.module_file`, which runs `find_spec` on the **top-level** name only — on a dotted
   name it imports the parent packages, i.e. executes project code — and walks the search
   locations below. Parses are cached by `(module, is package, content sha256)`, never by name
   (#39); a file libcst cannot parse is skipped with a stderr warning.
3. **Domain** (`domain/`) — `Node` (id + `NodeKind`: `MODULE`, `CLASS`, `FUNCTION`, each with
   its `letter`, PlantUML's spot `M` / `C` / `F`; the id is always a dotted path, so frames and flat labels work
   unchanged for definitions; frozen, hashable, **no metric or frame
   fields** — which frame a node is drawn in depends on what else is drawn, a diff's nodes too),
   `Edge`, `Link`, `Cycle`, `Tangle`, and `BlueprintGraph`. `edges` is a `frozenset` because `links`,
   `cycles` and `tangles` are all derived from it and would silently go stale behind a mutation.
   Metrics live in side maps keyed by node id / endpoint pair. `Edge.source`/`target` are the real
   import; `Edge.source_endpoint`/`target_endpoint`, `Link.source`/`target` and
   `Cycle.endpoint_from`/`endpoint_to` are link endpoints — namespaces or nodes, by link level.
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
   its imports are in the tangle's note, so a cycle of any length lists each import once. Both are
   agnostic to node kind and run in the pipeline — **not** in a renderer. Frames are the
   renderer's (`renderer/layout.py`): they depend on what a drawing shows, a diff's nodes included. Snapshots store `facade_edges`; tangles are re-derived.
6. **Render** (`renderer/`) — a `BlueprintRenderer` turns the graph into the output string.

### Snapshot and diff

`snapshot.py` is the one intermediate format: `dump(graph, metrics, links, deps)` / `load(text) ->
Snapshot` (graph + names of the metrics computed into it — stored, not inferred, since a graph with
no links has no `edge_weight` values yet computed it — + the link level it was built at, stored for
the same reason: endpoints alone cannot tell the levels apart). It holds **primary data only** — nodes (extractor
order, which renderers draw in), edges, node/link metrics — and `load` re-derives links, cycles and
tangles via `analyze()`. `format` + `version` (3) and the link level are checked; anything unexpected is `SnapshotError`.
Version 3 adds `deps` (the `--deps` direction or null) and `neighbors` (node ids, each checked to
be a node); version 2 is still read, as a graph without `--deps`. Two snapshots of different
`deps` cannot be diffed (exit 2), and `SnapshotCache.key` includes it.
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
- `GraphDiff.graph` holds shown nodes + shown edges, with `cycles` left empty on
  purpose (cycle detection on a partial edge set would report a resolved cycle as present).
- tangles compare by their member set (`TangleDelta` NEW/RESOLVED, `context_tangles`); their links
  stay in `link_status` and are marked by `OnCycle` — an unchanged one on an unchanged tangle drawn
  as a plain diagram does, on a new/resolved one like a new/resolved pair. A changed tangle's links
  are shown even with `changes_only`, and `is_empty` counts tangle changes: a facade's imports can
  close a cycle with no drawn link changing.
- `GraphDiff.graph.neighbors`: a shown node that is a neighbor on the side it comes from (removed:
  old, else new), drawn after the focus as the extractor orders them, so the identity invariant
  holds with `--deps`. An unchanged neighbor is drawn as a plain diagram draws it
  (`DiffRenderer._format_neighbor`); an added / removed one is marked as that, under its full name.
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
`diff/__init__.py:DIFF_RENDERERS`) reuse `Layout.build` / `placed_nodes` / `laid_out`
(`renderer/layout.py`, `renderer/base.py`) — the layout of the shown nodes and the drawn connection
endpoints, as a plain diagram of them has — `format_frame` / `class_head` /
`format_cycle_note` (`renderer/puml.py`) and `layout_key` / `label_line` / `format_title` / `quote_label` / `format_cycle_note` /
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

### Frames and labels

Most of every dotted id is repeated on every box; `renderer/layout.py:Layout.build(node ids,
endpoints, nested=...)` works out, once per drawing, where each name goes and what it is labelled.
Ids never change — arrows, snapshots and diffs name the same things whatever a label reads. Both
the plain and the diff template call it (the diff with its shown nodes and every drawn connection
endpoint), so a diff of a graph with itself lays out exactly as its plain diagram.

**Nested** (`namespace`, `class-grouped`): every proper dotted prefix of a node or
an endpoint is a frame, under rules each earned by a case that breaks otherwise:

1. A prefix that **is** a node id is no frame: the node is already declared, and
   `package a.b { class a.b }` is a PlantUML syntax error. Not an edge case — 18 of 23 endpoints hit
   it when this project graphs itself.
2. A node sits in the **deepest** frame it lies under. Declaring a class in two containers does
   not error; it silently collapses to one entity.
3. A frame holding no node and exactly one child frame is **merged** into that child, labelled by
   the joined path, repeatedly — so `app` → `features` → `core` → `executory_processes` is one frame
   `app.features.core.executory_processes`. Unless an arrow ends on it (the namespace level points
   arrows at containers): then it stays. A frame holding a node or two frames stays.

Frames sit where their first node is drawn (declaration order is layout order). PlantUML draws
them explicitly: `set separator none` (always), `package "label" as full.id { ... }` nested, and
`class "label" as full.id`; an arrow names the alias. D2 nests by key: a node's key is its path
through the frames, a merged chain one quoted part (`"app.features.core".usecases.Run`), and D2
labels a node by its last part.

**Flat** (`module`, `class`): no frames; the items are the nodes plus every endpoint no
node carries (a package facade), each facade before the first node under it. The prefix every drawn
name shares, in whole dotted parts and never a whole name (`common_prefix`; a lone `a.b.c` keeps
`c`; names differing in their first part share nothing), is dropped from every label and shown once
as the title: PlantUML `title <prefix>`, D2 a `title` text shape `near: top-center`. A label equal
to its key adds nothing (`class a.b` / no `label:` line). A diff works the prefix out on the modules
its shadowed nodes stand for (`pkg (module)`).

The layout reaches the hooks on a copy of the renderer (`laid_out`, the `LaidOut.layout`
property), so the renderer a caller holds never changes and the hook signatures stay as they were.
`render` is `@final` in both bases, and `layout` read anywhere but on that copy (a hook called
directly) raises instead of drawing every name flat. PlantUML reads a title, a package label and a
note as creole, where `__init__` is an underlined `init`: those go through `escape_creole`.

### Renderers (Template Method pattern)

`BlueprintRenderer` (`renderer/base.py`) defines the fixed, **stateless** `render(graph)` algorithm.
It takes a `RenderPlan` (required — a missing one is a `TypeError`, never a silent metric-free
render) and `RendererOptions` (depth colors, cycle details). `fmt` is a `ClassVar` each renderer must
set; the constructor rejects a plan built for another format.

`_format_neighbor(node)` is concrete too: by default `_format_node(node, NEIGHBOR_COLOR, [])`, so
a renderer outside this package draws `--deps` neighbors without knowing them; puml / d2 add a
dashed, muted style (`NEIGHBOR_STYLE`). Abstract hooks: `_format_node`, `_format_link(source, target, decoration)`,
`_format_cycle(cycle, decoration, *, details)`, `_combine_output`. `details` is decided by the
template (cycle details on, the pair on no tangle), not by the renderer. `_format_frame(frame, items)` is
**concrete**, defaulting to no wrapping — D2 nests by key on its own, and an abstract method
would break every renderer outside this package. It replaced `_format_group(namespace, nodes)`;
a subclass still defining that is a `TypeError` at class creation (`LaidOut._RENAMED_HOOKS`),
not a diagram silently drawn without containers. A hook spells a name through `self.layout`
(`path`, `label`, `title`). `_format_cycle` returns a
`CycleRender(inline, deferred)` so a renderer that must place cycle details elsewhere (D2) carries
them out-of-band without mutating instance state. Shared cycle-detail formatting lives in
`renderer/cycles.py`. Cycles use `CYCLE_HIGHLIGHT_COLOR`, kept distinct from every
`depth_colors` entry. Containers carry **no** stereotype: PlantUML draws one on a package as literal
text inside the frame rather than as a colored spot, which is noise on every container.

To add a new output format:
1. Subclass `BlueprintRenderer` in a new `renderer/<name>.py`, set `fmt`, implement the abstract
   hooks, and override `_format_frame` if the format does not nest by key.
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
matched, bad `--metric`, `--metric` with `--deps`, unreadable or invalid snapshot, `-f json` with drawing options), exit **1**
for an analysis that could not finish (`history`: images that could not be drawn; `draw`: an image the tool refused). `diff` exits
like `diff(1)` instead: **0** no change, **1** any change, **2** any trouble — an analysis failure there is 2, since 1 means "different". A
"change" is structural, or — only with `--metric` — a shown metric whose value moved; without
`--metric` the exit code is exactly as before. `diff --metric` is validated by the same
`build_render_plan` as `draw` (exit 2), a snapshot lacking the metric is exit 2, and `diff --base`
computes the requested metrics on both git sides (nothing else). The diff
diagram is written even on exit 1. Output is written through `sys.stdout.buffer` as UTF-8 — cycle
details contain arrows, and a non-UTF-8 console would otherwise raise `UnicodeEncodeError` after all
the work is done.
A reader that closes stdout early (`draw ... | head -1`) ends the run quietly with exit 1
(`main` catches `BrokenPipeError` and points stdout at devnull, the Python docs' recipe).
