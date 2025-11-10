import textwrap
from string import Template
from typing import Final

from arch_blueprint.modules import BlueprintModule
from arch_blueprint.renderer.base import (
    BlueprintRenderer,
)

_CLASS_TEMPLATE: Final = Template(
    textwrap.dedent(
        """\
    ${class_name}: {
      shape: class
      style: {
        fill: "$color"
      }
    }
    """,
    ),
)


class D2LangRenderer(BlueprintRenderer):
    """Renders D2lang diagrams from blueprint modules."""

    def render(self, target_modules: list[BlueprintModule]) -> str:
        header = "direction: right\n"
        body = self._render_classes(target_modules)
        body += self._render_links(target_modules)
        return header + body

    def _render_classes(self, blueprint_modules: list[BlueprintModule]) -> str:
        class_lines = []
        for blueprint_module in blueprint_modules:
            color = self.get_color_for_depth(blueprint_module.depth)
            text = _CLASS_TEMPLATE.substitute(
                {"class_name": blueprint_module.name, "color": color},
            )
            class_lines.append(text)
        return "\n".join(class_lines)

    def _render_links(self, blueprint_modules: list[BlueprintModule]) -> str:
        links = set()
        for blueprint_module in blueprint_modules:
            _links = blueprint_module.find_dependencies_namespace_to_namespaces()
            for link in _links:
                links.add(link)
        return "\n".join(f"{from_} -> {to_}\n" for from_, to_ in links)
