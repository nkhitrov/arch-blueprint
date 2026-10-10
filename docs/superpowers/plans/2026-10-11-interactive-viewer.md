# Interactive viewer (`arch-blueprint serve`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a `serve` command that opens a local page to explore a project's import graph — fold /
unfold packages, focus a node, see a link's imports — recomputed by Python on every change.

**Architecture:** `serve/fold.py` folds a module-level graph into a view; `serve/view.py` builds
the JSON of one view (extract → fold → metrics → analyze → layout); `serve/server.py` is a stdlib
HTTP server over it; `serve/static/` is a no-build front end on vendored cytoscape.js + ELK.

**Tech Stack:** Python 3.9+, stdlib `http.server`, grimp / existing pipeline; cytoscape.js
3.30.2, elkjs 0.9.3, cytoscape-elk 2.2.0 (vendored).

**Spec:** `docs/superpowers/specs/2026-10-11-interactive-viewer-design.md`

## Global Constraints

- No new Python dependency. Python 3.9 syntax (`Optional`, `from __future__ import annotations`).
- Server binds `127.0.0.1` only.
- Strict mypy, ruff rules of `pyproject.toml`; `uv run pre-commit run -a` green.
- Errors reuse the CLI's wording (`_layout_hint`, "no modules matched: …").
- Commit messages carry no assistant self-reference.

**Deviation from spec, deliberate:** `ViewRequest` has no `metrics` field — every registered
metric is computed (cheap next to the grimp build), and the metric shown is chosen client-side;
the CLI command still carries `--metric` from the client state.

## Review Focus

1. Folding a prefix that is a package facade some arrow ends on (`ancestor_dep`) — the arrow must
   end on the folded node, not vanish.
2. Facade imports inside a folded package — they become the folded node's own imports (as
   `-m pkg` would draw them), not hidden edges.
3. A fold covering a prefix with no selected module — ignored, no phantom node.
4. A static path with `..` — 404, never a file outside `static/`.
5. A pattern that matches nothing in a later request — 400 with the CLI's message, server keeps
   running.

---

### Task 1: `fold(graph, folded)`

**Files:** Create `src/arch_blueprint/serve/__init__.py`, `src/arch_blueprint/serve/fold.py`;
Test `tests/test_serve_view.py`.

**Interfaces:** Produces `fold(graph: BlueprintGraph, folded: Collection[str]) -> BlueprintGraph`
— returns a **new, un-analyzed** graph (no metrics, empty cycles).

Rules: `owner(name)` = the shortest folded prefix `p` with `name == p` or `name` under `p`, else
`name`. Nodes: each node mapped by `owner`, deduplicated, first-occurrence order, a folded node
is `Node(p, MODULE)`. Edges: endpoints mapped by `owner`; a facade edge whose **source** is under
or equal to a folded prefix becomes an ordinary edge (its code is now the node's own); an edge is
dropped when its endpoints are equal or the source endpoint lies under the target endpoint
(an import of its own package, as `module_level` drops it). `Edge.source/target` unchanged.

- [ ] Step 1: tests — over `ModuleExtractor(GrimpSource(EXAMPLE_PROJECT, ["app1.**", "app2.**", "plugins.**"]), level=module_level).extract()`:
  - `test_fold_nothing_is_identity`: nodes and edges equal.
  - `test_fold_root_keeps_cross_links`: fold `{"app1","app2","plugins"}` → node ids are those
    three; every link connects two of them; the union of their edges' `(source, target)` equals
    the original cross-root edges' pairs.
  - `test_fold_unknown_prefix_ignored`: fold `{"nope"}` → identity.
  - `test_fold_matches_bare_selection` on `INIT_IMPORTS_PROJECT`: folding `storage` of
    `["writer", "storage.**"]` gives the same node ids and link pairs as extracting
    `["writer", "storage"]` (facade imports included).
  - `test_fold_keeps_arrow_on_facade` on `ANCESTOR_DEP_PROJECT`: folding the package an arrow's
    target facade sits in keeps a link ending on the folded node.
  - `test_fold_swallows_cycle` on `CYCLIC_PROJECT`: unfolded `analyze` has a cycle; folding both
    sides of it into one prefix (their common package, if any; else fold each root and expect the
    cycle between the roots) behaves accordingly.
- [ ] Step 2: run `uv run pytest tests/test_serve_view.py` → fails (no module).
- [ ] Step 3: implement.
- [ ] Step 4: tests pass; `uv run mypy ./src ./tests`; `uv run ruff check src tests`.
- [ ] Step 5: commit `feat(serve): fold a module graph into packages`.

### Task 2: `build_view` and `cli_command`

**Files:** Create `src/arch_blueprint/serve/view.py`; Test `tests/test_serve_view.py`.

**Interfaces:**
- `@dataclass(frozen=True) class ViewRequest: patterns: tuple[str, ...]; folded: frozenset[str] = frozenset(); links: str = "module"` (`links` ∈ `VIEW_LEVELS = ("module", "class")`; `ValueError` otherwise).
- `ViewRequest.from_json(data: Mapping[str, Any]) -> ViewRequest` — `ValueError` on bad shape.
- `build_view(source: GrimpSource, request: ViewRequest, registry: MetricRegistry) -> dict[str, Any]`
  — `module`: `ModuleExtractor(source, level=module_level)` then `fold`; `class`:
  `LINK_LEVELS["class-grouped"].extractor(source)`, `folded` ignored. Then
  `registry.compute(graph, None)`, `analyze`. Raises `NoModulesError(patterns)` (defined here) on
  an empty graph.
- JSON shape:
  ```
  {"nodes": [{"id","label","kind","parent","folded","depth","color","metrics":{}}],
   "frames": [{"id","label","parent"}],
   "links": [{"source","target","cyclic","metrics":{}, "imports":[[importer, imported], ...]}],
   "cycles": [{"a","b","imports":[[i,j],...]}], "tangles": [{"members":[...]}],
   "metrics": {"node": [names displayable], "link": [names]}, "cli": str}
  ```
  Frames/labels from `Layout.build(node_ids, endpoints, nested=True)`: walk `layout.items`
  recursively; a node's `parent` is the frame holding it; an endpoint that is a frame needs no node.
  `color` = `DEFAULT_OPTIONS.get_color_for_depth(depth)`. A link inside a cycle pair is not listed
  in `links` (the cycle is). `cyclic` = link is on a tangle. Lists sorted for determinism; `imports`
  sorted.
- `cli_command(project_dir: str, request: ViewRequest, metric: Optional[str]) -> str` —
  `arch-blueprint draw DIR -m P … --links module|class-grouped [--metric M]`, shell-quoted; with
  `folded` (module level) prefixed by the line
  `# folded packages have no CLI equivalent; this draws them unfolded`.

- [ ] Step 1: tests:
  - `test_view_unfolded_matches_module_level` (example project): link pairs ==
    `build_graph(..., LINK_LEVELS["module"].extractor)` link pairs minus cycle pairs, cycles equal.
  - `test_view_frames_nest` (`DEEP_PROJECT`, `deep.**`): every node's `parent` is a frame id or
    `None`, every frame's `parent` likewise, labels equal `Layout.label`.
  - `test_view_link_lists_imports`: some link's `imports` non-empty and each pair is a real edge.
  - `test_view_folded_node_flagged`: fold `app1` → node `app1` has `folded: True`.
  - `test_view_class_level` (`CLASSES_PROJECT`, `refs.**`): node kinds include `C` and `F`.
  - `test_view_no_modules` → `NoModulesError`.
  - `test_cli_command_roundtrip`: run `main(shlex.split(cmd)[1:] + ["-f", "json"])` via
    `subprocess` like `tests/conftest.py` does; snapshot nodes == view node ids (unfolded).
  - `test_cli_command_folded_note`.
  - `test_request_from_json_rejects` bad `links`, non-list `patterns`.
- [ ] Steps 2–4 as in Task 1.
- [ ] Step 5: commit `feat(serve): build a view as JSON`.

### Task 3: HTTP server

**Files:** Create `src/arch_blueprint/serve/server.py`, `src/arch_blueprint/serve/static/index.html`
(placeholder until Task 5); Test `tests/test_serve_server.py`.

**Interfaces:**
- `class ViewServer`: `__init__(self, project_dir: str, roots: Sequence[str], registry: MetricRegistry, port: int = 0)`; `url: str`; `serve_forever()`; `shutdown()`; `server_close()`.
- `GrimpSource` per `patterns` tuple in an `OrderedDict` LRU of 4.
- Routes: `GET /` → `index.html`; `GET /static/<name>` → file in `static/` (resolved path must stay
  inside; else 404); `GET /api/tree` → `{"project": str, "roots": [...], "modules": [{"id",
  "package": bool}]}` (from `GrimpSource(project, [r + ".**" for r in roots]).modules_under(root)`,
  `package` = some other module lies under it); `POST /api/view` with JSON body
  `{patterns, folded, links, metric?}` → `build_view` + `cli` → 200; `ValueError`,
  `NoModulesError`, `PackageNotFoundError`, `ImportError` → 400 `{"error": str}`;
  unknown path → 404. Responses `application/json; charset=utf-8`. Request logging silenced.
- [ ] Step 1: tests, server on port 0 in a daemon thread (fixture): `/` 200 html; `/api/tree`
  lists `app1` as package; `/api/view` 200 with nodes; bad links → 400; unmatched pattern → 400
  and a following valid request → 200; `/static/../server.py` and `/static/%2e%2e/server.py` → 404.
- [ ] Steps 2–4; Step 5 commit `feat(serve): local HTTP server for views`.

### Task 4: `serve` CLI command

**Files:** Modify `src/arch_blueprint/__main__.py` (`_add_serve`, `_serve`, `_COMMANDS`, top-level
epilog example); Test `tests/test_cli.py`.

- `arch-blueprint serve PROJECT_DIR [-m PATTERN ...] [--links module|class] [--port N] [--no-open]`.
- Roots: `detect_roots` via `_default_patterns` logic (its src-layout and empty-dir aborts; note
  `serving …`); with `-m`, roots = `_root_of(p)` of each. Before starting: build the first view
  (`patterns` = `-m` or `root.**`; `folded` = each root's direct subpackages for `module`) through
  `build_view`, mapping errors exactly like `_build` (exit 2). Then print `serving <url> (Ctrl-C to
  stop)` to stderr, open browser unless `--no-open`, `serve_forever`; `KeyboardInterrupt` → exit 0.
- The first request's state is passed to the page as the URL query (`?m=…&links=…&fold=…`).
- [ ] Step 1: tests — `serve -h` exit 0 with "examples:"; missing dir exit 2; `-m nope.*` exit 2
  with "no package"; neither starts a server (they fail before).
- [ ] Steps 2–4; Step 5 commit `feat(cli): serve command`.

### Task 5: Front end

**Files:** `src/arch_blueprint/serve/static/{index.html,viewer.js,viewer.css}`,
`static/vendor/{cytoscape.min.js,elk.bundled.js,cytoscape-elk.js,LICENSES.md}`.

- Layout: top bar (level select, metric select, search box, "⧉ CLI command"), left tree with
  checkboxes and fold toggles, centre cytoscape canvas, right inspector. Light/dark via
  `prefers-color-scheme`.
- State `{patterns, folded, links, metric, focus}` ↔ URL query (`history.replaceState`); any
  change → `POST /api/view` → redraw with `elk` layered, direction DOWN, previous positions kept
  for unchanged ids where possible.
- Canvas: frames = compound parents; folded nodes styled as packages (double border); cycles =
  red two-headed edge; tangle links red; dblclick a folded node → unfold; dblclick a frame → fold
  it (drop folded under it); click node → focus (neighbors + their edges full opacity, rest 0.15),
  inspector lists metrics, depends-on, used-by; click edge → inspector lists `imports`; Esc clears.
- Tree: checkbox per package/module → patterns (`pkg.**` for a fully checked package, bare name
  for a module leaf, minimal set); a package row has a fold toggle mirroring `folded`.
- Errors → banner with `error`.
- [ ] Step 1: download vendored files (approved), add licences.
- [ ] Step 2: write the page.
- [ ] Step 3: manual check in the browser pane on `examples/project_root` and on this project's
  `src` — fold/unfold, focus, edge imports, search, reload keeps state, CLI command copied and
  run; screenshot.
- [ ] Step 4: commit `feat(serve): interactive viewer page`.

### Task 6: Docs

README `serve` section; CLAUDE.md: command, `serve/` layer (fold, view, server, static), new test
files. Full `uv run pre-commit run -a`. Commit `docs: serve command`.
