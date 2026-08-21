"""Loading and validation of the YAML/JSON input format (version 1).

The format is documented in ``docs/input-format.md``. JSON input needs no
separate code path because YAML is a superset of JSON.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from .model import SetSystem

_TOP_LEVEL_KEYS = {"name", "sets", "links", "labels"}


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

    set_links, element_links = _resolve_flat_mapping(
        document.get("links"), sets, source, key="links", value_noun="URL"
    )
    set_labels, element_labels = _resolve_flat_mapping(
        document.get("labels"), sets, source, key="labels", value_noun="label"
    )
    return SetSystem(
        sets=sets,
        name=name,
        set_links=set_links,
        element_links=element_links,
        set_labels=set_labels,
        element_labels=element_labels,
    )


def _resolve_flat_mapping(
    raw: object,
    sets: dict[str, frozenset[str]],
    source: str,
    key: str,
    value_noun: str,
) -> tuple[dict[str, str], dict[str, str]]:
    """Resolve a flat name→string mapping against set and element names.

    Shared by ``links`` and ``labels``: keys must name exactly one of a set
    or an element, values must be non-empty strings.
    """
    if raw is None:
        return {}, {}
    if not isinstance(raw, dict):
        raise InputFormatError(
            f"{source}: '{key}' must be a mapping of set or element names to "
            f"{value_noun}s"
        )
    elements = frozenset().union(*sets.values()) if sets else frozenset()
    for_sets: dict[str, str] = {}
    for_elements: dict[str, str] = {}
    for target, value in raw.items():
        if not isinstance(target, str):
            raise InputFormatError(
                f"{source}: {key} target {target!r} is not a string"
            )
        if not isinstance(value, str) or not value:
            raise InputFormatError(
                f"{source}: {key} entry for {target!r} must be a non-empty "
                f"string {value_noun}"
            )
        is_set, is_element = target in sets, target in elements
        if is_set and is_element:
            raise InputFormatError(
                f"{source}: {key} target {target!r} names both a set and an "
                "element; rename one of them to disambiguate"
            )
        if is_set:
            for_sets[target] = value
        elif is_element:
            for_elements[target] = value
        else:
            raise InputFormatError(
                f"{source}: {key} target {target!r} is neither a set nor an element"
            )
    return for_sets, for_elements


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
