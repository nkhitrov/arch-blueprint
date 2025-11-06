import textwrap
from collections.abc import Sequence
from typing import Optional

from arch_blueprint.modules import BlueprintModule


class PlantUmlRenderer:
    """Renders PlantUML diagrams from blueprint modules."""

    def __init__(self, colors: Optional[Sequence[str]] = None) -> None:
        self.colors = colors or [
            "#E74C3C",
            "#3498DB",
            "#2ECC71",
            "#1ABC9C",
            "#F39C12",
            "#9B59B6",
            "#27AE60",
            "#34495E",
            "#E67E22",
            "#8E44AD",
        ]

    def render(self, target_modules: list[BlueprintModule]) -> None:
        header = textwrap.dedent("""\
            @startuml
            !theme amiga

            top to bottom direction
            hide empty members

            """)

        body = self._render_classes(target_modules)
        body += self._render_links(target_modules)

        footer = textwrap.dedent("""\
            @enduml
        """)

        text = header + body + footer
        print(text)  # noqa: T201

    def _render_classes(self, blueprint_modules: list[BlueprintModule]) -> str:
        class_lines = []
        for blueprint_module in blueprint_modules:
            color = self.generate_color_code(blueprint_module.name)
            text = f"class {blueprint_module.name} <<(M, {color})>>\n"
            class_lines.append(text)

        return "\n".join(class_lines)

    def _render_links(self, blueprint_modules: list[BlueprintModule]) -> str:
        links = set()
        for blueprint_module in blueprint_modules:
            _links = blueprint_module.find_dependencies_namespace_to_namespaces()
            for link in _links:
                links.add(link)

        text = ""
        arrow = "--->"
        for from_, to_ in links:
            text += f"{from_} {arrow} {to_}\n"

        return text

    def generate_color_code(self, module: str) -> str:
        depth = len(module.rsplit("."))
        return self.colors[depth]
