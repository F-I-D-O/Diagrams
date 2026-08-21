"""Loading and validation of the YAML/JSON input format (version 1).

The format is documented in ``docs/input-format.md``. JSON input needs no
separate code path because YAML is a superset of JSON.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from .model import SetSystem

_TOP_LEVEL_KEYS = {"name", "sets", "links"}


class InputFormatError(ValueError):
    """Raised when an input file does not conform to the input format."""


class _StrictLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate mapping keys instead of ignoring them."""


def _construct_mapping(loader: _StrictLoader, node: yaml.MappingNode) -> dict:
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in mapping:
            raise InputFormatError(
                f"duplicate key {key!r} on line {key_node.start_mark.line + 1}"
            )
        mapping[key] = loader.construct_object(value_node, deep=True)
    return mapping


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
)


def load_set_system(path: str | Path) -> SetSystem:
    """Load and validate a set system from a YAML or JSON file."""
    path = Path(path)
    return parse_set_system(path.read_text(encoding="utf-8"), source=str(path))


def parse_set_system(text: str, source: str = "<string>") -> SetSystem:
    """Parse and validate a set system from YAML or JSON text.

    ``source`` is used in error messages only.
    """
    try:
        document = yaml.load(text, Loader=_StrictLoader)
    except yaml.YAMLError as error:
        raise InputFormatError(f"{source}: not valid YAML/JSON: {error}") from error

    if not isinstance(document, dict):
        raise InputFormatError(f"{source}: top level must be a mapping")

    unknown_keys = set(document) - _TOP_LEVEL_KEYS
    if unknown_keys:
        raise InputFormatError(
            f"{source}: unknown top-level keys: {', '.join(sorted(map(repr, unknown_keys)))}"
        )

    name = document.get("name")
    if name is not None and not isinstance(name, str):
        raise InputFormatError(f"{source}: 'name' must be a string")

    if "sets" not in document:
        raise InputFormatError(f"{source}: missing required key 'sets'")
    raw_sets = document["sets"]
    if not isinstance(raw_sets, dict) or not raw_sets:
        raise InputFormatError(
            f"{source}: 'sets' must be a non-empty mapping of set names to element lists"
        )

    sets: dict[str, frozenset[str]] = {}
    for set_name, raw_members in raw_sets.items():
        if not isinstance(set_name, str):
            raise InputFormatError(f"{source}: set name {set_name!r} is not a string")
        sets[set_name] = _validate_members(set_name, raw_members, source)

    set_links, element_links = _validate_links(document.get("links"), sets, source)
    return SetSystem(
        sets=sets, name=name, set_links=set_links, element_links=element_links
    )


def _validate_links(
    raw_links: object, sets: dict[str, frozenset[str]], source: str
) -> tuple[dict[str, str], dict[str, str]]:
    """Resolve the flat ``links`` mapping against set and element names."""
    if raw_links is None:
        return {}, {}
    if not isinstance(raw_links, dict):
        raise InputFormatError(
            f"{source}: 'links' must be a mapping of set or element names to URLs"
        )
    elements = frozenset().union(*sets.values()) if sets else frozenset()
    set_links: dict[str, str] = {}
    element_links: dict[str, str] = {}
    for target, url in raw_links.items():
        if not isinstance(target, str):
            raise InputFormatError(f"{source}: link target {target!r} is not a string")
        if not isinstance(url, str) or not url:
            raise InputFormatError(
                f"{source}: link for {target!r} must be a non-empty string URL"
            )
        is_set, is_element = target in sets, target in elements
        if is_set and is_element:
            raise InputFormatError(
                f"{source}: link target {target!r} names both a set and an "
                "element; rename one of them to disambiguate"
            )
        if is_set:
            set_links[target] = url
        elif is_element:
            element_links[target] = url
        else:
            raise InputFormatError(
                f"{source}: link target {target!r} is neither a set nor an element"
            )
    return set_links, element_links


def _validate_members(set_name: str, raw_members: object, source: str) -> frozenset[str]:
    if raw_members is None:
        return frozenset()
    if not isinstance(raw_members, list):
        raise InputFormatError(
            f"{source}: set {set_name!r} must map to a list of elements"
        )
    members: set[str] = set()
    for element in raw_members:
        if not isinstance(element, str):
            raise InputFormatError(
                f"{source}: set {set_name!r} contains non-string element {element!r}"
            )
        if element in members:
            raise InputFormatError(
                f"{source}: set {set_name!r} lists element {element!r} twice"
            )
        members.add(element)
    return frozenset(members)
