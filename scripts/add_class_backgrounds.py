#!/usr/bin/env python3
"""Add convex-hull background regions to a D2 SVG for diagram group classes.

D2 encodes each node as a top-level <g> whose class attribute lists the node id
(base64) plus D2 classes (e.g. "decision sets"). This script finds nodes for
selected classes, computes a padded convex hull of their shape bounds, and
inserts semi-transparent polygons with centered area headers behind the diagram content.

Typical usage (after compiling .d2 to .svg):

    d2 "Collection Decision Tree.d2" "Collection Decision Tree.svg"
    python scripts/add_class_backgrounds.py
"""

from __future__ import annotations

import math
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

# --- Configuration (edit here) ---

REPO_ROOT = Path(__file__).resolve().parent.parent
SVG_PATH = REPO_ROOT / "Collection Decision Tree.svg"
OUTPUT_PATH: Path | None = None  # None = overwrite SVG_PATH

PADDING = 24.0
FONT_SIZE = 400


@dataclass(frozen=True)
class AreaHeader:
    """Label drawn at the centroid of each background hull."""

    text: str
    fill: str = "#1A2744"
    font_size: int = 22
    font_weight: str = "bold"
    font_family: str = "Source Sans Pro, sans-serif"
    offset_x: float = 0.0
    offset_y: float = 0.0


@dataclass(frozen=True)
class BackgroundArea:
    """One labeled background region tied to D2 node class(es)."""

    id: str
    classes: frozenset[str]
    header: AreaHeader
    fill: str
    stroke: str
    fill_opacity: float = 0.42
    stroke_opacity: float = 0.55
    stroke_width: float = 2.0


BACKGROUND_AREAS: tuple[BackgroundArea, ...] = (
    BackgroundArea(
        id="sets",
        classes=frozenset({"sets"}),
        header=AreaHeader(text="Sets", fill="#bad1e3", font_size=800),
        fill="#DCEEF9",
        stroke="#5A9BC4",
    ),
    BackgroundArea(
        id="maps",
        classes=frozenset({"maps"}),
        header=AreaHeader(text="Maps", fill="#4A3270", font_size=300),
        fill="#EDE0FA",
        stroke="#8B6BB8",
    ),
    BackgroundArea(
        id="arrays",
        classes=frozenset({"arrays", "dynamic_arrays"}),
        header=AreaHeader(text="Arrays", fill="#1E5A2E", font_size=FONT_SIZE),
        fill="#DDF5DD",
        stroke="#5A9E5A",
    ),
)

SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)

BACKGROUND_GROUP_IDS = frozenset({
    "class-backgrounds",
    "class-background-fills",
    "class-background-headers",
})


def local_tag(element: ET.Element) -> str:
    tag = element.tag
    return tag.split("}", 1)[-1] if "}" in tag else tag


def parse_classes(class_attr: str | None) -> set[str]:
    if not class_attr:
        return set()
    return set(class_attr.split())


def rect_bounds(rect: ET.Element) -> list[tuple[float, float]]:
    x = float(rect.get("x", 0))
    y = float(rect.get("y", 0))
    w = float(rect.get("width", 0))
    h = float(rect.get("height", 0))
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


def path_bounds(path: ET.Element) -> list[tuple[float, float]]:
    d = path.get("d", "")
    nums = [float(n) for n in re.findall(r"-?\d*\.?\d+", d)]
    if len(nums) < 2:
        return []
    xs = nums[0::2]
    ys = nums[1::2]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    return [(xmin, ymin), (xmax, ymin), (xmax, ymax), (xmin, ymax)]


def has_direct_shape_child(group: ET.Element) -> bool:
    return any(
        local_tag(child) == "g" and child.get("class") == "shape" for child in group
    )


def build_parent_map(root: ET.Element) -> dict[ET.Element, ET.Element]:
    return {child: parent for parent in root.iter() for child in parent}


def iter_diagram_node_groups(canvas: ET.Element):
    """Yield outermost node <g> elements (D2 wraps some in <a> link groups)."""
    parents = build_parent_map(canvas)
    for group in canvas.iter():
        if local_tag(group) != "g":
            continue
        if not has_direct_shape_child(group):
            continue
        parent = parents.get(group)
        if parent is not None and local_tag(parent) == "g" and has_direct_shape_child(parent):
            continue
        yield group


def shape_points(shape_group: ET.Element) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for child in shape_group:
        tag = local_tag(child)
        if tag == "rect":
            points.extend(rect_bounds(child))
        elif tag == "path":
            points.extend(path_bounds(child))
    return points


def cross(o: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def convex_hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    unique = sorted(set(points))
    if len(unique) <= 1:
        return unique
    if len(unique) == 2:
        return unique

    lower: list[tuple[float, float]] = []
    for p in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    upper: list[tuple[float, float]] = []
    for p in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    return lower[:-1] + upper[:-1]


def pad_hull(
    hull: list[tuple[float, float]], padding: float
) -> list[tuple[float, float]]:
    if not hull:
        return hull
    if len(hull) == 1:
        x, y = hull[0]
        return [
            (x - padding, y - padding),
            (x + padding, y - padding),
            (x + padding, y + padding),
            (x - padding, y + padding),
        ]

    cx = sum(p[0] for p in hull) / len(hull)
    cy = sum(p[1] for p in hull) / len(hull)
    padded: list[tuple[float, float]] = []
    for x, y in hull:
        dx, dy = x - cx, y - cy
        dist = math.hypot(dx, dy)
        if dist < 1e-9:
            padded.append((x, y))
        else:
            scale = (dist + padding) / dist
            padded.append((cx + dx * scale, cy + dy * scale))
    return padded


def polygon_centroid(hull: list[tuple[float, float]]) -> tuple[float, float]:
    """Geometric center (center of gravity) of a simple polygon."""
    n = len(hull)
    if n == 0:
        return 0.0, 0.0
    if n == 1:
        return hull[0]
    if n == 2:
        return ((hull[0][0] + hull[1][0]) / 2, (hull[0][1] + hull[1][1]) / 2)

    signed_area = 0.0
    cx = 0.0
    cy = 0.0
    for i in range(n):
        x0, y0 = hull[i]
        x1, y1 = hull[(i + 1) % n]
        cross = x0 * y1 - x1 * y0
        signed_area += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross

    signed_area *= 0.5
    if abs(signed_area) < 1e-9:
        return sum(p[0] for p in hull) / n, sum(p[1] for p in hull) / n

    cx /= 6.0 * signed_area
    cy /= 6.0 * signed_area
    return cx, cy


def points_to_polygon_attr(points: list[tuple[float, float]]) -> str:
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in points)


def find_d2_canvas(root: ET.Element) -> ET.Element:
    for element in root.iter():
        if local_tag(element) != "svg":
            continue
        classes = parse_classes(element.get("class"))
        if any(c.startswith("d2-") for c in classes) or "d2-svg" in (element.get("class") or ""):
            return element
    for element in root:
        if local_tag(element) == "svg":
            return element
    raise ValueError("Could not find inner D2 <svg> canvas in file.")


def collect_node_points(
    canvas: ET.Element, target_classes: frozenset[str]
) -> tuple[list[tuple[float, float]], int]:
    points: list[tuple[float, float]] = []
    node_count = 0
    for group in iter_diagram_node_groups(canvas):
        classes = parse_classes(group.get("class"))
        if not classes & target_classes:
            continue

        shape_group = next(
            child
            for child in group
            if local_tag(child) == "g" and child.get("class") == "shape"
        )
        node_points = shape_points(shape_group)
        if not node_points:
            continue
        node_count += 1
        points.extend(node_points)
    return points, node_count


def is_background_group(element: ET.Element) -> bool:
    return element.get("id") in BACKGROUND_GROUP_IDS


def find_canvas_rect_insert_index(canvas: ET.Element) -> int:
    for index, child in enumerate(canvas):
        if local_tag(child) == "rect":
            return index + 1
    return 0


def find_header_insert_index(canvas: ET.Element) -> int:
    """Place headers above fills but below all diagram nodes and edges."""
    for index, child in enumerate(canvas):
        if is_background_group(child):
            continue
        if local_tag(child) == "g" and has_direct_shape_child(child):
            return index
    return len(canvas)


def remove_existing_backgrounds(canvas: ET.Element) -> None:
    for group in list(canvas):
        if local_tag(group) == "g" and is_background_group(group):
            canvas.remove(group)


def append_area_header(
    parent: ET.Element,
    area: BackgroundArea,
    hull: list[tuple[float, float]],
) -> None:
    header = area.header
    cx, cy = polygon_centroid(hull)
    cx += header.offset_x
    cy += header.offset_y
    label = ET.SubElement(
        parent,
        f"{{{SVG_NS}}}text",
        {
            "class": f"class-background-header class-background-header-{area.id}",
            "data-group": area.id,
            "x": f"{cx:.2f}",
            "y": f"{cy:.2f}",
            "fill": header.fill,
            "style": (
                "text-anchor:middle;dominant-baseline:middle;"
                "pointer-events:none;"
                f"font-size:{header.font_size}px;"
                f"font-weight:{header.font_weight};"
                f"font-family:{header.font_family};"
            ),
        },
    )
    label.text = header.text


def insert_backgrounds(
    canvas: ET.Element,
    areas: tuple[BackgroundArea, ...],
    padding: float,
) -> dict[str, tuple[int, bool]]:
    remove_existing_backgrounds(canvas)

    fills_root = ET.Element(f"{{{SVG_NS}}}g", {"id": "class-background-fills"})
    headers_root = ET.Element(f"{{{SVG_NS}}}g", {"id": "class-background-headers"})

    stats: dict[str, tuple[int, bool]] = {}
    has_fills = False
    has_headers = False
    for area in areas:
        points, node_count = collect_node_points(canvas, area.classes)
        drawn = False
        if len(points) < 3:
            stats[area.id] = (node_count, drawn)
            continue
        hull = convex_hull(points)
        if len(hull) < 3:
            stats[area.id] = (node_count, drawn)
            continue
        hull = pad_hull(hull, padding)
        drawn = True
        has_fills = True
        has_headers = True

        area_fill_group = ET.SubElement(
            fills_root,
            f"{{{SVG_NS}}}g",
            {
                "class": f"class-background-area class-background-area-{area.id}",
                "data-group": area.id,
            },
        )
        ET.SubElement(
            area_fill_group,
            f"{{{SVG_NS}}}polygon",
            {
                "class": f"class-background class-background-{area.id}",
                "points": points_to_polygon_attr(hull),
                "fill": area.fill,
                "fill-opacity": str(area.fill_opacity),
                "stroke": area.stroke,
                "stroke-opacity": str(area.stroke_opacity),
                "stroke-width": str(area.stroke_width),
            },
        )

        area_header_group = ET.SubElement(
            headers_root,
            f"{{{SVG_NS}}}g",
            {
                "class": f"class-background-header-area class-background-header-area-{area.id}",
                "data-group": area.id,
            },
        )
        append_area_header(area_header_group, area, hull)
        stats[area.id] = (node_count, drawn)

    if has_fills:
        canvas.insert(find_canvas_rect_insert_index(canvas), fills_root)
    if has_headers:
        header_insert_at = find_header_insert_index(canvas)
        canvas.insert(header_insert_at, headers_root)
    return stats


def process_svg(svg_path: Path, output_path: Path | None) -> None:
    tree = ET.parse(svg_path)
    root = tree.getroot()
    canvas = find_d2_canvas(root)
    stats = insert_backgrounds(canvas, BACKGROUND_AREAS, PADDING)

    dest = output_path or svg_path
    tree.write(dest, encoding="utf-8", xml_declaration=True)

    for area in BACKGROUND_AREAS:
        node_count, drawn = stats.get(area.id, (0, False))
        if node_count == 0:
            print(
                f"warning: no nodes found for class(es) {sorted(area.classes)!r}",
                file=sys.stderr,
            )
        elif not drawn:
            print(
                f"warning: could not build hull for '{area.id}' ({node_count} nodes)",
                file=sys.stderr,
            )
        else:
            print(f"  {area.header.text}: {node_count} nodes")
    print(f"Wrote {dest}")


def main() -> int:
    if not SVG_PATH.is_file():
        print(f"error: file not found: {SVG_PATH}", file=sys.stderr)
        return 1

    process_svg(SVG_PATH, OUTPUT_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
