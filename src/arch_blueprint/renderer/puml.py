import textwrap

from arch_blueprint.modules import BlueprintModule
from arch_blueprint.renderer.base import BlueprintRenderer


class PlantUmlRenderer(BlueprintRenderer):
    """Renders PlantUML diagrams from blueprint modules."""

    def render(self, target_modules: list[BlueprintModule]) -> str:
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

        return header + body + footer

    def _render_classes(self, blueprint_modules: list[BlueprintModule]) -> str:
        class_lines = []
        for blueprint_module in blueprint_modules:
            color = self.get_color_for_depth(blueprint_module.depth)
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
