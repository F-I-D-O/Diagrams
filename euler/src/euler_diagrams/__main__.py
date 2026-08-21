"""Command-line entry point: compute a layout for an input file.

Usage: python -m euler_diagrams FILE
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .input_format import InputFormatError, load_set_system
from .layout import LayoutError, layout_2d
from .svg import RenderError, render_svg


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m euler_diagrams",
        description="Compute a rectangular Euler diagram for a set system.",
    )
    parser.add_argument("file", type=Path, help="input file (YAML or JSON)")
    parser.add_argument(
        "-o",
        "--output",
        help="write an SVG rendering to this file ('-' for stdout); "
        "without this option a plain-text layout summary is printed",
    )
    args = parser.parse_args(argv)

    try:
        system = load_set_system(args.file)
        layout = layout_2d(system)
        if args.output is not None:
            svg = render_svg(layout)
            if args.output == "-":
                sys.stdout.write(svg)
            else:
                Path(args.output).write_text(svg, encoding="utf-8")
            return 0
    except (OSError, InputFormatError, LayoutError, RenderError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    if layout.name is not None:
        print(f"name: {layout.name}")
    print("rectangles:")
    for set_name, rectangle in sorted(layout.rectangles.items()):
        print(
            f"  {set_name}: x=[{rectangle.x_min}, {rectangle.x_max}] "
            f"y=[{rectangle.y_min}, {rectangle.y_max}]"
        )
    print("points:")
    for element, (x, y) in sorted(layout.points.items()):
        print(f"  {element}: ({x}, {y})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
