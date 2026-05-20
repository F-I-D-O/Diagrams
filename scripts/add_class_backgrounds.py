#!/usr/bin/env python3
"""Add convex-hull background regions to a D2 SVG for diagram group classes.

D2 encodes each node as a top-level <g> whose class attribute lists the node id
(base64) plus D2 classes (e.g. "decision sets"). This script finds nodes for
selected classes, computes a padded convex hull of their shape bounds, and
inserts semi-transparent polygons behind the diagram content.

Typical usage (after compiling .d2 to .svg):

    d2 "Collection Decision Tree.d2" "Collection Decision Tree.svg"
    python scripts/add_class_backgrounds.py "Collection Decision Tree.svg"
"""

from __future__ import annotations

import argparse
import math
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# Match fill colors from Collection Decision Tree.d2 classes block.
DEFAULT_GROUP_COLORS: dict[str, str] = {
    "sets": "#E8F4FC",
    "maps": "#F3E8FC",
    "arrays": "#E8FCE8",
}

# Nodes tagged dynamic_arrays are included in the arrays background hull.
ARRAYS_ALIASES = frozenset({"arrays", "dynamic_arrays"})

SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)


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


def points_to_polygon_attr(points: list[tuple[float, float]]) -> str:
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in points)


def find_d2_canvas(root: ET.Element) -> ET.Element:
    for element in root.iter():
        if local_tag(element) != "svg":
            continue
        classes = parse_classes(element.get("class"))
        if any(c.startswith("d2-") for c in classes) or "d2-svg" in (element.get("class") or ""):
            return element
    # Fallback: nested svg under root.
    for element in root:
        if local_tag(element) == "svg":
            return element
    raise ValueError("Could not find inner D2 <svg> canvas in file.")


def collect_node_points(
    canvas: ET.Element, target_class: str
) -> tuple[list[tuple[float, float]], int]:
    points: list[tuple[float, float]] = []
    node_count = 0
    for group in iter_diagram_node_groups(canvas):
        classes = parse_classes(group.get("class"))
        if target_class == "arrays":
            if not classes & ARRAYS_ALIASES:
                continue
        elif target_class not in classes:
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


def remove_existing_backgrounds(canvas: ET.Element) -> None:
    for group in list(canvas):
        if local_tag(group) == "g" and group.get("id") == "class-backgrounds":
            canvas.remove(group)


def insert_backgrounds(
    canvas: ET.Element,
    groups: list[str],
    colors: dict[str, str],
    padding: float,
    opacity: float,
) -> dict[str, tuple[int, bool]]:
    remove_existing_backgrounds(canvas)

    bg_root = ET.Element(
        f"{{{SVG_NS}}}g",
        {"id": "class-backgrounds"},
    )

    stats: dict[str, tuple[int, bool]] = {}
    for group in groups:
        points, node_count = collect_node_points(canvas, group)
        drawn = False
        if len(points) < 3:
            stats[group] = (node_count, drawn)
            continue
        hull = convex_hull(points)
        if len(hull) < 3:
            stats[group] = (node_count, drawn)
            continue
        hull = pad_hull(hull, padding)
        drawn = True
        ET.SubElement(
            bg_root,
            f"{{{SVG_NS}}}polygon",
            {
                "class": f"class-background class-background-{group}",
                "data-group": group,
                "points": points_to_polygon_attr(hull),
                "fill": colors.get(group, "#EEEEEE"),
                "fill-opacity": str(opacity),
                "stroke": colors.get(group, "#CCCCCC"),
                "stroke-opacity": "0.6",
                "stroke-width": "2",
            },
        )
        stats[group] = (node_count, drawn)

    # Insert immediately after the canvas background <rect>, before diagram nodes.
    insert_at = 0
    for i, child in enumerate(canvas):
        if local_tag(child) == "rect":
            insert_at = i + 1
            break
    canvas.insert(insert_at, bg_root)
    return stats


def process_svg(
    svg_path: Path,
    output_path: Path | None,
    groups: list[str],
    padding: float,
    opacity: float,
    colors: dict[str, str],
) -> None:
    tree = ET.parse(svg_path)
    root = tree.getroot()
    canvas = find_d2_canvas(root)
    stats = insert_backgrounds(canvas, groups, colors, padding, opacity)

    dest = output_path or svg_path
    tree.write(dest, encoding="utf-8", xml_declaration=True)

    for group in groups:
        node_count, drawn = stats.get(group, (0, False))
        if node_count == 0:
            print(f"warning: no nodes found for class '{group}'", file=sys.stderr)
        elif not drawn:
            print(
                f"warning: could not build hull for '{group}' ({node_count} nodes)",
                file=sys.stderr,
            )
        else:
            print(f"  {group}: {node_count} nodes")
    print(f"Wrote {dest}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Add convex-hull class backgrounds to a D2-generated SVG."
    )
    parser.add_argument(
        "svg",
        type=Path,
        help="Path to the SVG file (modified in place unless --output is set).",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output path (default: overwrite input).",
    )
    parser.add_argument(
        "--groups",
        nargs="+",
        default=list(DEFAULT_GROUP_COLORS),
        help="D2 class names to outline (default: sets maps arrays).",
    )
    parser.add_argument(
        "--padding",
        type=float,
        default=24.0,
        help="Outward padding in SVG units (default: 24).",
    )
    parser.add_argument(
        "--opacity",
        type=float,
        default=0.45,
        help="Background fill opacity (default: 0.45).",
    )
    parser.add_argument(
        "--color",
        action="append",
        metavar="GROUP=HEX",
        help="Override fill/stroke color for a group (e.g. sets=#E8F4FC).",
    )
    args = parser.parse_args()

    if not args.svg.is_file():
        print(f"error: file not found: {args.svg}", file=sys.stderr)
        return 1

    colors = dict(DEFAULT_GROUP_COLORS)
    if args.color:
        for item in args.color:
            if "=" not in item:
                print(f"error: invalid --color value: {item}", file=sys.stderr)
                return 1
            name, value = item.split("=", 1)
            colors[name.strip()] = value.strip()

    process_svg(
        args.svg,
        args.output,
        args.groups,
        args.padding,
        args.opacity,
        colors,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
