import textwrap

from arch_blueprint.objects.models import BlueprintObject, BlueprintPackage


class PlantUmlUseCaseRenderer:
    """Renders PlantUML diagrams from blueprint modules."""

    def render(self, packages: list[BlueprintPackage]) -> str:
        self.highlight_packages = {} #{"features.core.debts",}
        self.highlight_color = "chocolate"

        header = textwrap.dedent("""\
            @startuml
            !theme amiga

            left to right direction

            """)

        body = self._render_packages(packages)
        body += self._render_links(packages)

        footer = textwrap.dedent("""\
            @enduml
        """)

        return header + body + footer

    def _render_packages(self, packages: list[BlueprintPackage]) -> str:
        lines = []
        for package in packages:
            # todo set color by package
            text = self._render_usecases(package)
            lines.append(text)

            text = self._render_packages(package.packages)
            lines.append(text)

        return "\n".join(lines)

    def _render_usecases(self, package: BlueprintPackage) -> str:
        lines = []
        for usecase in package.objects:
            text = f'usecase {usecase.name}'
            if self.is_highlight_package(package):
                text += f" #back:{self.highlight_color}"

            name = usecase.name if usecase.title is None else f"\n{usecase.title}"
            text+= f' as "{name}\n<color:tan>{package.name}</color>"'
            lines.append(text)

        lines.append("")
        return "\n".join(lines)

    def _render_links(self, packages: list[BlueprintPackage]) -> str:
        links = self._collect_links(packages)
        links.append("\n")
        return "\n".join(links)

    def _collect_links(self, packages: list[BlueprintPackage]) -> list[str]:
        if len(packages) == 0:
            return []

        links = []
        for package in packages:
            for usecase in package.objects:
                for dep_usecase in usecase.dependencies:
                    text = f"{usecase.name} ---> {dep_usecase.name}"
                    if self.is_highlight_package(package):
                        text+= f" #{self.highlight_color};line.bold"
                    links.append(text)

            links.extend(self._collect_links(package.packages))

        return links

    def is_highlight_package(self, package: BlueprintPackage) -> bool:
        for p_name in self.highlight_packages:
            if package.name.startswith(p_name):
                return True

        return False
