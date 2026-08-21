"""Internal data model for Euler diagram set systems."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property


@dataclass(frozen=True)
class SetSystem:
    """A named family of sets — the input of all layout algorithms.

    Equivalent to a formal context whose objects are the elements and whose
    attributes are the set names, which is the structure the algorithms of
    Dürrschnabel & Priss (arXiv:2403.03801) operate on. ``set_links`` and
    ``element_links`` carry optional URLs per set and element name.
    """

    sets: dict[str, frozenset[str]]
    name: str | None = None
    set_links: dict[str, str] = field(default_factory=dict)
    element_links: dict[str, str] = field(default_factory=dict)

    @cached_property
    def elements(self) -> frozenset[str]:
        """All elements occurring in at least one set."""
        return frozenset().union(*self.sets.values()) if self.sets else frozenset()

    def memberships(self, element: str) -> frozenset[str]:
        """Names of the sets that contain ``element``."""
        if element not in self.elements:
            raise KeyError(element)
        return frozenset(name for name, members in self.sets.items() if element in members)

    @cached_property
    def zones(self) -> frozenset[frozenset[str]]:
        """The non-empty zones: distinct membership signatures of the elements.

        Each zone is the set of set names whose mutual intersection (minus all
        other sets) is inhabited. The outer zone is not included.
        """
        return frozenset(self.memberships(element) for element in self.elements)
