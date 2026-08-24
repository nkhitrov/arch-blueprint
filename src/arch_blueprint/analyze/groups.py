from __future__ import annotations

from arch_blueprint.domain.graph import BlueprintGraph, Group


class GroupAnalyzer:
    """Works out which nodes a renderer may draw inside a namespace container.

    Links are aggregated to namespaces, while nodes are individual modules, so a
    link endpoint is frequently a name no node carries. A renderer that declares
    nothing for it emits an arrow to an undeclared element; PlantUML then invents
    an empty box and the real, metric-carrying nodes sit unconnected beside it.
    """

    @staticmethod
    def build(graph: BlueprintGraph) -> list[Group]:
        """Group nodes under the link endpoints that need a container.

        Three rules, each earned by a case that breaks otherwise:

        1. A namespace that *is* a node id gets no group — the endpoint is
           already declared, and ``package a.b { class a.b }`` is a PlantUML
           syntax error. On this project's own graph that covers 18 of 23
           endpoints.
        2. Namespaces nest, so a node joins the deepest one it lies under;
           declaring it in two containers would silently drop it.
        3. A node under no endpoint namespace joins no group and is drawn as it
           always was.
        """
        node_ids = {node.id for node in graph.nodes}
        endpoints = {link.source_namespace for link in graph.links}
        endpoints |= {link.target_namespace for link in graph.links}
        containers = sorted(endpoints - node_ids)

        members: dict[str, list[str]] = {namespace: [] for namespace in containers}
        for node in graph.nodes:
            owner = _deepest_container(node.id, containers)
            if owner is not None:
                members[owner].append(node.id)

        return [
            Group(namespace=namespace, members=tuple(members[namespace]))
            for namespace in containers
            if members[namespace]
        ]


def _deepest_container(node_id: str, containers: list[str]) -> str | None:
    owner: str | None = None
    for namespace in containers:
        if node_id.startswith(f"{namespace}.") and (
            owner is None or len(namespace) > len(owner)
        ):
            owner = namespace
    return owner
