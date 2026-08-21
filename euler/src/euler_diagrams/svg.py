"""SVG rendering of rectangular Euler diagram layouts.

Colors follow the validated reference palette of the data-viz method: the
fixed categorical slot order with its documented light and dark steps, so the
palette's validation carries over unchanged. Identity is never color-alone —
every set is labeled directly on its border and every element is a box with
its name centered inside, all text in ink tokens rather than series colors.
Dark mode uses the palette's dark column via ``prefers-color-scheme``, not an
automatic flip.

Set labels sit centered on their rectangle's border: the border is drawn as a
path with a structural gap under the label. A label prefers the top edge
center and slides along the edge or flips to the bottom edge to avoid member
boxes, other borders, and other labels; where a dense layout leaves no clear
spot, a surface-colored pill under the text locally covers foreign lines
(reading as an interruption, not a box), while the owning border's gap is cut
wider than the pill so the ownership stays unambiguous.

Geometry guarantees:

- No two parallel border lines ever coincide or touch: edges sharing a grid
  line with overlapping spans get different per-edge inset steps (a
  contained rectangle's edge always deeper than its container's), and
  opposite-side borders on one line are separated by their minimal insets.
- Pixel positions per axis come from a constraint-graph longest-path pass,
  so every member box keeps ``_MEMBER_CLEARANCE`` to every border while no
  row or column reserves space its content does not need.
"""

from __future__ import annotations

import math
from collections import defaultdict
from itertools import product
from xml.sax.saxutils import escape, quoteattr

from .layout import Layout, Rectangle

__all__ = ["RenderError", "render_svg"]

_PALETTE_LIGHT = [
    "#2a78d6",
    "#eb6834",
    "#1baf7a",
    "#eda100",
    "#e87ba4",
    "#008300",
    "#4a3aa7",
    "#e34948",
]
_PALETTE_DARK = [
    "#3987e5",
    "#d95926",
    "#199e70",
    "#c98500",
    "#d55181",
    "#008300",
    "#9085e9",
    "#e66767",
]

_MARGIN = 28
_TITLE_HEIGHT = 26
_STEP_PX = 5.0  # inset per step; the minimal gap between parallel border lines
_MEMBER_BOX_HEIGHT = 22.0
_MEMBER_STACK_GAP = 4.0  # vertical gap between boxes of co-located elements
_MEMBER_COLUMN_GAP = 8.0  # horizontal gap between columns of a member grid
_MEMBER_CLEARANCE = 6.0  # minimal gap between a member box and a vertical border
# Floor of the vertical clearance; the effective value grows with the tallest
# label pill (half its height + 1) so a label on a rectangle's top border
# never covers the member boxes below it, even when labels are multi-line.
_MEMBER_CLEARANCE_Y = 9.0
_COLUMN_SEARCH_LIMIT = 50_000  # exhaustive column search up to this many combinations
_MIN_RECT_HEIGHT = 24.0
_CHAR_WIDTH = 7.0  # estimated glyph advance of the 12px system sans
_LABEL_HEIGHT = 16.0
_CORNER_RADIUS = 3.0
_LABEL_FRACTIONS = [0.5, 0.4, 0.6, 0.3, 0.7, 0.2, 0.8, 0.12, 0.88]
_HALF_STROKE = 1.0
_LINE_HEIGHT = 14.0  # extra height per additional label line
_LINK_ICON_SIZE = 8.0
_LINK_ICON_SPACE = _LINK_ICON_SIZE + 4.0  # icon plus its gap to the label text

Box = tuple[float, float, float, float]


class RenderError(Exception):
    """Raised when a layout cannot be rendered."""


def render_svg(layout: Layout) -> str:
    """Render ``layout`` as a standalone SVG document string."""
    if len(layout.rectangles) > len(_PALETTE_LIGHT):
        raise RenderError(
            f"cannot render more than {len(_PALETTE_LIGHT)} sets: the categorical "
            "palette has a fixed number of slots and hues are never generated"
        )

    rectangles_px, _, member_groups = _pixel_geometry(layout)
    set_names = sorted(layout.rectangles)
    slot = {name: i for i, name in enumerate(set_names)}
    pill_sizes = {
        name: _pill_size(
            _display_lines(name, layout.set_labels), name in layout.set_links
        )
        for name in set_names
    }
    labels = _set_label_positions(
        rectangles_px, [box for box, _ in member_groups], pill_sizes
    )

    # The viewBox is the exact bounding box of everything drawn — rectangle
    # borders (2px strokes reach 1px past the edge), label pills, member
    # boxes, and the title — so the image has no margin and, with no
    # background rect, a transparent background.
    content = [(x - 1, y - 1, w + 2, h + 2) for x, y, w, h in rectangles_px.values()]
    content += [labels[name][2] for name in set_names]
    content += [box for box, _ in member_groups]
    if layout.name:
        content.append((_MARGIN, _MARGIN - 22.0, 8.0 * len(layout.name) + 4, 20.0))
    min_x = math.floor(min(box[0] for box in content))
    min_y = math.floor(min(box[1] for box in content))
    width = math.ceil(max(box[0] + box[2] for box in content)) - min_x
    height = math.ceil(max(box[1] + box[3] for box in content)) - min_y

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="{min_x} {min_y} {width} {height}" '
        f'width="{width}" height="{height}" role="img">',
        f"  <title>{escape(layout.name or 'Euler diagram')}</title>",
        f"  <style>{_stylesheet()}</style>",
    ]
    if layout.name:
        parts.append(
            f'  <text class="title" x="{_MARGIN}" y="{_MARGIN - 8}">'
            f"{escape(layout.name)}</text>"
        )

    # Larger rectangles first so nested ones stay on top.
    grid_area = {
        name: (r.x_max - r.x_min) * (r.y_max - r.y_min)
        for name, r in layout.rectangles.items()
    }
    by_size = sorted(set_names, key=lambda n: (-grid_area[n], n))
    for name in by_size:
        x, y, w, h = rectangles_px[name]
        parts.append(
            f'  <rect class="set-fill-{slot[name]}" x="{x:g}" y="{y:g}" '
            f'width="{w:g}" height="{h:g}" rx="{_CORNER_RADIUS:g}"/>'
        )
    for name in by_size:
        _, _, _, gap_lo, gap_hi, edge = labels[name]
        parts.append(
            f'  <path class="set-stroke-{slot[name]}" '
            f'd="{_border_path(rectangles_px[name], edge, gap_lo, gap_hi)}"/>'
        )

    for (x, y, w, h), name in member_groups:
        lines = _display_lines(name, layout.element_labels)
        link = layout.element_links.get(name)
        if link is not None:
            parts.append(f"  <a href={quoteattr(link)}>")
        parts.append(
            f'  <rect class="member-box" x="{x:g}" y="{y:g}" '
            f'width="{w:g}" height="{h:g}" rx="4"/>'
        )
        text_x = x + w / 2 - (_LINK_ICON_SPACE / 2 if link is not None else 0)
        parts.append(_label_text(lines, "member-label", text_x, y + h / 2))
        if link is not None:
            parts.append(
                _link_icon_after(lines, text_x, y + h / 2, "member-icon")
            )
            parts.append("  </a>")

    for name in set_names:
        center_x, center_y, pill, _, _, _ = labels[name]
        pill_x, pill_y, pill_w, pill_h = pill
        lines = _display_lines(name, layout.set_labels)
        link = layout.set_links.get(name)
        if link is not None:
            parts.append(f"  <a href={quoteattr(link)}>")
        parts.append(
            f'  <rect class="label-pill" x="{pill_x:g}" y="{pill_y:g}" '
            f'width="{pill_w:g}" height="{pill_h:g}" rx="4"/>'
        )
        text_x = center_x - (_LINK_ICON_SPACE / 2 if link is not None else 0)
        parts.append(
            _label_text(lines, f"set-label set-ink-{slot[name]}", text_x, center_y)
        )
        if link is not None:
            parts.append(
                _link_icon_after(lines, text_x, center_y, f"set-icon-{slot[name]}")
            )
            parts.append("  </a>")
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def _pixel_geometry(
    layout: Layout,
) -> tuple[dict[str, Box], dict[str, Box], list[tuple[Box, str]]]:
    """Map the integer grid to pixel rectangles and member boxes.

    Returns the rectangle per set, the member box per element (elements with
    equal memberships share a grid point and flow there into a small grid of
    individual boxes whose column count minimizes the diagram size), and all
    boxes with their labels.
    Pixel coordinates per axis come from a longest-path pass over a
    constraint graph (VLSI-style one-dimensional compaction): consecutive
    grid coordinates are separated by exactly the space their local content
    needs (border insets, member half-extents, clearances), and long-range
    constraints keep every rectangle wide enough for its border label and
    tall enough for its corners. The result is minimal per axis — no row or
    column reserves space for content it does not carry.
    """
    insets = _edge_insets(layout)

    grouped: dict[tuple[int, int], list[str]] = defaultdict(list)
    for element in sorted(layout.points):
        grouped[layout.points[element]].append(element)

    rectangles = layout.rectangles
    pill_sizes = {
        name: _pill_size(
            _display_lines(name, layout.set_labels), name in layout.set_links
        )
        for name in rectangles
    }
    member_sizes = {
        element: _member_box_size(
            _display_lines(element, layout.element_labels),
            element in layout.element_links,
        )
        for element in layout.points
    }
    x_axis = dict(
        boundaries={r.x_min for r in rectangles.values()}
        | {r.x_max for r in rectangles.values()},
        start_inset=_line_insets(rectangles, insets, "x_min"),
        end_inset=_line_insets(rectangles, insets, "x_max"),
        spans=[
            (
                r.x_min,
                r.x_max,
                pill_sizes[name][0]
                + 6
                + 2 * _CORNER_RADIUS
                + insets[name]["x_min"]
                + insets[name]["x_max"],
            )
            for name, r in rectangles.items()
        ],
    )
    # Top-edge labels reach half their pill below the border; the vertical
    # clearance must exceed that so labels never cover the member boxes.
    label_clearance = max(
        (height / 2 + 1 for _, height in pill_sizes.values()), default=0.0
    )
    y_axis = dict(
        clearance=max(_MEMBER_CLEARANCE_Y, label_clearance),
        boundaries={r.y_min for r in rectangles.values()}
        | {r.y_max for r in rectangles.values()},
        start_inset=_line_insets(rectangles, insets, "y_min"),
        end_inset=_line_insets(rectangles, insets, "y_max"),
        spans=[
            (
                r.y_min,
                r.y_max,
                _MIN_RECT_HEIGHT + insets[name]["y_min"] + insets[name]["y_max"],
            )
            for name, r in rectangles.items()
        ],
    )
    columns = _choose_columns(grouped, x_axis, y_axis, member_sizes)
    grids = {
        point: _member_grid(elements, columns[point], member_sizes)
        for point, elements in grouped.items()
    }
    pos_x = _axis_positions(half=_grid_halves(grids, 0), **x_axis)
    pos_y = _axis_positions(half=_grid_halves(grids, 1), **y_axis)

    top = _MARGIN + (_TITLE_HEIGHT if layout.name else 0)
    rectangles_px = {}
    for name, rectangle in rectangles.items():
        x = _MARGIN + pos_x[rectangle.x_min] + insets[name]["x_min"]
        y = top + pos_y[rectangle.y_min] + insets[name]["y_min"]
        rectangles_px[name] = (
            x,
            y,
            _MARGIN + pos_x[rectangle.x_max] - insets[name]["x_max"] - x,
            top + pos_y[rectangle.y_max] - insets[name]["y_max"] - y,
        )

    member_groups = []
    member_boxes: dict[str, Box] = {}
    for point in sorted(grouped):
        x, y = point
        offsets, _, _ = grids[point]
        for element in grouped[point]:
            dx, dy, w, h = offsets[element]
            box = (_MARGIN + pos_x[x] + dx, top + pos_y[y] + dy, w, h)
            member_groups.append((box, element))
            member_boxes[element] = box
    return rectangles_px, member_boxes, member_groups


def _link_icon(x: float, y: float, ink_class: str) -> str:
    """A tiny external-link arrow with its top-left corner at ``(x, y)``."""
    return (
        f'  <path class="link-icon {ink_class}" '
        f'transform="translate({x:g} {y:g})" d="M1 7 L7 1 M3 1 H7 V5"/>'
    )


def _label_text(
    lines: list[str], css_class: str, center_x: float, center_y: float
) -> str:
    """A ``<text>`` centered at the given point; multi-line via tspans."""
    if len(lines) == 1:
        return (
            f'  <text class="{css_class}" x="{center_x:g}" y="{center_y + 4:g}">'
            f"{escape(lines[0])}</text>"
        )
    first_baseline = center_y + 4 - (len(lines) - 1) * _LINE_HEIGHT / 2
    tspans = "".join(
        f'<tspan x="{center_x:g}" y="{first_baseline + i * _LINE_HEIGHT:g}">'
        f"{escape(line)}</tspan>"
        for i, line in enumerate(lines)
    )
    return f'  <text class="{css_class}">{tspans}</text>'


def _link_icon_after(
    lines: list[str], center_x: float, center_y: float, ink_class: str
) -> str:
    """The link icon placed after the last line of a centered label."""
    last_line_center_y = center_y + (len(lines) - 1) * _LINE_HEIGHT / 2
    return _link_icon(
        center_x + _CHAR_WIDTH * len(lines[-1]) / 2 + 4,
        last_line_center_y - _LINK_ICON_SIZE / 2,
        ink_class,
    )


def _display_lines(name: str, display_labels: dict[str, str]) -> list[str]:
    """The lines of a set's or element's display label (default: its name)."""
    return display_labels.get(name, name).split("\n")


def _member_box_size(lines: list[str], linked: bool = False) -> tuple[float, float]:
    """Pixel size of one member box for a display label of ``lines``."""
    width = max(24.0, _CHAR_WIDTH * max(len(line) for line in lines) + 18.0) + (
        _LINK_ICON_SPACE if linked else 0.0
    )
    return width, _MEMBER_BOX_HEIGHT + (len(lines) - 1) * _LINE_HEIGHT


def _member_grid(
    elements: list[str], columns: int, sizes: dict[str, tuple[float, float]]
) -> tuple[dict[str, Box], float, float]:
    """Pack a group of co-located elements into a row-major grid.

    Returns per-element boxes ``(dx, dy, w, h)`` relative to the group
    center, plus the grid's total width and height. Each column is as wide
    as its widest box; boxes are centered within their column.
    ``columns=1`` is the plain vertical stack.
    """
    columns = min(columns, len(elements))
    rows = math.ceil(len(elements) / columns)
    widths = [sizes[element][0] for element in elements]
    heights = [sizes[element][1] for element in elements]
    column_width = [
        max(widths[i] for i in range(c, len(elements), columns))
        for c in range(columns)
    ]
    row_height = [
        max(heights[i] for i in range(r * columns, min((r + 1) * columns, len(elements))))
        for r in range(rows)
    ]
    total_width = sum(column_width) + (columns - 1) * _MEMBER_COLUMN_GAP
    total_height = sum(row_height) + (rows - 1) * _MEMBER_STACK_GAP

    offsets: dict[str, Box] = {}
    for i, element in enumerate(elements):
        row, column = divmod(i, columns)
        column_left = (
            -total_width / 2
            + sum(column_width[:column])
            + column * _MEMBER_COLUMN_GAP
        )
        row_top = (
            -total_height / 2 + sum(row_height[:row]) + row * _MEMBER_STACK_GAP
        )
        offsets[element] = (
            column_left + (column_width[column] - widths[i]) / 2,
            row_top + (row_height[row] - heights[i]) / 2,
            widths[i],
            heights[i],
        )
    return offsets, total_width, total_height


def _grid_halves(
    grids: dict[tuple[int, int], tuple[dict[str, Box], float, float]], axis: int
) -> dict[int, float]:
    """Half-extent per grid coordinate on one axis from the member grids."""
    halves: dict[int, float] = defaultdict(float)
    for point, (_, width, height) in grids.items():
        extent = width if axis == 0 else height
        halves[point[axis]] = max(halves[point[axis]], extent / 2)
    return dict(halves)


def _choose_columns(
    grouped: dict[tuple[int, int], list[str]],
    x_axis: dict,
    y_axis: dict,
    sizes: dict[str, tuple[float, float]],
) -> dict[tuple[int, int], int]:
    """Choose a column count per member group minimizing the diagram size.

    A candidate assignment is scored by running the axis compaction with the
    resulting group extents and taking the rendered area (ties: smaller
    half-perimeter, then fewer columns overall). All assignments are
    enumerated when the search space is at most ``_COLUMN_SEARCH_LIMIT``;
    larger spaces are hill-climbed from near-square grids, adjusting one
    group by one column at a time.
    """
    points = sorted(grouped)
    extent_cache: dict[tuple[tuple[int, int], int], tuple[float, float]] = {}

    def extents(point: tuple[int, int], columns: int) -> tuple[float, float]:
        key = (point, columns)
        if key not in extent_cache:
            extent_cache[key] = _member_grid(grouped[point], columns, sizes)[1:]
        return extent_cache[key]

    def score(assignment: dict[tuple[int, int], int]) -> tuple[float, float, int]:
        half_x: dict[int, float] = defaultdict(float)
        half_y: dict[int, float] = defaultdict(float)
        for point in points:
            width, height = extents(point, assignment[point])
            half_x[point[0]] = max(half_x[point[0]], width / 2)
            half_y[point[1]] = max(half_y[point[1]], height / 2)
        size_x = max(_axis_positions(half=dict(half_x), **x_axis).values())
        size_y = max(_axis_positions(half=dict(half_y), **y_axis).values())
        return (size_x * size_y, size_x + size_y, sum(assignment.values()))

    combinations = math.prod(len(grouped[point]) for point in points)
    if combinations <= _COLUMN_SEARCH_LIMIT:
        best: dict[tuple[int, int], int] | None = None
        best_score = None
        for choice in product(*(range(1, len(grouped[point]) + 1) for point in points)):
            assignment = dict(zip(points, choice))
            candidate_score = score(assignment)
            if best_score is None or candidate_score < best_score:
                best, best_score = assignment, candidate_score
        assert best is not None
        return best

    assignment = {
        point: math.ceil(math.sqrt(len(grouped[point]))) for point in points
    }
    current = score(assignment)
    while True:
        improved = False
        for point in points:
            for candidate_columns in (assignment[point] - 1, assignment[point] + 1):
                if not 1 <= candidate_columns <= len(grouped[point]):
                    continue
                candidate = {**assignment, point: candidate_columns}
                candidate_score = score(candidate)
                if candidate_score < current:
                    assignment, current = candidate, candidate_score
                    improved = True
        if not improved:
            return assignment


def _axis_positions(
    boundaries: set[int],
    start_inset: dict[int, float],
    end_inset: dict[int, float],
    half: dict[int, float],
    spans: list[tuple[int, int, float]],
    clearance: float = _MEMBER_CLEARANCE,
) -> dict[int, float]:
    """Longest-path positions for one axis of the compacted grid.

    Grid coordinates alternate boundary/element (a compaction invariant), so
    chain constraints are always between a boundary line — whose borders
    reach inward by up to ``start_inset``/``end_inset`` — and an adjacent
    element with half-extent ``half``, ``clearance`` apart. ``spans`` adds
    ``(from, to, min_pixels)`` constraints (label width, minimum height).
    Coordinates are already topologically ordered, so one forward pass is
    exact.
    """
    coordinates = sorted(boundaries | set(half))
    span_floor: dict[int, list[tuple[int, float]]] = defaultdict(list)
    for start, end, min_pixels in spans:
        span_floor[end].append((start, min_pixels))

    positions: dict[int, float] = {}
    previous: int | None = None
    for coordinate in coordinates:
        if previous is None:
            position = 0.0
        elif coordinate in boundaries:
            position = (
                positions[previous]
                + half.get(previous, 0.0)
                + clearance
                + end_inset.get(coordinate, 0.0)
                + _HALF_STROKE
            )
        else:
            position = (
                positions[previous]
                + start_inset.get(previous, 0.0)
                + _HALF_STROKE
                + clearance
                + half.get(coordinate, 0.0)
            )
        for start, min_pixels in span_floor.get(coordinate, ()):
            position = max(position, positions[start] + min_pixels)
        positions[coordinate] = position
        previous = coordinate
    return positions


def _line_insets(
    rectangles: dict[str, Rectangle],
    insets: dict[str, dict[str, float]],
    edge: str,
) -> dict[int, float]:
    """Largest inward inset per grid line among the ``edge`` borders on it."""
    result: dict[int, float] = defaultdict(float)
    for name, rectangle in rectangles.items():
        line = getattr(rectangle, edge)
        result[line] = max(result[line], insets[name][edge])
    return dict(result)


def _edge_insets(layout: Layout) -> dict[str, dict[str, float]]:
    """Assign each rectangle edge an inward inset separating parallel borders.

    Each edge is handled on its own grid line: edges there whose
    perpendicular spans overlap would render on top of each other, so they
    get distinct inset steps; an edge of a contained (or identical, ordered
    by name) rectangle always sits deeper than its container's edge on the
    same line. Edges alone on their line get the minimal one-step inset —
    unlike a per-rectangle inset, a deep conflict stack on one side of a
    rectangle does not inflate its other edges.
    """
    rectangle_of = layout.rectangles

    def contains_or_equal(outer: Rectangle, inner: Rectangle) -> bool:
        return (
            outer.x_min <= inner.x_min
            and inner.x_max <= outer.x_max
            and outer.y_min <= inner.y_min
            and inner.y_max <= outer.y_max
        )

    def grid_area(r: Rectangle) -> int:
        return (r.x_max - r.x_min) * (r.y_max - r.y_min)

    edge_span = {
        "x_min": lambda r: (r.y_min, r.y_max),
        "x_max": lambda r: (r.y_min, r.y_max),
        "y_min": lambda r: (r.x_min, r.x_max),
        "y_max": lambda r: (r.x_min, r.x_max),
    }
    groups: dict[tuple[str, int], list[tuple[str, tuple[int, int], int]]] = defaultdict(list)
    insets: dict[str, dict[str, float]] = {}
    for name in sorted(rectangle_of, key=lambda n: (-grid_area(rectangle_of[n]), n)):
        rectangle = rectangle_of[name]
        insets[name] = {}
        for edge, span_of in edge_span.items():
            span = span_of(rectangle)
            group = groups[(edge, getattr(rectangle, edge))]
            floor = max(
                (
                    step + 1
                    for other, _, step in group
                    if contains_or_equal(rectangle_of[other], rectangle)
                ),
                default=0,
            )
            used = {
                step
                for _, other_span, step in group
                if max(span[0], other_span[0]) <= min(span[1], other_span[1])
            }
            step = floor
            while step in used:
                step += 1
            group.append((name, span, step))
            insets[name][edge] = (step + 1) * _STEP_PX
    return insets


def _pill_size(lines: list[str], linked: bool = False) -> tuple[float, float]:
    """Pixel size of the pill behind a set label of ``lines``."""
    width = (
        _CHAR_WIDTH * max(len(line) for line in lines)
        + 12.0
        + (_LINK_ICON_SPACE if linked else 0.0)
    )
    return width, _LABEL_HEIGHT + (len(lines) - 1) * _LINE_HEIGHT


def _set_label_positions(
    rectangles_px: dict[str, Box],
    member_boxes: list[Box],
    pill_sizes: dict[str, tuple[float, float]] | None = None,
) -> dict[str, tuple[float, float, Box, float, float, str]]:
    """Place each set label centered on its rectangle's border.

    Returns per set: label center, its pill box, the border gap interval and
    the edge ("top" or "bottom") carrying it. Labels sit on the top edge,
    sliding along it to dodge collisions; crossing a foreign border line is
    only a soft penalty (the pill visually interrupts it), so a label falls
    to the bottom edge only when every top position would cover a member box
    or another label — and even then only if the bottom is strictly better.
    """
    if pill_sizes is None:
        pill_sizes = {name: _pill_size([name]) for name in rectangles_px}
    edge_segments = {
        name: _edges(rectangle) for name, rectangle in rectangles_px.items()
    }
    placements: dict[str, tuple[float, float, Box, float, float, str]] = {}
    label_obstacles: list[Box] = []
    order = sorted(
        rectangles_px, key=lambda n: (rectangles_px[n][1], rectangles_px[n][0], n)
    )
    for name in order:
        x, y, w, h = rectangles_px[name]
        pill_width, pill_height = pill_sizes[name]
        gap_half = pill_width / 2 + 3
        foreign_segments = [
            segment
            for other, segments in edge_segments.items()
            if other != name
            for segment in segments
        ]

        def penalty(box: Box) -> tuple[int, int]:
            """(hard, soft): hard conflicts cover boxes or labels, soft ones
            merely cross foreign border lines (interrupted by the pill)."""
            hard = 5 * sum(_overlaps(box, other) for other in member_boxes)
            hard += 3 * sum(_overlaps(box, other) for other in label_obstacles)
            soft = sum(_overlaps(box, other) for other in foreign_segments)
            return hard, soft

        edge_bests: list[tuple[tuple[int, int], float, float, str]] = []
        for edge_y, edge in ((y, "top"), (y + h, "bottom")):
            low = x + _CORNER_RADIUS + gap_half
            high = x + w - _CORNER_RADIUS - gap_half
            candidates = (
                [low + fraction * (high - low) for fraction in _LABEL_FRACTIONS]
                if low <= high
                else [x + w / 2]
            )
            edge_best: tuple[tuple[int, int], float, float, str] | None = None
            for center_x in candidates:
                box = (
                    center_x - pill_width / 2,
                    edge_y - pill_height / 2,
                    pill_width,
                    pill_height,
                )
                score = penalty(box)
                if edge_best is None or score < edge_best[0]:
                    edge_best = (score, center_x, edge_y, edge)
                if score == (0, 0):
                    break
            assert edge_best is not None
            edge_bests.append(edge_best)
            if edge == "top" and edge_best[0][0] == 0:
                break  # top edge is conflict-free (borders aside): take it

        # min() is stable, so on equal scores the top edge (listed first) wins.
        _, center_x, center_y, edge = min(edge_bests, key=lambda best: best[0])
        gap_lo = max(x + _CORNER_RADIUS, center_x - gap_half)
        gap_hi = min(x + w - _CORNER_RADIUS, center_x + gap_half)
        pill = (
            center_x - pill_width / 2,
            center_y - pill_height / 2,
            pill_width,
            pill_height,
        )
        label_obstacles.append(pill)
        placements[name] = (center_x, center_y, pill, gap_lo, gap_hi, edge)
    return placements


def _border_path(rectangle_px: Box, edge: str, gap_lo: float, gap_hi: float) -> str:
    """The rounded-rectangle border as a path, interrupted on ``edge``."""
    x, y, w, h = rectangle_px
    r = _CORNER_RADIUS
    if edge == "top":
        return (
            f"M {gap_hi:g} {y:g} H {x + w - r:g} "
            f"A {r:g} {r:g} 0 0 1 {x + w:g} {y + r:g} V {y + h - r:g} "
            f"A {r:g} {r:g} 0 0 1 {x + w - r:g} {y + h:g} H {x + r:g} "
            f"A {r:g} {r:g} 0 0 1 {x:g} {y + h - r:g} V {y + r:g} "
            f"A {r:g} {r:g} 0 0 1 {x + r:g} {y:g} H {gap_lo:g}"
        )
    return (
        f"M {gap_lo:g} {y + h:g} H {x + r:g} "
        f"A {r:g} {r:g} 0 0 1 {x:g} {y + h - r:g} V {y + r:g} "
        f"A {r:g} {r:g} 0 0 1 {x + r:g} {y:g} H {x + w - r:g} "
        f"A {r:g} {r:g} 0 0 1 {x + w:g} {y + r:g} V {y + h - r:g} "
        f"A {r:g} {r:g} 0 0 1 {x + w - r:g} {y + h:g} H {gap_hi:g}"
    )


def _edges(rectangle_px: Box) -> list[Box]:
    """The four border lines of a rectangle as thin obstacle boxes."""
    x, y, w, h = rectangle_px
    return [
        (x - 1, y - 1, w + 2, 2),
        (x - 1, y + h - 1, w + 2, 2),
        (x - 1, y - 1, 2, h + 2),
        (x + w - 1, y - 1, 2, h + 2),
    ]


def _overlaps(a: Box, b: Box) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def _stylesheet() -> str:
    light = "\n".join(
        f"    .set-fill-{i} {{ fill: {hex}; fill-opacity: .13; }}\n"
        f"    .set-stroke-{i} {{ fill: none; stroke: {hex}; stroke-width: 2; }}\n"
        f"    .set-ink-{i} {{ fill: {hex}; }}\n"
        f"    .set-icon-{i} {{ stroke: {hex}; }}"
        for i, hex in enumerate(_PALETTE_LIGHT)
    )
    dark = "\n".join(
        f"      .set-fill-{i} {{ fill: {hex}; fill-opacity: .2; }}\n"
        f"      .set-stroke-{i} {{ stroke: {hex}; }}\n"
        f"      .set-ink-{i} {{ fill: {hex}; }}\n"
        f"      .set-icon-{i} {{ stroke: {hex}; }}"
        for i, hex in enumerate(_PALETTE_DARK)
    )
    return f"""
    svg {{ font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }}
    .title {{ fill: #0b0b0b; font-size: 14px; font-weight: 600; }}
    .set-label {{ font-size: 12px; font-weight: 600; text-anchor: middle; }}
    .member-label {{ fill: #0b0b0b; font-size: 12px; text-anchor: middle; }}
    .member-box {{ fill: #fcfcfb; stroke: #c3c2b7; stroke-width: 1; }}
    .label-pill {{ fill: #fcfcfb; }}
    a:hover .set-label {{ text-decoration: underline; }}
    a:hover .member-box {{ stroke: #898781; }}
    .link-icon {{ fill: none; stroke-width: 1.2; stroke-linecap: round; stroke-linejoin: round; }}
    .member-icon {{ stroke: #52514e; }}
{light}
    @media (prefers-color-scheme: dark) {{
      .title, .member-label {{ fill: #ffffff; }}
      .member-box {{ fill: #1a1a19; stroke: #383835; }}
      .label-pill {{ fill: #1a1a19; }}
      .member-icon {{ stroke: #c3c2b7; }}
{dark}
    }}
  """
