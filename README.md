# Description

Generate modules import graph for python project. Using `plantuml` for render.

# Installation

```shell
pip install arch-blueprint
```

# Usage

```shell
arch-blueprint --help
usage: arch-blueprint [-h] --modules [MODULES ...] [--format {puml,d2}]
                      [--metric NAME] [--no-cycle-details]
                      project_dir

Generate architecture diagrams for Python applications

positional arguments:
  project_dir           Path to root directory of target project

options:
  -h, --help            show this help message and exit
  --modules, -m [MODULES ...]
                        Selected modules for rendering (examples:
                        'myapp.somemodule', 'myapp.somemodule.*',
                        'myapp.*.*.models.*', 'myapp.somemodule.**')
  --format, -f {puml,d2}
                        Output format. Possible values: ['puml', 'd2']
  --metric NAME         Display a metric (repeatable). A node metric renders
                        as a block on each node (e.g. --metric fan_in); a link
                        metric renders as a label on each connection (e.g.
                        --metric edge_weight).
  --no-cycle-details    Hide detailed information for cyclic dependencies
```

A run against the bundled example project:

```shell
arch-blueprint examples/project_root -m 'app1.*' -m 'app2.*' -m 'plugins.**'
```

```puml
@startuml
!theme amiga

top to bottom direction
hide empty members

package app1 <<(P, #95A5A6)>> {
  class app1.models <<(M, #2ECC71)>>
}
package app2 <<(P, #95A5A6)>> {
  class app2.service <<(M, #2ECC71)>>
}
package plugins <<(P, #95A5A6)>> {
  class plugins.auth.backend <<(M, #1ABC9C)>>
}

app2 ---> app1
app2 ---> plugins
@enduml
```

### How the diagram is built

A **node** is a module. A **link** is aggregated to the namespace where two modules first differ, so
`app2.service` importing `app1.models` is drawn as `app2 ---> app1`. Those endpoints are declared as
`package` blocks with the modules inside, so the emitted source names everything it points at.
(PlantUML would also infer the container from the dotted class names and render the same picture —
declaring it is about the source saying what it means, not about fixing the image.) A namespace that
is itself a module (`writer` importing `storage.backend`) stays a plain class: wrapping a class in a
package of its own name is a syntax error.

`-m` is repeatable, which is how you graph sibling packages under a root that has no `__init__.py`
of its own. A link is drawn when both endpoints belong to the selected set — including a dependency
*on* a package whose children were selected, since `pkg.*` never selects `pkg` itself.

### Errors

Bad input is reported on stderr and exits 2; an analysis that cannot finish exits 1. Nothing fails
silently — a mistyped metric name is an error listing the valid ones, and a pattern matching no
modules is an error rather than an empty diagram.

```shell
$ arch-blueprint examples/project_root -m 'app1.*' --metric fanin
arch-blueprint: unknown metric 'fanin'. Available: depth, edge_weight, fan_in, fan_out, instability
```

### Metrics

`--metric NAME` is repeatable and displays a metric. Where it is drawn depends on what it measures:

| Metric | Kind | Drawn as |
| --- | --- | --- |
| `fan_in` | node | a row in the node's block |
| `fan_out` | node | a row in the node's block |
| `instability` | node | a row in the node's block — `fan_out / (fan_in + fan_out)` |
| `edge_weight` | link | a label on the connection: how many imports it stands for |

Blocks appear in the order you asked for them. A cycle is one connection standing for two links, so
a link metric shows both values there as `forward/backward`, matching the order of the cycle's own
detail block.

New metrics are self-contained plugins under `src/arch_blueprint/metrics/`, registered in
`metrics/__init__.py` — no changes to the extractor or renderers are needed. See `CLAUDE.md` for the
protocols.

## Development

This project uses [`uv`](https://docs.astral.sh/uv/).

```shell
uv sync                       # install deps
uv run pytest                 # run the test suite
uv run pre-commit run -a      # lint, format, type-check, test (what CI runs)
```

# Examples

Generated with the code in this repository against released packages, so they can be reproduced:

```shell
pip install --target /tmp/pkgs fastapi taskiq
arch-blueprint /tmp/pkgs -m 'fastapi.*'
```

## FastAPI

`fastapi 0.141.1` — 27 modules, 65 links, 4 cycles.
Source: [`docs/images/fastapi.puml`](docs/images/fastapi.puml)

![FastAPI module graph](docs/images/fastapi.png)

## Taskiq

`taskiq 0.12.5` — 31 modules, 87 links, 6 cycles.
Source: [`docs/images/taskiq.puml`](docs/images/taskiq.puml)

![Taskiq module graph](docs/images/taskiq.png)

## With metrics

```shell
arch-blueprint /tmp/pkgs -m 'taskiq.*' \
  --metric fan_in --metric fan_out --metric instability
```

Every node carries its own block. `taskiq.abc` reads `fan_out: 13, instability: 1.0` — it depends on
thirteen modules and nothing depends on it, which is what an abstract-base module should look like.
`taskiq.compat` is the opposite at `fan_in: 8, instability: 0.0`. Cycles stay highlighted, with the
imports that cause them listed beside the connection.

Source: [`docs/images/taskiq_metrics.puml`](docs/images/taskiq_metrics.puml)

![Taskiq module graph with metrics](docs/images/taskiq_metrics.png)

# License

MIT — see [LICENSE](LICENSE).
