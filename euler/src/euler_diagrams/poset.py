"""Finite partial orders and the extended Euler-poset of a formal context.

The extended Euler-poset is Definition 6 of Dürrschnabel & Priss:
*Realizability of Rectangular Euler Diagrams* (arXiv:2403.03801). Its order
dimension characterizes the existence of a rectangular Euler diagram.

Poset elements are tagged tuples so that objects, attributes, object copies
and the scaffolding elements can never collide: ``("obj", g)``,
``("attr", m)``, ``("copy1", g)``, ``("copy2", g)``, ``("a", i)``,
``("b", i)``.
"""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from typing import Iterable, Sequence

Element = tuple

OBJ = "obj"
ATTR = "attr"
COPY1 = "copy1"
COPY2 = "copy2"
A = "a"
B = "b"


class Poset:
    """A finite ordered set given by its strict order relation.

    The relation is validated to be irreflexive, antisymmetric and
    transitively closed.
    """

    def __init__(
        self, elements: Sequence[Element], strictly_less: Iterable[tuple[Element, Element]]
    ) -> None:
        self.elements = tuple(elements)
        element_set = set(self.elements)
        if len(element_set) != len(self.elements):
            raise ValueError("duplicate poset elements")
        less = frozenset(strictly_less)
        successors: dict[Element, set[Element]] = defaultdict(set)
        for x, y in less:
            if x not in element_set or y not in element_set:
                raise ValueError(f"relation pair ({x!r}, {y!r}) uses unknown elements")
            if x == y:
                raise ValueError(f"relation is not irreflexive at {x!r}")
            if (y, x) in less:
                raise ValueError(f"relation is not antisymmetric at ({x!r}, {y!r})")
            successors[x].add(y)
        for x, y in less:
            not_inherited = successors[y] - successors[x]
            if not_inherited:
                z = next(iter(not_inherited))
                raise ValueError(f"relation is not transitive: {x!r} < {y!r} < {z!r}")
        self.strictly_less = less

    def is_less(self, x: Element, y: Element) -> bool:
        return (x, y) in self.strictly_less

    def comparable(self, x: Element, y: Element) -> bool:
        return (x, y) in self.strictly_less or (y, x) in self.strictly_less

    def incomparable_pairs(self) -> list[tuple[Element, Element]]:
        """All unordered incomparable pairs, in deterministic order."""
        return [
            (x, y) for x, y in combinations(self.elements, 2) if not self.comparable(x, y)
        ]


def extended_euler_poset(
    extents: dict[str, frozenset[str]], objects: Sequence[str]
) -> Poset:
    """Build the extended Euler-poset of a clarified formal context.

    ``extents`` maps each attribute to its set of objects. The context must be
    clarified: attribute extents and object intents must be pairwise distinct.
    """
    attributes = sorted(extents)
    if len(set(extents.values())) != len(attributes):
        raise ValueError("context is not clarified: duplicate attribute extents")
    intents = defaultdict(frozenset)
    for g in objects:
        intents[g] = frozenset(m for m in attributes if g in extents[m])
    if len(set(intents.values())) != len(objects):
        raise ValueError("context is not clarified: duplicate object intents")

    less: set[tuple[Element, Element]] = set()
    for m in attributes:
        for g in extents[m]:
            less.add(((OBJ, g), (ATTR, m)))
    for m1 in attributes:
        for m2 in attributes:
            if m1 != m2 and extents[m1] < extents[m2]:
                less.add(((ATTR, m1), (ATTR, m2)))
    for g in objects:
        less.add(((OBJ, g), (COPY1, g)))
        less.add(((OBJ, g), (COPY2, g)))
        less.add(((A, 1), (COPY1, g)))
        less.add(((A, 2), (COPY1, g)))
        less.add(((A, 3), (COPY2, g)))
        less.add(((A, 4), (COPY2, g)))
    for i in range(1, 5):
        for j in range(1, 5):
            if i != j:
                less.add(((A, i), (B, j)))
    ground = [(OBJ, g) for g in objects] + [(ATTR, m) for m in attributes]
    for x in ground:
        for i in range(1, 5):
            less.add((x, (B, i)))

    elements = (
        ground
        + [(COPY1, g) for g in objects]
        + [(COPY2, g) for g in objects]
        + [(A, i) for i in range(1, 5)]
        + [(B, i) for i in range(1, 5)]
    )
    return Poset(elements, less)
