# arch-blueprint

Draws the import graph of a Python project as an architecture diagram, in
[PlantUML](https://plantuml.com) or [D2](https://d2lang.com) source or as a PNG. It also shows what
a branch changed in that graph, and how the graph grew commit by commit.

![Example project graph](docs/images/example.png)

Each box is a module. An arrow means a module on one side imports a module on the other. Arrows
are drawn between packages, at the level where the two modules' paths part (`app2.service` →
`app1.models` is drawn as `app2 → app1`). A red double arrow is a **cycle**: two packages that
import each other.

- [Quick start](#quick-start)
- [Choosing what to draw](#choosing-what-to-draw)
- [Commands](#commands): [`draw`](#draw), [`render`](#render), [`diff`](#diff), [`history`](#history)
- [Metrics](#metrics)
- [Troubleshooting](#troubleshooting)
- [Examples](#examples)

## Quick start

```shell
pip install arch-blueprint
```

Point it at the directory **your packages sit in**: `src` for a src layout, otherwise usually the
repository root.

```shell
arch-blueprint draw src                 # PlantUML source on stdout
arch-blueprint draw src -o arch.puml    # the same, into a file
arch-blueprint draw src -o arch.png     # an image (needs `plantuml` on PATH)
arch-blueprint draw src -o arch.d2      # D2 source
```

To view a `.puml` without installing anything, paste it into the
[PlantUML web server](https://www.plantuml.com/plantuml). For `.d2` there's the
[D2 playground](https://play.d2lang.com). Or install the tool once (`brew install plantuml` /
`brew install d2`) and ask for a `.png` directly.

With no `-m`, every package in the directory is drawn whole, and the tool says which ones it
picked:

```
$ arch-blueprint draw examples/project_root -o example.png
arch-blueprint: drawing app1, app2, plugins (all modules; narrow with -m)
```

`arch-blueprint --help` lists the commands, and `arch-blueprint COMMAND --help` shows each
command's options with examples.

## Choosing what to draw

`-m PATTERN` chooses the modules. Repeat it to draw several packages together, with the links
between them:

| Pattern | Selects |
| --- | --- |
| `myapp.*` | the modules and subpackages directly inside `myapp` |
| `myapp.**` | everything under `myapp`, at any depth |
| `myapp.*.models` | `models` in every direct subpackage of `myapp` |
| `myapp` | `myapp` itself, drawn as **one box** (the tool warns you) |

```shell
arch-blueprint draw src -m 'myapp.*'
arch-blueprint draw . -m 'app1.*' -m 'app2.*' -m 'plugins.**'
```

Quote the patterns, or the shell expands the `*` itself.

A link is drawn only when both of its ends are selected. That includes a dependency *on* a
package whose children you selected: `pkg.*` never selects `pkg` itself, but an import of `pkg`
still counts.

## Commands

| Command | What it does |
| --- | --- |
| `draw PROJECT_DIR` | draws the project's import graph |
| `render SNAPSHOT` | draws a snapshot saved by `draw -o graph.json` |
| `diff` | draws what changed between two snapshots or two git revisions |
| `history PROJECT_DIR` | writes one diagram and one diff per commit that changed the graph |

Output goes to stdout unless `-o FILE` is given. Without `-f`, the extension of `-o` picks the
format:

| `-f` | `-o` extension | Output |
| --- | --- | --- |
| `puml` (default) | `.puml` | PlantUML source |
| `d2` | `.d2` | D2 source |
| `puml-png` | `.png` | image drawn by `plantuml` from `PATH` |
| `d2-png` | — | image drawn by `d2` from `PATH` |
| `json` (`draw` only) | `.json` | a snapshot, for `render` and `diff` |

A missing `plantuml` / `d2` is reported before any work starts.

### draw

```shell
arch-blueprint draw src                                   # every package in src/
arch-blueprint draw src -m 'myapp.*' -o arch.png          # one package, as an image
arch-blueprint draw src --metric fan_in --metric fan_out  # with metrics on the boxes
arch-blueprint draw src --no-cycle-details                # without the notes on cycles
```

Every cycle gets a note listing the imports that make it up, so you can see which ones to break:

```shell
arch-blueprint draw tests/fixtures/cyclic -m 'pkg_a.*' -m 'pkg_b.*'
```

```puml
pkg_a <-[#C0392B,bold]-> pkg_b
note on link
  **pkg_a -> pkg_b:**
  - core → util
  - services → util
  **pkg_b -> pkg_a:**
  - util → core
end note
```

A namespace that is itself a module (`writer` importing `storage.backend`) stays a plain box.
Packages without an `__init__.py` (PEP 420 namespace packages) work as well.

### render

`draw -o graph.json` (or `-f json`) saves a **snapshot** instead of a picture: the modules, the
imports between them and every metric. `render` draws a snapshot later, in any format and with any
metrics, and the result is byte for byte what `draw` would have produced:

```shell
arch-blueprint draw src -m 'myapp.*' -o graph.json
arch-blueprint render graph.json -o graph.png --metric instability
```

### diff

`diff` draws the graph with the changes marked on it. It can compare two snapshots:

```shell
arch-blueprint diff old.json new.json -o diff.png
```

Or, when the project is in git, a revision against the working tree (or against `--head REV`). No
stored files are needed:

```shell
arch-blueprint diff --base origin/main src -o diff.png
arch-blueprint diff --base v1.0 --head v2.0 src -m 'myapp.*'
```

![Diff: a module and link added, a module and link removed](docs/images/diff.png)

Unchanged parts are drawn as on a plain diagram. Every change is dashed and has a color and a
label of its own:

| Marker | Module | Dependency |
| --- | --- | --- |
| added | green, spot `+`, `«added»`, dashed frame | green dashed arrow, `added` |
| removed | red, spot `-`, `«removed»`, dashed frame | red dashed arrow, `removed` |
| new cycle | — | red dashed `<->`, `NEW CYCLE` |
| cycle resolved | — | grey dashed arrow, `cycle resolved`, in the direction that remains (a bare line if neither does) |

- `--changes-only` draws just the changes and the modules they touch. That helps on a large
  project.
- `--cycle-details` adds the notes that list a cycle's imports. A diff is a quick look, so they
  are off by default.
- A package that exists on one side only is shown as added or removed; it doesn't fail the run.
- When nothing changed, you still get a valid diagram, with "No architectural changes" in the
  legend.

`diff` exits like `diff(1)`: **0** when nothing changed, **1** when something did, **2** on an
error. The diagram is written either way. In CI, to fail on errors but not on changes:

```shell
arch-blueprint diff --base origin/main src -o diff.png || test $? -eq 1
```

### history

`history` walks the branch's first-parent history (one commit per merged pull request). For every
commit that changed the graph, it writes the full diagram and the diff against the previous one.
Commits that leave the graph alone are skipped.

```shell
arch-blueprint history src                                         # every package in src/
arch-blueprint history src myapp -f puml-png                       # one package, as images
arch-blueprint history src app1 app2 -m 'app1.*' -m 'app2.core.*'  # packages narrowed by -m
arch-blueprint history src myapp --base v1.0 --head main -o album
```

```
blueprint-history/                    (or -o DIR)
  0001_2026-05-02_ab12cd3.png         the first frame: the diagram only
  0002_2026-05-12_ef45ab6.diff.png    what changed
  0002_2026-05-12_ef45ab6.png         what it became
  index.md                            the frames in order, with dates and commit subjects
```

- **ROOTs.** The packages named after `PROJECT_DIR` are the ones drawn, each whole unless `-m`
  narrows it. With none named, it's every package the project has at `--head`. A package that a
  commit doesn't have yet is no error: the commit is reported as `no source yet`, and the package
  shows up in the first frame that has its code.
- **One kind of file.** An album holds either sources (`-f puml`, `-f d2`) or images
  (`-f puml-png`, `-f d2-png`).
- **Caching.** Snapshots and images are cached in `./.arch-blueprint` (`--cache-dir`). After a
  failed image, rerunning redraws only what is missing, and another album of the same history
  reuses the cache.
- **Large diagrams.** d2 refuses to rasterize very large diagrams. Such a diagram is redrawn at
  half the scale, then at half again; `--scale FACTOR` sets the starting scale. PlantUML's size
  limit is raised to 16384 px (`PLANTUML_LIMIT_SIZE`; a value you set yourself wins).
- **Reruns.** Unchanged files are not rewritten. Frame files from an earlier run that this run
  didn't produce are removed; nothing else in the directory is touched.
- **Broken commits.** A commit whose code can't be analyzed is reported as `skipped`, with the
  reason.

## Metrics

`--metric NAME` shows a metric; repeat it for more. `arch-blueprint --list-metrics` prints this
list:

| Metric | On | Meaning |
| --- | --- | --- |
| `fan_in` | each box | how many modules depend on this one |
| `fan_out` | each box | how many modules this one depends on |
| `instability` | each box | `fan_out / (fan_in + fan_out)`: 0 = only depended upon, 1 = only depends on others |
| `edge_weight` | each arrow | how many module imports the arrow stands for |

The metrics appear in the order you ask for them. A cycle is one arrow standing for two links, so
`edge_weight` shows both values there, as `forward/backward`.

```shell
arch-blueprint draw tests/fixtures/cyclic -m 'pkg_a.*' -m 'pkg_b.*' \
  --metric fan_in --metric fan_out --metric instability --metric edge_weight
```

![Metrics on nodes and on a cyclic connection](docs/images/metrics.png)

`pkg_b.util` is depended on twice and depends on one module, so `instability: 0.33`. The arrow is a
cycle, so `edge_weight` reads `2/1`: two imports one way and one the other.

New metrics are self-contained plugins under `src/arch_blueprint/metrics/`. See `CLAUDE.md` for
the protocols.

## Troubleshooting

Errors are one line on stderr and exit 2 (1 when an analysis or an image could not finish; `diff`
uses its own codes, see above). Nothing fails silently: a pattern that matches no module is an
error, not an empty diagram. Common mistakes:

| Message | What to do |
| --- | --- |
| `a command comes first now — run: arch-blueprint draw …` | Earlier versions had no command word (`arch-blueprint DIR -m …`). Put `draw` first. |
| `src is itself a package — pass the directory that contains it` | `PROJECT_DIR` is the directory the packages sit in, not a package. |
| `. keeps its packages in src` | A src layout: run `arch-blueprint draw src`. |
| `no package 'myap' in src (found: myapp, tests)` | A typo in `-m`; the message lists the packages that exist. |
| `no modules matched: 'myapp.zzz.*'` | The package exists but the pattern selects nothing inside it. |
| `-m 'myapp' draws the package as a single box` | Use `myapp.*` or `myapp.**`. |
| `-m took 'src' as a pattern` | `-m` takes every value up to the next option: put `PROJECT_DIR` first, or give one pattern per `-m`. |
| `-f puml-png needs 'plantuml' on PATH` | Install PlantUML / D2, or write source (`-o x.puml`) and view it online. |
| `unknown metric 'fanin'. Available: …` | See `arch-blueprint --list-metrics`. |

A pattern resolves against `PROJECT_DIR` first, then against the installed packages. Graphing
`arch_blueprint` itself always resolves to the running copy.

## Examples

Generated with this tool from released packages, so you can reproduce them:

```shell
pip install --target /tmp/pkgs wemake-python-styleguide fastapi taskiq
arch-blueprint draw /tmp/pkgs -m 'wemake_python_styleguide.*'
```

### wemake-python-styleguide

`wemake-python-styleguide 1.8.0`: 14 modules, 29 links, **no cycles**.
Source: [`docs/images/wemake.puml`](docs/images/wemake.puml)

This is what a layered codebase looks like when nothing points back up. `checker` sits alone at
the top, everything drains toward `types`, `constants` and `compat` at the bottom, and no arrow is
red.

![wemake-python-styleguide module graph](docs/images/wemake.png)

### FastAPI

`fastapi 0.141.1`: 27 modules, 65 links, 4 cycles.
Source: [`docs/images/fastapi.puml`](docs/images/fastapi.puml)

![FastAPI module graph](docs/images/fastapi.png)

### Taskiq

`taskiq 0.12.5`: 31 modules, 87 links, 6 cycles.
Source: [`docs/images/taskiq.puml`](docs/images/taskiq.puml)

![Taskiq module graph](docs/images/taskiq.png)

### With metrics

```shell
arch-blueprint draw /tmp/pkgs -m 'taskiq.*' \
  --metric fan_in --metric fan_out --metric instability
```

`taskiq.abc` reads `fan_out: 13, instability: 1.0`: it depends on thirteen modules and nothing
depends on it, which is what an abstract-base module should look like. `taskiq.compat` is the
opposite, at `fan_in: 8, instability: 0.0`.

Source: [`docs/images/taskiq_metrics.puml`](docs/images/taskiq_metrics.puml)

![Taskiq module graph with metrics](docs/images/taskiq_metrics.png)

## Development

This project uses [`uv`](https://docs.astral.sh/uv/).

```shell
uv sync                       # install deps
uv run pytest                 # run the test suite
uv run pre-commit run -a      # lint, format, type-check, test (what CI runs)
```

## License

MIT — see [LICENSE](LICENSE).
