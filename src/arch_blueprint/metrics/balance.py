from __future__ import annotations

from collections.abc import Mapping
from typing import Optional

from arch_blueprint.domain.graph import BlueprintGraph, MetricValue
from arch_blueprint.metrics._coupling import link_distances
from arch_blueprint.metrics.base import NO_OPTIONS, MetricOption, MetricOptions

BALANCED = "balanced"
TOO_FAR = "too-far"

STRENGTH = "strength"
DISTANCE = "distance"

_Pair = tuple[str, str]


class BalanceMetric:
    """Whether a link carries too much knowledge across too far a boundary.

    The balanced-coupling model (Khononov) calls coupling balanced when strength
    and distance counterbalance each other: a lot of shared knowledge is fine
    between neighbours, and a distant boundary is fine if little crosses it.
    Strength is approximated by how many imports stand behind the link, distance
    by the package-tree gap between its farthest modules. Volatility, the model's
    third dimension, is not an input: it needs change history, which would make
    the output non-deterministic.

    **Where each dimension becomes "too much" is the caller's call, not ours.**
    Import counts are close to degenerate in real projects -- 22 of wemake's 29
    links carry exactly one import, 280 of aiohttp's 281 -- so a rank-based cut
    lands on the floor and "above the threshold" comes to mean "more than one
    import". Every automatic rule tried (quartile, Tukey fence, largest gap)
    broke on some real graph. So: no threshold, no verdict. Ask for the metric
    with none set and it says nothing, while the diagram's legend reports the
    values it saw -- which is what a threshold should be picked from.

    Each threshold given narrows the verdict; one left out does not constrain.
    """

    name = "balance"
    title = "balance"
    description = (
        "a thick arrow marks a link clearing every threshold below; "
        "on a cycle the verdict is named in text instead"
    )
    render: Optional[str] = "balance_mark"
    options: tuple[MetricOption, ...] = (
        MetricOption(STRENGTH, "imports a link must carry to count as strong"),
        MetricOption(DISTANCE, "tree steps a link must span to count as distant"),
    )

    def compute(
        self,
        graph: BlueprintGraph,
        options: MetricOptions = NO_OPTIONS,
    ) -> Mapping[_Pair, MetricValue]:
        strength_bar = options.get(STRENGTH)
        distance_bar = options.get(DISTANCE)
        if strength_bar is None and distance_bar is None:
            return {}

        distances = link_distances(graph)
        verdicts: dict[_Pair, MetricValue] = {}
        for link in graph.links:
            pair = (link.source_namespace, link.target_namespace)
            strong = strength_bar is None or len(link.edges) >= strength_bar
            distant = distance_bar is None or distances[pair] >= distance_bar
            verdicts[pair] = TOO_FAR if strong and distant else BALANCED
        return verdicts
