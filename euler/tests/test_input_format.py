"""Tests for the YAML/JSON input format loader."""

from pathlib import Path

import pytest

from euler_diagrams import InputFormatError, load_set_system, parse_set_system

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"

VALID = """
name: languages
sets:
  compiled: [c, cpp, rust, java]
  gc: [java, go, python]
  scripting: [python, js]
"""


def test_parses_valid_document() -> None:
    system = parse_set_system(VALID)
    assert system.name == "languages"
    assert system.sets["compiled"] == {"c", "cpp", "rust", "java"}
    assert system.elements == {"c", "cpp", "rust", "java", "go", "python", "js"}


def test_memberships_and_zones() -> None:
    system = parse_set_system(VALID)
    assert system.memberships("java") == {"compiled", "gc"}
    assert system.zones == {
        frozenset({"compiled"}),
        frozenset({"compiled", "gc"}),
        frozenset({"gc"}),
        frozenset({"gc", "scripting"}),
        frozenset({"scripting"}),
    }


def test_memberships_of_unknown_element_raises() -> None:
    with pytest.raises(KeyError):
        parse_set_system(VALID).memberships("cobol")


def test_loads_example_file() -> None:
    system = load_set_system(EXAMPLES_DIR / "languages.yaml")
    assert system.name == "languages"


def test_parses_json_document() -> None:
    system = parse_set_system('{"sets": {"A": ["x"], "B": ["x", "y"]}}')
    assert system.name is None
    assert system.zones == {frozenset({"A", "B"}), frozenset({"B"})}


def test_name_is_optional() -> None:
    assert parse_set_system("sets: {A: [x]}").name is None


def test_empty_set_allowed() -> None:
    system = parse_set_system("sets:\n  A: [x]\n  B: []\n  C:\n")
    assert system.sets["B"] == frozenset()
    assert system.sets["C"] == frozenset()


def test_links_resolve_to_sets_and_elements() -> None:
    system = parse_set_system(
        """
sets:
  A: [x, y]
  B: [y]
links:
  A: https://example.org/a
  x: ./local/x.html
"""
    )
    assert system.set_links == {"A": "https://example.org/a"}
    assert system.element_links == {"x": "./local/x.html"}


def test_links_are_optional_and_default_empty() -> None:
    system = parse_set_system("sets: {A: [x]}")
    assert system.set_links == {}
    assert system.element_links == {}


@pytest.mark.parametrize(
    "text, match",
    [
        ("sets: {A: [x]}\nlinks: [not, a, mapping]", "'links' must be a mapping"),
        ("sets: {A: [x]}\nlinks: {B: u}", "neither a set nor an element"),
        ("sets: {A: [x]}\nlinks: {A: 3}", "non-empty string URL"),
        ("sets: {A: [x]}\nlinks: {A: ''}", "non-empty string URL"),
        ("sets: {A: [x], x: [A]}\nlinks: {x: u}", "both a set and an element"),
    ],
)
def test_invalid_links_rejected(text: str, match: str) -> None:
    with pytest.raises(InputFormatError, match=match):
        parse_set_system(text)


@pytest.mark.parametrize(
    "text, match",
    [
        ("- a\n- b", "top level must be a mapping"),
        ("sets: {A: [x]}\ncolor: red", "unknown top-level keys"),
        ("name: [not, a, string]\nsets: {A: [x]}", "'name' must be a string"),
        ("name: no sets here", "missing required key 'sets'"),
        ("sets: []", "non-empty mapping"),
        ("sets: {}", "non-empty mapping"),
        ("sets: {1: [x]}", "not a string"),
        ("sets: {A: x}", "must map to a list"),
        ("sets: {A: [1, 2]}", "non-string element"),
        ("sets: {A: [x, x]}", "twice"),
        ("sets: {A: [x], A: [y]}", "duplicate key"),
        ("sets: {A: [x]", "not valid YAML"),
    ],
)
def test_invalid_documents_rejected(text: str, match: str) -> None:
    with pytest.raises(InputFormatError, match=match):
        parse_set_system(text)
