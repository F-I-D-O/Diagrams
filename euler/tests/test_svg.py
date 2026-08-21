"""Tests for the SVG renderer."""

import xml.etree.ElementTree as ElementTree
from pathlib import Path

import pytest

from euler_diagrams import RenderError, SetSystem, layout_2d, load_set_system, render_svg
from euler_diagrams.svg import _pixel_geometry

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


def make_system(sets: dict[str, list[str]], name: str | None = None) -> SetSystem:
    return SetSystem(
        sets={set_name: frozenset(members) for set_name, members in sets.items()},
        name=name,
    )


def systems_under_test() -> list[SetSystem]:
    return [
        load_set_system(EXAMPLES_DIR / "languages.yaml"),
        load_set_system(EXAMPLES_DIR / "europe.yaml"),
        load_set_system(EXAMPLES_DIR / "Transportation.yaml"),
        # pairwise overlaps without a common element
        make_system({f"m{i}": [f"g{j}" for j in range(3) if j != i] for i in range(3)}),
        # duplicate sets and duplicate memberships
        make_system({"A": ["x", "y"], "B": ["x", "y"], "C": ["x", "y", "z", "w"]}),
    ]


def test_svg_is_well_formed_and_fully_labeled() -> None:
    system = load_set_system(EXAMPLES_DIR / "europe.yaml")
    svg = render_svg(layout_2d(system))
    root = ElementTree.fromstring(svg)
    assert root.tag == "{http://www.w3.org/2000/svg}svg"
    text = " ".join(node.text or "" for node in root.iter())
    for set_name in system.sets:
        assert set_name in text
    for element in system.elements:
        assert element in text
    assert "europe" in text


def test_dark_mode_styles_present() -> None:
    svg = render_svg(layout_2d(load_set_system(EXAMPLES_DIR / "languages.yaml")))
    assert "prefers-color-scheme: dark" in svg


@pytest.mark.parametrize("system", systems_under_test(), ids=lambda s: s.name or "anon")
def test_member_boxes_preserve_membership_with_clearance(system: SetSystem) -> None:
    layout = layout_2d(system)
    rectangles_px, member_boxes, _ = _pixel_geometry(layout)
    clearance = 4
    for set_name, members in system.sets.items():
        rx, ry, rw, rh = rectangles_px[set_name]
        for element in system.elements:
            bx, by, bw, bh = member_boxes[element]
            inside = (
                rx + clearance < bx
                and ry + clearance < by
                and bx + bw < rx + rw - clearance
                and by + bh < ry + rh - clearance
            )
            disjoint = (
                bx + bw + clearance < rx
                or rx + rw + clearance < bx
                or by + bh + clearance < ry
                or ry + rh + clearance < by
            )
            if element in members:
                assert inside, f"member box of {element} not inside {set_name}"
            else:
                assert disjoint, f"member box of {element} touches {set_name}"


@pytest.mark.parametrize("system", systems_under_test(), ids=lambda s: s.name or "anon")
def test_parallel_border_lines_never_coincide(system: SetSystem) -> None:
    layout = layout_2d(system)
    rectangles_px, _, _ = _pixel_geometry(layout)
    vertical = []
    horizontal = []
    for name, (x, y, w, h) in rectangles_px.items():
        vertical += [(name, x, y, y + h), (name, x + w, y, y + h)]
        horizontal += [(name, y, x, x + w), (name, y + h, x, x + w)]
    for lines in (vertical, horizontal):
        for i, (name_a, pos_a, low_a, high_a) in enumerate(lines):
            for name_b, pos_b, low_b, high_b in lines[i + 1 :]:
                if name_a == name_b:
                    continue
                spans_meet = max(low_a, low_b) <= min(high_a, high_b)
                if spans_meet:
                    assert abs(pos_a - pos_b) >= 3, (
                        f"borders of {name_a} and {name_b} (nearly) coincide"
                    )


def test_colocated_elements_get_separate_boxes() -> None:
    # z and w share their memberships, so they share a grid point — but each
    # must get its own box, disjoint from the other's.
    from euler_diagrams.svg import _overlaps

    system = make_system({"A": ["x", "y"], "C": ["x", "y", "z", "w"]})
    layout = layout_2d(system)
    _, member_boxes, member_groups = _pixel_geometry(layout)
    assert layout.points["z"] == layout.points["w"]
    assert len(member_groups) == len(system.elements)
    assert member_boxes["z"] != member_boxes["w"]
    assert not _overlaps(member_boxes["z"], member_boxes["w"])


def test_large_group_flows_into_multiple_columns() -> None:
    from euler_diagrams.svg import _overlaps

    system = make_system(
        {"A": ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot"]}
    )
    _, member_boxes, _ = _pixel_geometry(layout_2d(system))
    boxes = list(member_boxes.values())
    for i, a in enumerate(boxes):
        for b in boxes[i + 1 :]:
            assert not _overlaps(a, b)
    assert len({box[0] for box in boxes}) > 1, "expected more than one column"
    assert len({box[1] for box in boxes}) > 1, "expected more than one row"


def test_member_grid_two_columns_hand_checked() -> None:
    from euler_diagrams.svg import _member_box_size, _member_grid

    elements = ["aa", "bb", "cc", "dd", "ee"]
    sizes = {element: _member_box_size([element]) for element in elements}
    offsets, width, height = _member_grid(elements, 2, sizes)
    box_width = sizes["aa"][0]
    assert width == 2 * box_width + 8
    assert height == 3 * 22 + 2 * 4
    assert offsets["aa"] == (-width / 2, -height / 2, box_width, 22.0)
    assert offsets["bb"] == (-width / 2 + box_width + 8, -height / 2, box_width, 22.0)
    assert offsets["ee"][0] == -width / 2  # row-major wrap to first column
    assert offsets["ee"][1] == -height / 2 + 2 * 26

    stacked, stack_width, stack_height = _member_grid(elements, 1, sizes)
    assert stack_width == box_width
    assert stack_height == 5 * 22 + 4 * 4
    assert all(dx == -box_width / 2 for dx, _, _, _ in stacked.values())


def test_member_grid_multiline_rows_grow() -> None:
    from euler_diagrams.svg import _member_box_size, _member_grid

    sizes = {
        "one": _member_box_size(["one"]),
        "two\nlines": _member_box_size(["two", "lines"]),
    }
    assert sizes["two\nlines"][1] == 22 + 14
    offsets, _, height = _member_grid(["one", "two\nlines"], 2, sizes)
    assert height == 36  # single row as tall as its tallest box
    # the single-line box is vertically centered within the taller row
    assert offsets["one"][1] == -height / 2 + (36 - 22) / 2
    assert offsets["two\nlines"][1] == -height / 2


def test_transportation_is_compact() -> None:
    # Regression bound: single-column stacking rendered this example 400x687.
    svg = render_svg(layout_2d(load_set_system(EXAMPLES_DIR / "Transportation.yaml")))
    import re

    width, height = map(int, re.search(r'width="(\d+)" height="(\d+)"', svg).groups())
    assert height < 550
    assert width * height < 0.8 * 400 * 687


def test_coincident_boundaries_are_separated() -> None:
    # A and B are identical sets: identical grid rectangles must render as
    # distinct concentric pixel rectangles.
    layout = layout_2d(make_system({"A": ["x", "y"], "B": ["x", "y"]}))
    rectangles_px, _, _ = _pixel_geometry(layout)
    assert rectangles_px["A"] != rectangles_px["B"]


@pytest.mark.parametrize("system", systems_under_test(), ids=lambda s: s.name or "anon")
def test_set_labels_sit_on_their_border(system: SetSystem) -> None:
    from euler_diagrams.svg import _pixel_geometry, _set_label_positions

    layout = layout_2d(system)
    rectangles_px, _, member_groups = _pixel_geometry(layout)
    labels = _set_label_positions(rectangles_px, [box for box, _ in member_groups])
    assert set(labels) == set(layout.rectangles)
    for name, (center_x, center_y, _, gap_lo, gap_hi, edge) in labels.items():
        x, y, w, h = rectangles_px[name]
        expected_y = y if edge == "top" else y + h
        assert center_y == pytest.approx(expected_y)
        assert x <= gap_lo < center_x < gap_hi <= x + w


# The duplicates system is excluded: its concentric same-line borders leave
# genuinely no top position free of other labels, the designed fallback case.
@pytest.mark.parametrize(
    "example", ["languages.yaml", "europe.yaml", "Transportation.yaml"]
)
def test_set_labels_prefer_the_top_edge(example: str) -> None:
    from euler_diagrams.svg import _pixel_geometry, _set_label_positions

    layout = layout_2d(load_set_system(EXAMPLES_DIR / example))
    rectangles_px, _, member_groups = _pixel_geometry(layout)
    labels = _set_label_positions(rectangles_px, [box for box, _ in member_groups])
    for name, (_, _, _, _, _, edge) in labels.items():
        assert edge == "top", f"label of {name!r} fell to the bottom edge"


def test_borders_are_paths_with_a_gap() -> None:
    system = load_set_system(EXAMPLES_DIR / "europe.yaml")
    svg = render_svg(layout_2d(system))
    assert svg.count('<path class="set-stroke-') == len(system.sets)
    assert svg.count('<rect class="label-pill"') == len(system.sets)


def test_axis_positions_chain_is_tight() -> None:
    # boundary 0, element 1, boundary 2: hand-computed longest-path values.
    from euler_diagrams.svg import _axis_positions

    positions = _axis_positions(
        boundaries={0, 2},
        start_inset={0: 5.0},
        end_inset={2: 10.0},
        half={1: 20.0},
        spans=[],
    )
    assert positions == {0: 0.0, 1: 5.0 + 1 + 6 + 20, 2: 32.0 + 20 + 6 + 10 + 1}


def test_axis_positions_span_constraint_binds() -> None:
    from euler_diagrams.svg import _axis_positions

    tight = _axis_positions(
        boundaries={0, 2}, start_inset={}, end_inset={}, half={1: 10.0}, spans=[]
    )
    widened = _axis_positions(
        boundaries={0, 2},
        start_inset={},
        end_inset={},
        half={1: 10.0},
        spans=[(0, 2, 500.0)],
    )
    assert widened[2] == 500.0 > tight[2]
    assert widened[1] == tight[1]  # element still packed against the left line


def test_europe_svg_is_compact() -> None:
    # Regression bound: the uniform-unit renderer produced 530 x 502.
    svg = render_svg(layout_2d(load_set_system(EXAMPLES_DIR / "europe.yaml")))
    import re

    width, height = map(int, re.search(r'width="(\d+)" height="(\d+)"', svg).groups())
    assert width < 480
    assert height < 480


def test_links_render_as_svg_anchors() -> None:
    from euler_diagrams import parse_set_system

    system = parse_set_system(
        """
sets:
  A: [x, y]
  B: [y]
links:
  A: https://example.org/a?q=1&r="2"
  x: https://example.org/x
"""
    )
    svg = render_svg(layout_2d(system))
    root = ElementTree.fromstring(svg)  # anchors must keep the SVG well-formed
    ns = "{http://www.w3.org/2000/svg}"
    anchors = root.findall(f"{ns}a")
    assert len(anchors) == 2
    by_href = {a.get("href"): a for a in anchors}
    assert set(by_href) == {'https://example.org/a?q=1&r="2"', "https://example.org/x"}

    element_anchor = by_href["https://example.org/x"]
    tags = [child.tag for child in element_anchor]
    assert tags == [f"{ns}rect", f"{ns}text", f"{ns}path"]
    assert element_anchor.find(f"{ns}rect").get("class") == "member-box"
    assert element_anchor.find(f"{ns}text").text == "x"
    assert "link-icon" in element_anchor.find(f"{ns}path").get("class")

    set_anchor = by_href['https://example.org/a?q=1&r="2"']
    assert set_anchor.find(f"{ns}rect").get("class") == "label-pill"
    assert set_anchor.find(f"{ns}text").text == "A"
    assert "link-icon" in set_anchor.find(f"{ns}path").get("class")
    # exactly one icon per linked entity, none elsewhere
    assert svg.count('class="link-icon') == 2


def test_unlinked_systems_render_without_anchors() -> None:
    svg = render_svg(layout_2d(load_set_system(EXAMPLES_DIR / "europe.yaml")))
    assert "<a " not in svg


def test_multiline_labels_render_as_tspans() -> None:
    from euler_diagrams import parse_set_system

    system = parse_set_system(
        """
sets:
  A: [long element name, y]
labels:
  A: "Set\\nA"
  long element name: "long element\\nname"
"""
    )
    layout = layout_2d(system)
    svg = render_svg(layout)
    root = ElementTree.fromstring(svg)
    ns = "{http://www.w3.org/2000/svg}"
    texts = {
        tuple(tspan.text for tspan in text): text
        for text in root.iter(f"{ns}text")
        if len(text) > 0
    }
    assert ("Set", "A") in texts
    assert ("long element", "name") in texts
    # tspans of one label share x (centered) and step by the line height
    tspans = list(texts[("long element", "name")])
    assert tspans[0].get("x") == tspans[1].get("x")
    assert float(tspans[1].get("y")) - float(tspans[0].get("y")) == 14.0

    # the two-line member box is taller than the single-line one
    _, member_boxes, _ = _pixel_geometry(layout)
    assert member_boxes["long element name"][3] == 36.0
    assert member_boxes["y"][3] == 22.0
    # and narrower than an unbroken label would be
    assert member_boxes["long element name"][2] < 7 * len("long element name") + 18


def test_background_transparent_and_viewbox_tight() -> None:
    # Transportation has no title, so the viewBox must hug the drawn
    # geometry: within rounding plus the 1px border-stroke halo of the
    # rectangle fills on every side.
    svg = render_svg(layout_2d(load_set_system(EXAMPLES_DIR / "Transportation.yaml")))
    assert "surface" not in svg
    root = ElementTree.fromstring(svg)
    view_x, view_y, view_w, view_h = (float(v) for v in root.get("viewBox").split())
    ns = "{http://www.w3.org/2000/svg}"
    rects = list(root.iter(f"{ns}rect"))
    assert rects
    lefts = [float(r.get("x")) for r in rects]
    tops = [float(r.get("y")) for r in rects]
    rights = [float(r.get("x")) + float(r.get("width")) for r in rects]
    bottoms = [float(r.get("y")) + float(r.get("height")) for r in rects]
    assert view_x <= min(lefts) <= view_x + 2
    assert view_y <= min(tops) <= view_y + 2
    assert view_x + view_w - 2 <= max(rights) <= view_x + view_w
    assert view_y + view_h - 2 <= max(bottoms) <= view_y + view_h
    assert float(root.get("width")) == view_w
    assert float(root.get("height")) == view_h


def test_more_than_eight_sets_rejected() -> None:
    elements = [f"e{i}" for i in range(9)]
    nested = {f"s{i}": elements[: i + 1] for i in range(9)}
    with pytest.raises(RenderError, match="palette"):
        render_svg(layout_2d(make_system(nested)))
