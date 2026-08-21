"""Two-dimensional rectangular Euler diagram layout.

Implements algorithm ``Euler2D`` of Dürrschnabel & Priss: *Realizability of
Rectangular Euler Diagrams* (arXiv:2403.03801): the set system is clarified
into a formal context, its extended Euler-poset is built, and a realizer of
width four is searched — the diagram exists if and only if one is found. Per
axis, two of the four linear extensions are scanned into interval boundaries
and point positions (the paper's ``EulerFromLinearExtension``; note that its
published pseudocode swaps the roles of the two scans, the version here is the
corrected one: the forward scan of the first extension yields each attribute's
upper boundary, the backward scan of the second its lower boundary).

Coordinates are integers; rectangle boundaries are even and point coordinates
odd, so a point never lies on a rectangle border. Renderers may rescale as
long as the coordinate order along each axis is preserved.

Known caveats inherited from the paper's diagram definition, which constrains
only point containment: two disjoint sets may be drawn as geometrically
overlapping rectangles when no element witnesses the overlap, and distinct
boundaries may share a coordinate (touching rectangles).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .model import SetSystem
from .poset import A, ATTR, B, OBJ, Element, extended_euler_poset
from .realizer import find_realizer

__all__ = ["Layout", "LayoutError", "NotRealizableError", "Rectangle", "layout_2d"]


class LayoutError(Exception):
    """Raised when no layout can be computed for the given set system."""


class NotRealizableError(LayoutError):
    """Raised when the set system has no rectangular Euler diagram."""


@dataclass(frozen=True)
class Rectangle:
    x_min: int
    x_max: int
    y_min: int
    y_max: int

    def contains(self, point: tuple[int, int]) -> bool:
        x, y = point
        return self.x_min <= x <= self.x_max and self.y_min <= y <= self.y_max


@dataclass(frozen=True)
class Layout:
    """Rectangles per set and a point per element; sets merged during
    clarification (equal element sets) share identical rectangles, elements
    with equal memberships share identical points."""

    rectangles: dict[str, Rectangle]
    points: dict[str, tuple[int, int]]
    name: str | None = None
    set_links: dict[str, str] = field(default_factory=dict)
    element_links: dict[str, str] = field(default_factory=dict)


def layout_2d(system: SetSystem) -> Layout:
    """Compute a rectangular Euler diagram layout for ``system``.

    Raises :class:`NotRealizableError` if none exists, :class:`LayoutError`
    for inputs outside the algorithm's scope (empty sets).
    """
    for set_name, members in system.sets.items():
        if not members:
            raise LayoutError(
                f"set {set_name!r} is empty; empty sets are not supported by the "
                "layout algorithm"
            )

    extents, objects, set_representative, element_representative = _clarify(system)
    poset = extended_euler_poset(extents, objects)
    # Symmetry breaking: in every width-4 realizer of the extended Euler-poset
    # each extension reverses exactly one scaffold pair (b_i, a_i) (see the
    # proof of Theorem 2), so extension k may be pinned to reverse pair k+1.
    forced = [(k, (B, k + 1), (A, k + 1)) for k in range(4)]
    forced += [(k, (A, i), (B, i)) for k in range(4) for i in range(1, 5) if i != k + 1]
    # Among all realizers, prefer compact ones: never break a non-incidence
    # on both axes when one suffices (double-breaks scatter axis signatures),
    # and prefer breaking on the y-axis, keeping the diagram to few columns.
    non_incident = [
        ((OBJ, g), (ATTR, m))
        for m, extent in extents.items()
        for g in objects
        if g not in extent
    ]
    realizer = find_realizer(poset, 4, forced, optimize_pairs=non_incident)
    if realizer is None:
        raise NotRealizableError(
            "the set system cannot be represented by a rectangular Euler diagram "
            "(its extended Euler-poset has order dimension greater than four)"
        )

    ground = [
        [x for x in extension if x[0] in (OBJ, ATTR)] for extension in realizer
    ]
    y_low, y_high, y_position = _scan_axis(ground[0], ground[1])
    x_low, x_high, x_position = _scan_axis(ground[2], ground[3])

    rectangles = {
        set_name: Rectangle(
            x_min=x_low[(ATTR, representative)],
            x_max=x_high[(ATTR, representative)],
            y_min=y_low[(ATTR, representative)],
            y_max=y_high[(ATTR, representative)],
        )
        for set_name, representative in set_representative.items()
    }
    points = {
        element: (x_position[(OBJ, representative)], y_position[(OBJ, representative)])
        for element, representative in element_representative.items()
    }
    rectangles, points = _compact(rectangles, points)

    for set_name, members in system.sets.items():
        rectangle = rectangles[set_name]
        for element in system.elements:
            if rectangle.contains(points[element]) != (element in members):
                raise AssertionError(
                    f"internal error: computed layout misrepresents "
                    f"({element!r}, {set_name!r})"
                )
    return Layout(
        rectangles=rectangles,
        points=points,
        name=system.name,
        set_links=dict(system.set_links),
        element_links=dict(system.element_links),
    )


def _clarify(
    system: SetSystem,
) -> tuple[dict[str, frozenset[str]], list[str], dict[str, str], dict[str, str]]:
    """Clarify the formal context of ``system``.

    Elements with equal memberships collapse into one object, sets with equal
    element sets into one attribute; each is represented by its
    lexicographically smallest member. Returns the clarified extents, the
    object list, and the set-name and element representative maps.
    """
    membership_groups: dict[frozenset[str], list[str]] = defaultdict(list)
    for element in sorted(system.elements):
        membership_groups[system.memberships(element)].append(element)
    element_representative = {
        element: group[0] for group in membership_groups.values() for element in group
    }

    extent_groups: dict[frozenset[str], list[str]] = defaultdict(list)
    for set_name in sorted(system.sets):
        extent = frozenset(
            element_representative[element] for element in system.sets[set_name]
        )
        extent_groups[extent].append(set_name)
    set_representative = {
        set_name: group[0] for group in extent_groups.values() for set_name in group
    }
    extents = {group[0]: extent for extent, group in extent_groups.items()}
    objects = sorted(group[0] for group in membership_groups.values())
    return extents, objects, set_representative, element_representative


def _compact(
    rectangles: dict[str, Rectangle], points: dict[str, tuple[int, int]]
) -> tuple[dict[str, Rectangle], dict[str, tuple[int, int]]]:
    """Remove structurally empty rows and columns from an integer layout.

    The scan gives every element a private coordinate per axis, leaving the
    diagram a sparse permutation-like scatter. On each axis, a maximal run of
    element positions with no rectangle boundary between them lies in exactly
    the same intervals of that axis, so the run can collapse onto one
    coordinate without changing any membership; a run of boundary coordinates
    with no element between them collapses likewise. Renumbering group by
    group keeps boundaries even and element positions odd (an axis always
    starts and ends with a boundary, and group types alternate).
    """
    x_map = _compaction_map(
        {r.x_min for r in rectangles.values()} | {r.x_max for r in rectangles.values()},
        {x for x, _ in points.values()},
    )
    y_map = _compaction_map(
        {r.y_min for r in rectangles.values()} | {r.y_max for r in rectangles.values()},
        {y for _, y in points.values()},
    )
    compact_rectangles = {
        name: Rectangle(
            x_min=x_map[r.x_min],
            x_max=x_map[r.x_max],
            y_min=y_map[r.y_min],
            y_max=y_map[r.y_max],
        )
        for name, r in rectangles.items()
    }
    compact_points = {
        element: (x_map[x], y_map[y]) for element, (x, y) in points.items()
    }
    return compact_rectangles, compact_points


def _compaction_map(boundaries: set[int], positions: set[int]) -> dict[int, int]:
    """Map axis coordinates to their group index (one group, one coordinate)."""
    mapping: dict[int, int] = {}
    group = -1
    previous_is_boundary: bool | None = None
    for coordinate in sorted(boundaries | positions):
        is_boundary = coordinate in boundaries
        if is_boundary != previous_is_boundary:
            group += 1
            previous_is_boundary = is_boundary
        mapping[coordinate] = group
    return mapping


def _scan_axis(
    first: list[Element], second: list[Element]
) -> tuple[dict[Element, int], dict[Element, int], dict[Element, int]]:
    """Turn two linear extensions of an Euler-poset into one axis of a diagram.

    ``first`` is scanned from its smallest element upward and assigns each
    attribute its upper interval boundary; ``second`` is scanned from its
    largest element downward and assigns the lower boundary. Whenever both
    scans rest on an object it is the same one (object orders are mutually
    reversed) and it is placed between the boundaries written so far. A point
    then lies in an attribute's interval if and only if the object is below
    the attribute in both extensions.
    """
    count = len(first)
    low: dict[Element, int] = {}
    high: dict[Element, int] = {}
    position: dict[Element, int] = {}
    i1 = i2 = coordinate = 0
    while i1 < count or i2 < count:
        progressed = False
        if i1 < count and first[i1][0] == ATTR:
            high[first[i1]] = coordinate
            i1 += 1
            progressed = True
        if i2 < count and second[count - 1 - i2][0] == ATTR:
            low[second[count - 1 - i2]] = coordinate
            i2 += 1
            progressed = True
        if (
            i1 < count
            and i2 < count
            and first[i1][0] == OBJ
            and second[count - 1 - i2][0] == OBJ
        ):
            if first[i1] != second[count - 1 - i2]:
                raise AssertionError(
                    "internal error: object orders of the two extensions are "
                    "not mutually reversed"
                )
            position[first[i1]] = coordinate + 1
            coordinate += 2
            i1 += 1
            i2 += 1
            progressed = True
        if not progressed:
            raise AssertionError("internal error: axis scan stalled")
    return low, high, position
