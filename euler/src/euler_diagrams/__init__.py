"""Generator of rectangular Euler diagrams (Dürrschnabel & Priss, arXiv:2403.03801)."""

from .input_format import InputFormatError, load_set_system, parse_set_system
from .layout import Layout, LayoutError, NotRealizableError, Rectangle, layout_2d
from .model import SetSystem
from .svg import RenderError, render_svg

__all__ = [
    "InputFormatError",
    "Layout",
    "LayoutError",
    "NotRealizableError",
    "Rectangle",
    "RenderError",
    "SetSystem",
    "layout_2d",
    "load_set_system",
    "parse_set_system",
    "render_svg",
]
