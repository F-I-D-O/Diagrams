"""Computing fixed-width realizers of partial orders via SAT.

A realizer of width ``t`` is a family of ``t`` linear extensions whose
intersection is exactly the order. Deciding whether one exists is NP-complete
for ``t >= 3`` (Yannakakis 1982), so the search is encoded as propositional
satisfiability: one variable per (extension, incomparable pair) stating the
pair's orientation, transitivity clauses making each extension a linear order,
and per-pair clauses requiring both orientations to occur among the
extensions.

For width-four realizers destined for two-dimensional Euler diagrams, the
choice among the many valid realizers matters for compactness: a non-incident
(object, attribute) pair whose incidence is broken on *both* axes
("double-break") scatters axis signatures and inflates the compacted grid.
``find_realizer`` can therefore minimize the number of double-breaks with a
MaxSAT pass (RC2): the hard clauses stay exactly the realizer encoding, and
one weight-1 soft clause per non-incident pair prefers the pair to stay
inside on at least one axis. Runtime remains exponential in the worst case;
realizability itself is decided by a plain SAT call first.
"""

from __future__ import annotations

from itertools import permutations
from typing import Iterable, Sequence

from pysat.examples.rc2 import RC2
from pysat.formula import WCNF
from pysat.solvers import Glucose3

from .poset import Element, Poset

Literal = int | bool


def find_realizer(
    poset: Poset,
    width: int,
    forced: Iterable[tuple[int, Element, Element]] = (),
    optimize_pairs: Iterable[tuple[Element, Element]] = (),
) -> list[list[Element]] | None:
    """Find ``width`` linear extensions of ``poset`` realizing it, or None.

    ``forced`` entries ``(k, x, y)`` pin ``x`` before ``y`` in extension ``k``
    (0-based) and are meant for symmetry breaking; every entry must concern an
    incomparable pair.

    ``optimize_pairs`` lists incomparable pairs ``(g, m)`` (an object and an
    attribute of an extended Euler-poset, extensions 0-1 forming the y-axis
    and 2-3 the x-axis of the diagram). Among all realizers, one is returned
    minimizing a compactness cost over the listed pairs: breaking a pair on
    both axes ("double-break", scattering axis signatures) costs 5, breaking
    it on the x-axis only costs 1, breaking it on the y-axis only is free —
    extra rows are far cheaper visually than extra columns, since member
    boxes are wide and flat. Requires ``width == 4``.
    """
    elements = poset.elements
    pairs = poset.incomparable_pairs()
    index = {pair: i for i, pair in enumerate(pairs)}

    def lit(k: int, x: Element, y: Element) -> Literal:
        """Literal for "x before y in extension k"; a bool if the order decides."""
        if poset.is_less(x, y):
            return True
        if poset.is_less(y, x):
            return False
        i = index.get((x, y))
        if i is not None:
            return k * len(pairs) + i + 1
        return -(k * len(pairs) + index[(y, x)] + 1)

    def negated(literal: Literal) -> Literal:
        return (not literal) if isinstance(literal, bool) else -literal

    clauses: list[list[int]] = []

    def add(literals: list[Literal]) -> None:
        clause = []
        for literal in literals:
            if literal is True:
                return
            if literal is False:
                continue
            clause.append(literal)
        clauses.append(clause)

    for k in range(width):
        for x, y, z in permutations(elements, 3):
            add([negated(lit(k, x, y)), negated(lit(k, y, z)), lit(k, x, z)])
    for x, y in pairs:
        add([lit(k, x, y) for k in range(width)])
        add([negated(lit(k, x, y)) for k in range(width)])
    for k, x, y in forced:
        literal = lit(k, x, y)
        if isinstance(literal, bool):
            raise ValueError(f"forced pair ({x!r}, {y!r}) is comparable")
        add([literal])

    with Glucose3(bootstrap_with=clauses) as solver:
        if not solver.solve():
            return None
        model = solver.get_model()

    objective_pairs = list(optimize_pairs)
    if objective_pairs:
        if width != 4:
            raise ValueError("realizer optimization requires width 4")
        formula = WCNF()
        for clause in clauses:
            formula.append(clause)
        next_variable = width * len(pairs) + 1
        for g, m in objective_pairs:
            inside_literals = []
            for axis in ((0, 1), (2, 3)):
                inside = next_variable
                next_variable += 1
                # inside => g before m in both extensions of the axis; the
                # reverse implication is unnecessary for the optimum.
                for k in axis:
                    literal = lit(k, g, m)
                    if literal is True:
                        continue
                    if literal is False:
                        formula.append([-inside])
                        break
                    formula.append([-inside, literal])
                inside_literals.append(inside)
            inside_y, inside_x = inside_literals
            formula.append([inside_x, inside_y], weight=4)
            formula.append([inside_x], weight=1)
        with RC2(formula) as optimizer:
            model = optimizer.compute()
        if model is None:
            raise AssertionError("hard clauses satisfiable but MaxSAT found no model")

    true_variables = {v for v in model if v > 0}

    def before(k: int, x: Element, y: Element) -> bool:
        literal = lit(k, x, y)
        if isinstance(literal, bool):
            return literal
        return literal in true_variables if literal > 0 else -literal not in true_variables

    extensions = []
    for k in range(width):
        predecessors = {x: 0 for x in elements}
        for x, y in permutations(elements, 2):
            if before(k, x, y):
                predecessors[y] += 1
        extension = sorted(elements, key=predecessors.__getitem__)
        if sorted(predecessors.values()) != list(range(len(elements))):
            raise AssertionError("SAT model does not induce a linear order")
        extensions.append(extension)
    return extensions


def count_double_breaks(
    extensions: Sequence[Sequence[Element]],
    pairs: Iterable[tuple[Element, Element]],
) -> int:
    """Count pairs ``(g, m)`` broken on both diagram axes of a 4-realizer.

    ``g`` counts as inside on an axis when it precedes ``m`` in both of the
    axis's extensions (0-1 and 2-3, matching ``minimize_double_breaks``).
    """
    positions = [{x: i for i, x in enumerate(extension)} for extension in extensions]
    count = 0
    for g, m in pairs:
        inside_any = any(
            all(positions[k][g] < positions[k][m] for k in axis)
            for axis in ((0, 1), (2, 3))
        )
        count += not inside_any
    return count


def realizes(poset: Poset, extensions: Sequence[Sequence[Element]]) -> bool:
    """Check that the intersection of ``extensions`` is exactly ``poset``."""
    positions = [{x: i for i, x in enumerate(extension)} for extension in extensions]
    for x, y in permutations(poset.elements, 2):
        less_in_all = all(position[x] < position[y] for position in positions)
        if less_in_all != poset.is_less(x, y):
            return False
    return True
