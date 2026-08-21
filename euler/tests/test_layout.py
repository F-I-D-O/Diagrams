"""Tests for the rectangular Euler diagram layout algorithm."""

from pathlib import Path

import pytest

from euler_diagrams import (
    LayoutError,
    NotRealizableError,
    SetSystem,
    layout_2d,
    load_set_system,
)
from euler_diagrams.layout import _scan_axis
from euler_diagrams.poset import ATTR, OBJ, extended_euler_poset
from euler_diagrams.realizer import find_realizer, realizes

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


def make_system(sets: dict[str, list[str]], name: str | None = None) -> SetSystem:
    return SetSystem(
        sets={set_name: frozenset(members) for set_name, members in sets.items()},
        name=name,
    )


def assert_faithful(system: SetSystem, layout) -> None:
    """Every element's point must lie exactly in the rectangles of its sets."""
    for set_name, members in system.sets.items():
        for element in system.elements:
            assert layout.rectangles[set_name].contains(layout.points[element]) == (
                element in members
            ), f"membership of ({element}, {set_name}) misrepresented"


def contranominal(size: int) -> SetSystem:
    """The contranominal scale: element i is in every set but the i-th."""
    return make_system(
        {
            f"m{i}": [f"g{j}" for j in range(size) if j != i]
            for i in range(size)
        }
    )


def test_scan_axis_hand_checked_example() -> None:
    first = [(OBJ, "x"), (ATTR, "A"), (OBJ, "y"), (ATTR, "B")]
    second = [(OBJ, "y"), (OBJ, "x"), (ATTR, "A"), (ATTR, "B")]
    low, high, position = _scan_axis(first, second)
    assert low == {(ATTR, "B"): 0, (ATTR, "A"): 0}
    assert high == {(ATTR, "A"): 2, (ATTR, "B"): 4}
    assert position == {(OBJ, "x"): 1, (OBJ, "y"): 3}


def test_minimal_system() -> None:
    system = make_system({"A": ["x"]})
    assert_faithful(system, layout_2d(system))


def test_nested_chain() -> None:
    system = make_system({"A": ["x"], "B": ["x", "y"], "C": ["x", "y", "z"]})
    layout = layout_2d(system)
    assert_faithful(system, layout)


def test_languages_example_file() -> None:
    system = load_set_system(EXAMPLES_DIR / "languages.yaml")
    assert_faithful(system, layout_2d(system))


def test_europe_example_file() -> None:
    # Figure 2 of the paper: not one-dimensional, but two-dimensional.
    system = load_set_system(EXAMPLES_DIR / "europe.yaml")
    assert_faithful(system, layout_2d(system))


def test_pairwise_overlaps_without_common_element() -> None:
    assert_faithful(contranominal(3), layout_2d(contranominal(3)))


def test_contranominal_of_five_is_not_realizable() -> None:
    # Its Euler-poset contains the standard example S5 of order dimension
    # five, so the extended Euler-poset cannot have a width-four realizer.
    with pytest.raises(NotRealizableError):
        layout_2d(contranominal(5))


def test_empty_set_rejected() -> None:
    with pytest.raises(LayoutError, match="empty"):
        layout_2d(make_system({"A": ["x"], "B": []}))


def test_clarification_duplicates_share_geometry() -> None:
    system = make_system(
        {"A": ["x", "y"], "B": ["x", "y"], "C": ["x", "y", "z", "w"]}
    )
    layout = layout_2d(system)
    assert_faithful(system, layout)
    assert layout.rectangles["A"] == layout.rectangles["B"]
    assert layout.points["z"] == layout.points["w"]


def assert_compact(layout) -> None:
    """No structurally empty rows or columns: on each axis the coordinates
    are contiguous from zero and boundary/element coordinates alternate."""
    axes = [
        (
            {r.x_min for r in layout.rectangles.values()}
            | {r.x_max for r in layout.rectangles.values()},
            {x for x, _ in layout.points.values()},
        ),
        (
            {r.y_min for r in layout.rectangles.values()}
            | {r.y_max for r in layout.rectangles.values()},
            {y for _, y in layout.points.values()},
        ),
    ]
    for boundaries, positions in axes:
        assert not boundaries & positions
        coordinates = sorted(boundaries | positions)
        assert coordinates == list(range(len(coordinates)))
        assert all(coordinate % 2 == 0 for coordinate in boundaries)
        assert all(coordinate % 2 == 1 for coordinate in positions)


@pytest.mark.parametrize(
    "sets",
    [
        {"A": ["x"]},
        {"A": ["x"], "B": ["x", "y"], "C": ["x", "y", "z"]},
        {f"m{i}": [f"g{j}" for j in range(3) if j != i] for i in range(3)},
        {"A": ["x", "y"], "B": ["x", "y"], "C": ["x", "y", "z", "w"]},
    ],
    ids=["minimal", "chain", "contranominal3", "duplicates"],
)
def test_layouts_are_compact(sets: dict[str, list[str]]) -> None:
    system = make_system(sets)
    layout = layout_2d(system)
    assert_faithful(system, layout)
    assert_compact(layout)


@pytest.mark.parametrize("example", ["languages.yaml", "europe.yaml"])
def test_example_layouts_are_compact(example: str) -> None:
    assert_compact(layout_2d(load_set_system(EXAMPLES_DIR / example)))


def test_uninformative_axis_collapses_to_single_column() -> None:
    # All sets of the languages example span the full range on one axis, so
    # that axis must compact to a single shared element coordinate.
    layout = layout_2d(load_set_system(EXAMPLES_DIR / "languages.yaml"))
    spans_x = {(r.x_min, r.x_max) for r in layout.rectangles.values()}
    spans_y = {(r.y_min, r.y_max) for r in layout.rectangles.values()}
    assert spans_x == {(0, 2)} or spans_y == {(0, 2)}


def test_compaction_map_groups_runs() -> None:
    from euler_diagrams.layout import _compaction_map

    mapping = _compaction_map({0, 4, 6, 10}, {1, 3, 7, 9})
    assert mapping == {0: 0, 1: 1, 3: 1, 4: 2, 6: 2, 7: 3, 9: 3, 10: 4}


def test_realizer_of_europe_extended_poset_is_valid() -> None:
    from euler_diagrams.layout import _clarify

    system = load_set_system(EXAMPLES_DIR / "europe.yaml")
    extents, objects, _, _ = _clarify(system)
    poset = extended_euler_poset(extents, objects)
    realizer = find_realizer(poset, 4)
    assert realizer is not None
    assert realizes(poset, realizer)


@pytest.mark.parametrize("example", ["languages.yaml", "europe.yaml"])
def test_optimized_realizer_never_worse_and_valid(example: str) -> None:
    from euler_diagrams.layout import _clarify
    from euler_diagrams.realizer import count_double_breaks

    system = load_set_system(EXAMPLES_DIR / example)
    extents, objects, _, _ = _clarify(system)
    poset = extended_euler_poset(extents, objects)
    pairs = [
        (("obj", g), ("attr", m))
        for m, extent in extents.items()
        for g in objects
        if g not in extent
    ]
    plain = find_realizer(poset, 4)
    optimized = find_realizer(poset, 4, optimize_pairs=pairs)
    assert optimized is not None
    assert realizes(poset, optimized)
    assert count_double_breaks(optimized, pairs) <= count_double_breaks(plain, pairs)
    # Both examples admit realizers with no double-break at all.
    assert count_double_breaks(optimized, pairs) == 0
