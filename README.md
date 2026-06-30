# Description

Generate modules import graph for python project. Using `plantuml` for render.

# Installation

```shell
pip install arch-blueprint
```

# Usage

Commands
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
  --metric NAME         Show a metric block on each node (repeatable). e.g.
                        --metric fan_in
  --no-cycle-details    Hide detailed information for cyclic dependencies
```

### Metrics

- `--metric NAME` adds a per-node metric block (repeatable). Built-in metrics:
  `fan_in`, `fan_out`, `instability`. New metrics are added as self-contained
  plugins under `src/arch_blueprint/metrics/` and registered in
  `metrics/__init__.py` — no changes to the extractor or renderers are needed.

## Development

This project uses [`uv`](https://docs.astral.sh/uv/).

```shell
uv sync                       # install deps
uv run pytest                 # run the test suite
uv run pre-commit run -a      # lint, format, type-check, test (what CI runs)
```

# Examples

## FastAPI
[Commit](https://github.com/fastapi/fastapi/commit/9348a5e2cf55440ff3da3bd4b7876acd3b3f57e5)

Command:
```shell
arch-blueprint . -m 'fastapi.*'
```

### Graph
![Generated](https://img.plantuml.biz/plantuml/png/dPXTRjim3CVVTGeDVTc2Pi0-W0934HG8-hWJ38EXo6eYnFgOBQFB1NQ07N4dcH9_n99eK-bB6XG_KYBv9sddgN6iTgsgo3jt44fGfkIU4UACfSxGdN7EA5hAMd0dZIO7MGegb7KdgeJQYReXX5UiQUWBywwi_5YBNwreN4CV7zz_lwTtdv-tsuTF7pQRY2k55ReKcak1iaMXcDH5WVfapd-hM-xQ6lVg4MjqWuFYDnVs73xkqhHEwdssm-B0T5dvB68MEyQFU-zTbnZ9AuaXIfR-q5TM2unqlfBUeT0E3KbpKsO4mgoj96TPsJHU8VulXbLclnSrcXUZULlN_fud3FKrhD3BMLOpLRoqccV5qWX_kdJesUvaSK7wJoVvYwnmz5Ni6iEF0cz8vzkwOZdoBRXHbg6Ik6G8E9OaRRrUhpTJ0PFafFMFk-U7hzils_kTgSgV4xmN2T762MeqhQG-4afNgzX7QlDjjVBaEedhtv-_rCl5_rEx9l0rA7BYgpUAVGtasLU44Z_twFcwjuJP9VEcA3kJfI0ZvrD_VV7mG7lmfZY3UbyKFoB1V0YuSBXd6AHJzXQZ7BYRF1dWTU9cm8EYSRAl6mxsUoc3pAt6PKOIk3OXEQW1NFnl9A_hC0EUJFuC6X30F1m9O1wCAZKF3diY0mrBDS-5fHeNzMBgOGh83Go6LmCUTqAtlOzy0-0UY4cK18I-RitHP1pz6JC9PYS5MYQJVC1KcWIGYpGwFbIzVTS0Mn3UDT0IpDerCmjwickKpv0lQB9Ym1ICJ_e85ar940gb3IAXrk87nSM-MuJZnR08HnDdo36YeE45Pl6I83JJ2Z0BjG989gq0Kvc1H3a1cR2-umlTVBTqrPvjbl6Go2BMzi1DUwLpFVNMlPgaceszTTpKro3kf6F6DnCifJ0OYnAc8gcIA9ubjG78ZDO0SXB6au_y_4C7-Gy0)
```puml
@startuml
!theme amiga

top to bottom direction
hide empty members

class fastapi.params <<(M, #2ECC71)>>
class fastapi.exception_handlers <<(M, #2ECC71)>>
class fastapi.datastructures <<(M, #2ECC71)>>
class fastapi.testclient <<(M, #2ECC71)>>
class fastapi.types <<(M, #2ECC71)>>
class fastapi.routing <<(M, #2ECC71)>>
class fastapi.logger <<(M, #2ECC71)>>
class fastapi.param_functions <<(M, #2ECC71)>>
class fastapi.utils <<(M, #2ECC71)>>
class fastapi.exceptions <<(M, #2ECC71)>>
class fastapi.staticfiles <<(M, #2ECC71)>>
class fastapi.middleware <<(M, #2ECC71)>>
class fastapi.cli <<(M, #2ECC71)>>
class fastapi.applications <<(M, #2ECC71)>>
class fastapi.background <<(M, #2ECC71)>>
class fastapi.encoders <<(M, #2ECC71)>>
class fastapi.concurrency <<(M, #2ECC71)>>
class fastapi.templating <<(M, #2ECC71)>>
class fastapi._compat <<(M, #2ECC71)>>
class fastapi.dependencies <<(M, #2ECC71)>>
class fastapi.openapi <<(M, #2ECC71)>>
class fastapi.__main__ <<(M, #2ECC71)>>
class fastapi.responses <<(M, #2ECC71)>>
class fastapi.requests <<(M, #2ECC71)>>
class fastapi.security <<(M, #2ECC71)>>
class fastapi.websockets <<(M, #2ECC71)>>

fastapi.__main__ ---> fastapi.cli
fastapi._compat <-[#E74C3C,bold]-> fastapi.openapi
note on link
  **fastapi._compat -> fastapi.openapi:**
  - fastapi._compat → constants
  **fastapi.openapi -> fastapi._compat:**
  - fastapi.openapi → fastapi._compat
end note
fastapi._compat <-[#E74C3C,bold]-> fastapi.params
note on link
  **fastapi._compat -> fastapi.params:**
  - fastapi._compat → fastapi.params
  **fastapi.params -> fastapi._compat:**
  - fastapi.params → fastapi._compat
end note
fastapi._compat ---> fastapi.types
fastapi.applications ---> fastapi.datastructures
fastapi.applications ---> fastapi.exception_handlers
fastapi.applications ---> fastapi.exceptions
fastapi.applications ---> fastapi.logger
fastapi.applications ---> fastapi.middleware
fastapi.applications ---> fastapi.openapi
fastapi.applications ---> fastapi.params
fastapi.applications ---> fastapi.routing
fastapi.applications ---> fastapi.types
fastapi.applications ---> fastapi.utils
fastapi.datastructures ---> fastapi._compat
fastapi.dependencies ---> fastapi._compat
fastapi.dependencies ---> fastapi.background
fastapi.dependencies ---> fastapi.concurrency
fastapi.dependencies ---> fastapi.exceptions
fastapi.dependencies ---> fastapi.logger
fastapi.dependencies ---> fastapi.params
fastapi.dependencies ---> fastapi.security
fastapi.dependencies ---> fastapi.types
fastapi.dependencies ---> fastapi.utils
fastapi.encoders ---> fastapi._compat
fastapi.encoders ---> fastapi.exceptions
fastapi.encoders ---> fastapi.types
fastapi.exception_handlers ---> fastapi.encoders
fastapi.exception_handlers ---> fastapi.exceptions
fastapi.exception_handlers ---> fastapi.utils
fastapi.exception_handlers ---> fastapi.websockets
fastapi.openapi ---> fastapi.datastructures
fastapi.openapi ---> fastapi.dependencies
fastapi.openapi ---> fastapi.encoders
fastapi.openapi ---> fastapi.exceptions
fastapi.openapi ---> fastapi.logger
fastapi.openapi <-[#E74C3C,bold]-> fastapi.params
note on link
  **fastapi.openapi -> fastapi.params:**
  - fastapi.openapi → fastapi.params
  **fastapi.params -> fastapi.openapi:**
  - fastapi.params → models
end note
fastapi.openapi ---> fastapi.responses
fastapi.openapi ---> fastapi.routing
fastapi.openapi ---> fastapi.types
fastapi.openapi ---> fastapi.utils
fastapi.param_functions ---> fastapi._compat
fastapi.param_functions ---> fastapi.openapi
fastapi.param_functions ---> fastapi.params
fastapi.params ---> fastapi.exceptions
fastapi.routing ---> fastapi._compat
fastapi.routing ---> fastapi.datastructures
fastapi.routing ---> fastapi.dependencies
fastapi.routing ---> fastapi.encoders
fastapi.routing ---> fastapi.exceptions
fastapi.routing ---> fastapi.params
fastapi.routing ---> fastapi.types
fastapi.routing <-[#E74C3C,bold]-> fastapi.utils
note on link
  **fastapi.routing -> fastapi.utils:**
  - fastapi.routing → fastapi.utils
  **fastapi.utils -> fastapi.routing:**
  - fastapi.utils → fastapi.routing
end note
fastapi.security ---> fastapi.exceptions
fastapi.security ---> fastapi.openapi
fastapi.security ---> fastapi.param_functions
fastapi.utils ---> fastapi._compat
fastapi.utils ---> fastapi.datastructures
fastapi.utils ---> fastapi.exceptions
@enduml
```

## Taskiq
[Commit](https://github.com/taskiq-python/taskiq/commit/eb29304a697f151439c12132480c4c5b8247bfa4)
Command:
```shell
arch-blueprint . -m 'taskiq.*' '*.brokers.*' '*.scheduler.*'
```

### Graph
![taskiq_graph](https://img.plantuml.biz/plantuml/png/fPXTRjGm4CVVSugWli2gMwc0X41LLLZraHCW57aJisisZbF7ATqUW0DmH4w2asms7jjZ6tZgn_moyVpdmtRkEaMawdcTlL1xocbEEDkHB5EYpPN8jq8fmVEAILeg9ffipogQKzwgOyuftrBPPLbPawxB5UaExE6gA_Uqwcigbz_ocvkNdo_pY-kFdpRlDwzkR-4JBIaFP4TdwlNzPlFksg5AmLkY8b1HSCAQeeZvgbc4qAges8hc-8fEzBAaNGJdhAfg-eF8ABcLug25lUhs6gwAwS-8Y1KjXOpuFR3IS8H0lM9rwWAV-KFQwkWZRLJCAzcMCSMfPAHcp_hTCR5fryLhYhInEYX5e-XJhEnqIljQ5LjToBIfOcjZJQTapxKYP6Yfn2gJEYQveyMtlXaxiOj8NfCjZIPILsF3cbqC6zuPPOJaHAbuQeOVYNbEqMUkHTReUIJaCQqW5rLBINMhLyNydyY3EiMn0EbJILkG8hHiIieUentfJjIgC4L4LZeLfUixisVbUhs-DNemCzeHc7Jafkrc_UNY_jtRpPlDvLRKrTU576THrWWzGNNwQjOSiZnVhKo_aFsmMcbYRGw2tpz_GNU6XsdMWKLR7YPYy35LWzzc3V1Czsu-h1fJO9fYgFMSzZILbeP9b6fv0D6hbUBfM9mnqvFHdI7T3CmldWKixuffTnh8c7agrZJXh6cRg9xr529XrND-D9tOepsadiqE3k7_l3BXaPuxFp76Cuz41-U7wMSvgta3T8Qahtq6SF5ZrGyqf7HUG9Rb690gpF848ittJZJ5WW5jZ5D7AFqcDmQvU8jrntZSn8pZYGmppZlusQwFDDX0jqtcGBTi-eICcUPT2xClHGjtQ6nPFlCqyWC07CLUmXd7Fcew4eS8Qt3v45iH7mEIEDm_43KSav4assQ_rxOxcPXFizYxFMPNHXzbYUH3G8cVTd0q4QxTYSL5nfdcsU_CiXulaH782cOw_8OrSHcueRbsSx7sXG1fn11cN2upe2YMQuyLYkC1tBWzq7Jl202MlFEbz3ysmVabqNtm10x3sTxH4EplTipfmU2c2SlTtHcXtTutF7AQXUGnWxaptuhnV9aVAP3AmH1OFXZbrX16mec0KLOrOHXin_F52mdHRpSciHU00Y38E1Y3ZAkG5xC2zp89KOEnx2L01PqkbQ6m7G3SvY5ddAlHPJkVsP2a1Jbd-p3QDwYzdpERpay0rG9V6xoBj2xwhXlxKz2_UV6lFFey-3Y3LmBEkIeFFx2yEZRu6iUSuFrKO7UwyeOltzaV)

```plantuml
@startuml
!theme amiga

top to bottom direction
hide empty members

class taskiq.scheduler.scheduler <<(M, #1ABC9C)>>
class taskiq.package <<(M, #2ECC71)>>
class taskiq.compat <<(M, #2ECC71)>>
class taskiq.__main__ <<(M, #2ECC71)>>
class taskiq.cli <<(M, #2ECC71)>>
class taskiq.state <<(M, #2ECC71)>>
class taskiq.schedule_sources <<(M, #2ECC71)>>
class taskiq.middlewares <<(M, #2ECC71)>>
class taskiq.brokers.shared_broker <<(M, #1ABC9C)>>
class taskiq.decor <<(M, #2ECC71)>>
class taskiq.kicker <<(M, #2ECC71)>>
class taskiq.utils <<(M, #2ECC71)>>
class taskiq.brokers.zmq_broker <<(M, #1ABC9C)>>
class taskiq.events <<(M, #2ECC71)>>
class taskiq.abc <<(M, #2ECC71)>>
class taskiq.serializers <<(M, #2ECC71)>>
class taskiq.message <<(M, #2ECC71)>>
class taskiq.api <<(M, #2ECC71)>>
class taskiq.context <<(M, #2ECC71)>>
class taskiq.result_backends <<(M, #2ECC71)>>
class taskiq.instrumentation <<(M, #2ECC71)>>
class taskiq.scheduler.merge_functions <<(M, #1ABC9C)>>
class taskiq.labels <<(M, #2ECC71)>>
class taskiq.warnings <<(M, #2ECC71)>>
class taskiq.funcs <<(M, #2ECC71)>>
class taskiq.formatters <<(M, #2ECC71)>>
class taskiq.task <<(M, #2ECC71)>>
class taskiq.serialization <<(M, #2ECC71)>>
class taskiq.brokers.inmemory_broker <<(M, #1ABC9C)>>
class taskiq.scheduler.created_schedule <<(M, #1ABC9C)>>
class taskiq.acks <<(M, #2ECC71)>>
class taskiq.exceptions <<(M, #2ECC71)>>
class taskiq.receiver <<(M, #2ECC71)>>
class taskiq.scheduler.scheduled_task <<(M, #1ABC9C)>>
class taskiq.result <<(M, #2ECC71)>>

taskiq.__main__ ---> taskiq.abc
taskiq.abc ---> taskiq.acks
taskiq.abc <-[#E74C3C,bold]-> taskiq.decor
note on link
  **taskiq.abc -> taskiq.decor:**
  - taskiq.abc → taskiq.decor
  **taskiq.decor -> taskiq.abc:**
  - taskiq.decor → broker
  - taskiq.decor → schedule_source
end note
taskiq.abc ---> taskiq.events
taskiq.abc ---> taskiq.exceptions
taskiq.abc <-[#E74C3C,bold]-> taskiq.formatters
note on link
  **taskiq.abc -> taskiq.formatters:**
  - taskiq.abc → proxy_formatter
  **taskiq.formatters -> taskiq.abc:**
  - taskiq.formatters → broker
  - taskiq.formatters → formatter
end note
taskiq.abc ---> taskiq.message
taskiq.abc ---> taskiq.result
taskiq.abc <-[#E74C3C,bold]-> taskiq.result_backends
note on link
  **taskiq.abc -> taskiq.result_backends:**
  - taskiq.abc → dummy
  **taskiq.result_backends -> taskiq.abc:**
  - taskiq.result_backends → result_backend
end note
taskiq.abc <-[#E74C3C,bold]-> taskiq.scheduler
note on link
  **taskiq.abc -> taskiq.scheduler:**
  - taskiq.abc → scheduled_task
  **taskiq.scheduler -> taskiq.abc:**
  - created_schedule → schedule_source
  - scheduler → broker
  - scheduler → schedule_source
end note
taskiq.abc <-[#E74C3C,bold]-> taskiq.serializers
note on link
  **taskiq.abc -> taskiq.serializers:**
  - taskiq.abc → json_serializer
  **taskiq.serializers -> taskiq.abc:**
  - taskiq.serializers → serializer
end note
taskiq.abc ---> taskiq.state
taskiq.abc ---> taskiq.utils
taskiq.abc ---> taskiq.warnings
taskiq.api ---> taskiq.abc
taskiq.api ---> taskiq.acks
taskiq.api ---> taskiq.cli
taskiq.api ---> taskiq.receiver
taskiq.api ---> taskiq.scheduler
taskiq.brokers ---> taskiq.abc
taskiq.brokers ---> taskiq.decor
taskiq.brokers ---> taskiq.events
taskiq.brokers ---> taskiq.exceptions
taskiq.brokers ---> taskiq.kicker
taskiq.brokers ---> taskiq.message
taskiq.brokers ---> taskiq.receiver
taskiq.brokers ---> taskiq.utils
taskiq.cli ---> taskiq.abc
taskiq.cli ---> taskiq.acks
taskiq.cli ---> taskiq.receiver
taskiq.cli ---> taskiq.scheduler
taskiq.context ---> taskiq.abc
taskiq.context ---> taskiq.exceptions
taskiq.context ---> taskiq.message
taskiq.context ---> taskiq.state
taskiq.decor ---> taskiq.kicker
taskiq.decor ---> taskiq.scheduler
taskiq.decor ---> taskiq.task
taskiq.formatters ---> taskiq.compat
taskiq.formatters ---> taskiq.message
taskiq.funcs ---> taskiq.exceptions
taskiq.funcs ---> taskiq.result
taskiq.funcs ---> taskiq.task
taskiq.instrumentation ---> taskiq.cli
taskiq.instrumentation ---> taskiq.middlewares
taskiq.kicker ---> taskiq.abc
taskiq.kicker ---> taskiq.compat
taskiq.kicker ---> taskiq.exceptions
taskiq.kicker ---> taskiq.labels
taskiq.kicker ---> taskiq.message
taskiq.kicker <-[#E74C3C,bold]-> taskiq.scheduler
note on link
  **taskiq.kicker -> taskiq.scheduler:**
  - taskiq.kicker → created_schedule
  - taskiq.kicker → scheduled_task
  **taskiq.scheduler -> taskiq.kicker:**
  - created_schedule → taskiq.kicker
  - scheduler → taskiq.kicker
end note
taskiq.kicker ---> taskiq.task
taskiq.kicker ---> taskiq.utils
taskiq.message ---> taskiq.labels
taskiq.middlewares ---> taskiq.abc
taskiq.middlewares ---> taskiq.compat
taskiq.middlewares ---> taskiq.exceptions
taskiq.middlewares ---> taskiq.kicker
taskiq.middlewares ---> taskiq.message
taskiq.middlewares ---> taskiq.result
taskiq.receiver ---> taskiq.abc
taskiq.receiver ---> taskiq.acks
taskiq.receiver ---> taskiq.compat
taskiq.receiver ---> taskiq.context
taskiq.receiver ---> taskiq.exceptions
taskiq.receiver ---> taskiq.message
taskiq.receiver ---> taskiq.result
taskiq.receiver ---> taskiq.state
taskiq.receiver ---> taskiq.utils
taskiq.result ---> taskiq.compat
taskiq.result ---> taskiq.serialization
taskiq.result_backends ---> taskiq.result
taskiq.schedule_sources ---> taskiq.abc
taskiq.schedule_sources ---> taskiq.scheduler
taskiq.scheduler ---> taskiq.exceptions
taskiq.scheduler ---> taskiq.task
taskiq.scheduler ---> taskiq.utils
taskiq.scheduler.created_schedule ---> taskiq.scheduler.scheduled_task
taskiq.scheduler.merge_functions ---> taskiq.scheduler.scheduled_task
taskiq.scheduler.scheduler ---> taskiq.scheduler.scheduled_task
taskiq.serialization ---> taskiq.compat
taskiq.serialization ---> taskiq.exceptions
taskiq.task ---> taskiq.abc
taskiq.task ---> taskiq.compat
taskiq.task ---> taskiq.exceptions
taskiq.task ---> taskiq.result
@enduml
```
