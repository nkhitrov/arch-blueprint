from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MetricDisplay:
    """Which metrics to display, kept separate from renderer styling options.

    ``shown`` lists metric names selected for display (e.g. via ``--metric``).
    A metric is drawn only if its name is here; how it is drawn comes from the
    render plugin the metric references.
    """

    shown: tuple[str, ...] = ()
