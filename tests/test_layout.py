from __future__ import annotations

import pytest

from arch_blueprint.renderer.layout import Frame, Layout, LayoutItem, common_prefix


def _shape(items: tuple[LayoutItem, ...]) -> list[object]:
    """A layout tree as plain data: a frame is ``(label, namespace, [items])``."""
    return [
        (item.label, item.namespace, _shape(item.items))
        if isinstance(item, Frame)
        else item
        for item in items
    ]


def _nested(nodes: list[str], endpoints: tuple[str, ...] = ()) -> list[object]:
    return _shape(Layout.build(nodes, set(endpoints), nested=True).items)


# --- nested: every prefix a frame, chains of empty ones merged ---------------


def test_a_chain_of_empty_frames_is_one_frame_labelled_by_its_path() -> None:
    assert _nested(["app.features.core.ep.Run", "app.features.core.ep.Stop"]) == [
        (
            "app.features.core.ep",
            "app.features.core.ep",
            ["app.features.core.ep.Run", "app.features.core.ep.Stop"],
        ),
    ]


def test_a_chain_is_merged_below_a_frame_that_stays() -> None:
    """``app`` holds two frames; ``app.x`` and ``app.x.y`` hold nothing but one."""
    assert _nested(["app.x.y.z.A", "app.w.B"]) == [
        (
            "app",
            "app",
            [("x.y.z", "app.x.y.z", ["app.x.y.z.A"]), ("w", "app.w", ["app.w.B"])],
        ),
    ]


def test_a_frame_an_arrow_ends_on_stays() -> None:
    """At the namespace level an arrow points at the container: it is drawn."""
    assert _nested(["a.b.c.X", "a.b.c.Y"], endpoints=("a.b", "a.b.c.X")) == [
        ("a.b", "a.b", [("c", "a.b.c", ["a.b.c.X", "a.b.c.Y"])]),
    ]


def test_a_frame_holding_a_node_stays() -> None:
    assert _nested(["a.X", "a.b.c.Y"]) == [
        ("a", "a", ["a.X", ("b.c", "a.b.c", ["a.b.c.Y"])]),
    ]


def test_a_frame_holding_two_frames_stays() -> None:
    assert _nested(["a.b.X", "a.c.Y"]) == [
        ("a", "a", [("b", "a.b", ["a.b.X"]), ("c", "a.c", ["a.c.Y"])]),
    ]


def test_a_prefix_that_is_a_node_is_no_frame() -> None:
    """``package a.b { class a.b }`` is a PlantUML syntax error."""
    assert _nested(["a.b", "a.b.C"]) == [("a", "a", ["a.b", "a.b.C"])]


def test_a_node_under_no_prefix_is_at_the_top() -> None:
    assert _nested(["Loose", "m.A"]) == ["Loose", ("m", "m", ["m.A"])]


def test_frames_sit_where_their_first_node_is_drawn() -> None:
    """Declaration order is layout order: the extractor's order is kept."""
    assert _nested(["b.X", "a.Y", "b.Z"]) == [
        ("b", "b", ["b.X", "b.Z"]),
        ("a", "a", ["a.Y"]),
    ]


def test_path_and_label_follow_the_frames() -> None:
    layout = Layout.build(["app.core.u.Run", "app.core.m.Task"], set(), nested=True)
    assert layout.path("app.core.u.Run") == ("app.core", "u", "Run")
    assert layout.label("app.core.u.Run") == "Run"
    assert layout.title == ""


# --- flat: the shared prefix stripped from every label -----------------------


@pytest.mark.parametrize(
    ("names", "prefix"),
    [
        (["a.b.c", "a.b.d"], "a.b"),
        (["a.b.c"], "a.b"),
        (["a.b", "a.b.c"], "a"),
        (["a.x", "b.x"], ""),
        (["a"], ""),
        (["ab.c", "a.c"], ""),
        ([], ""),
    ],
    ids=[
        "shared",
        "single",
        "leaves_label",
        "first_part",
        "one_part",
        "whole",
        "empty",
    ],
)
def test_common_prefix_is_whole_parts_and_leaves_every_label(
    names: list[str],
    prefix: str,
) -> None:
    assert common_prefix(names) == prefix


def test_flat_labels_drop_the_prefix_and_the_title_shows_it() -> None:
    layout = Layout.build(
        ["app.x.core.A", "app.x.util.B"],
        {"app.x.core.A", "app.x.util"},
        nested=False,
    )
    assert layout.items == ("app.x.core.A", "app.x.util", "app.x.util.B")
    assert layout.title == "app.x"
    assert layout.label("app.x.util") == "util"
    assert layout.path("app.x.core.A") == ("app.x.core.A",)


def test_flat_prefix_counts_what_a_drawn_id_stands_for() -> None:
    """A diff's shadowed ``a.pkg.(module)`` is module ``a.pkg``: it keeps ``pkg``."""
    layout = Layout.build(
        ["a.pkg.(module)", "a.pkg.sub"],
        set(),
        nested=False,
        base=lambda name: name.removesuffix(".(module)"),
    )
    assert layout.prefix == "a"
