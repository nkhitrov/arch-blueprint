# Interactive viewer: `arch-blueprint serve`

Status: design, awaiting review. Date: 2026-10-11.

## Why

Every look at the architecture today is a separate CLI run: choose `-m`, `--links` and `--metric`
up front, render, open the picture, repeat. Exploring an unfamiliar project that way is slow,
because the right cut is not known in advance. `serve` opens a local page where the project is
explored interactively and every change of view is recomputed on the spot.

## Scope of v1: exploration

In:

- the package tree with checkboxes (the selection, `-m`);
- collapsing / expanding a package frame on the canvas (collapsed = one node, as at the namespace
  level; expanded = its modules);
- focus on a node: its incoming and outgoing links highlighted, everything else dimmed;
- the inspector: a node's metrics and neighbours; a link's real imports;
- search by name; a global level switch `module` / `class`; one metric shown at a time;
- the view state in the URL; a "copy CLI command" button.

Out (later iterations, on the same API):

1. Cycles panel, isolating a cycle, what-if "drop this import" (`excluded_edges` in the request).
2. `--watch`: rebuild on save, changes against a baseline highlighted via `diff_graphs` (SSE).
3. `--base REV` and a slider over `history` frames.
4. Mixing classes and modules in one view (expand a module into its definitions).

## UX

```
┌ level: module|class ─ metric: [instability▾] ─ search ─ [⧉ CLI command] ─────────────┐
│ Package tree     │                                       │ Inspector               │
│ ☑ app1           │  canvas: package frames (compound     │ app1.core.service       │
│   ▸ core (folded)│  nodes); dblclick a frame: fold /     │ fan_in 4 · fan_out 7    │
│   ☐ legacy       │  unfold; click a node: focus; click   │ → depends on (7) …      │
│ ☑ app2           │  an arrow: its imports                │ ← used by (4) …         │
│                  │                                       │ arrow a→b: 3 imports    │
└──────────────────┴───────────────────────────────────────┴─────────────────────────┘
```

- First open: every root from `detect_roots` (or `-m`) selected, each root's direct subpackages
  folded — a small picture to start from; unfolding goes down towards the module level.
- Unfold a frame: its children appear (subpackages folded, modules as nodes); the layout is re-run
  with the previous positions as a hint so the picture does not jump.
- Focus is client-side: the canvas already holds the links. Esc clears it.
- A cycle is drawn as on a diagram: one two-headed arrow in `CYCLE_HIGHLIGHT_COLOR`; a tangle's
  one-way links marked the same way. Node fill by depth, as on a diagram.
- Errors (no modules matched, a file libcst could not parse) are a banner with the CLI's own
  wording and hint, never an empty canvas.
- "⧉ CLI command" gives the `arch-blueprint draw …` closest to the view: the `-m` patterns of the
  selection, `--links`, `--metric`. A view with partial folds has no exact CLI equivalent; the
  command then says so in a comment line.

## Architecture

### Folding: one graph transform, no new link level

A view is the module-level graph with some prefixes folded. `serve/view.py:fold(graph, folded)`
maps every node under a folded prefix, and every edge endpoint under it, to that prefix; nodes
collapse into one `Node(prefix, MODULE)`, edges whose two endpoints fold into one prefix are
dropped. `Edge.source` / `target` stay the real import, so a link's imports are still listed.
Metrics are computed and `analyze()` run **after** folding, so fan-in of a folded package, cycles
between folded packages and tangles are all what the existing code computes on that graph.

Why not a new `LinkLevel`: a level decides an edge's key from one import, with no notion of
per-view state; folding is a property of the view, and keeping it out of `extract/` leaves
`LINK_LEVELS`, snapshots and `SnapshotCache.key` untouched.

### `src/arch_blueprint/serve/`

- `view.py` — pure:
  - `ViewRequest` (frozen): `patterns`, `folded: frozenset[str]`, `links` (`module` | `class`),
    `metrics: tuple[str, ...]`.
  - `build_view(source, request, registry) -> dict`: extract with the level's extractor
    (`LINK_LEVELS`) → `fold` (module level only) → `registry.compute` → `analyze` → JSON:
    nodes (id, kind letter, label, frame path, depth, metric values), frames
    (`renderer/layout.py:Layout.build(..., nested=True)` — labels match the diagrams, merged
    chains included), links (endpoints, metric values, the list of real imports), cycles, tangles,
    `cli`.
  - `cli_command(project_dir, request) -> str`.
- `server.py` — stdlib `ThreadingHTTPServer`, bound to `127.0.0.1` only; no new dependency.
  - `GET /`, `GET /static/<file>` — the front end, read from package data.
  - `GET /api/tree` — the selectable tree under the roots (`GrimpSource.modules_under`).
  - `POST /api/view` — `ViewRequest` JSON → the view; bad input → `400 {error, hint}`.
  - `GrimpSource` per distinct pattern set, kept in a small LRU (grimp builds are the slow part;
    folding and metrics are cheap). `GrimpSource` already restores `sys.path` / `sys.modules`
    per call, so a long-lived server leaves the interpreter as it found it between requests.
- `static/` — `index.html`, `viewer.js` (one ES module, no build step), `viewer.css`;
  **cytoscape.js** (compound nodes) and **cytoscape-elk** (layered layout that respects compound
  nodes) vendored as minified files with their licences, so the page works offline.

### CLI

`_add_serve` in `__main__.py`, added to `_COMMANDS`:

```
arch-blueprint serve PROJECT_DIR [-m PATTERN ...] [--links module|class] [--port N] [--no-open]
```

- `-m` defaults to `detect_roots`, noted on stderr, as for `draw`; a src layout gets the same hint.
- The first view is built **before** the server starts: bad input is exit 2 with the usual
  one-line message, not a page that loads into an error.
- Prints the URL, opens it with `webbrowser` unless `--no-open`; Ctrl-C exits 0.
- `--port 0` (default) picks a free port.
- The help ends with runnable examples, like every subcommand.

## Testing

- `tests/test_serve_view.py` — in-process over fixtures:
  - nothing folded equals the `module`-level graph (links, cycles, metrics);
  - folding to the roots of `examples/project_root` leaves exactly the cross-root links, each
    carrying the imports of every module-level link it absorbed;
  - folding keeps real imports on a link; a fold that swallows a cycle drops it;
    `tests/fixtures/cyclic` yields the cycle unfolded;
  - frames and labels equal `Layout.build`'s for the same nodes (`deep_ns`);
  - `cli_command` re-run through the CLI gives the same nodes and links when no partial fold.
- `tests/test_serve_server.py` — the server on port 0 in a thread: `/`, `/api/tree`,
  `/api/view`, a 400 with hint, a static file outside `static/` refused.
- `tests/test_cli.py` — `serve --help`, exit 2 on a missing directory / unmatched pattern, without
  starting a server.
- Manual: `uv run arch-blueprint serve examples/project_root` in a browser — fold / unfold, focus,
  a link's imports, URL state survives reload, copy the CLI command and run it.

## Documentation

`README.md` gets a `serve` section with a screenshot; `CLAUDE.md` gets the `serve/` layer, the fold
transform and the new test files.
