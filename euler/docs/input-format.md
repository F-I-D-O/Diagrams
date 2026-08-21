# Input format (version 1)

The input of the diagram generator is a *set system*: a family of named sets
over named elements. It is written as YAML; since YAML is a superset of JSON,
JSON files are accepted by the same loader.

## Example

```yaml
name: languages
sets:
  compiled: [c, cpp, rust, java]
  gc: [java, go, python]
  scripting: [python, js]
```

## Schema

| Key     | Required | Type                          | Meaning                          |
|---------|----------|-------------------------------|----------------------------------|
| `name`  | no       | string                        | Diagram title.                   |
| `sets`  | yes      | mapping: string → string list | Each entry is one set with its elements. |
| `links` | no       | mapping: string → string      | URL per set or element name. Set links attach to the set's border label, element links make the element's whole box clickable. |
| `labels` | no      | mapping: string → string      | Display label per set or element name. May contain newlines (quoted `"…\n…"` or a `\|-` block scalar) for multi-line labels; the name itself stays the identity used in `sets` and `links`. |

Rules, all violations are hard errors:

- The top level must be a mapping and may contain only the keys above.
- `sets` must contain at least one set.
- Set names and elements must be strings. Quote values YAML would otherwise
  read as numbers or booleans (e.g. `"42"`, `"yes"`).
- An element may not be listed twice within the same set (typo protection).
  Listing the same element in several sets is the whole point and, of course,
  allowed.
- Duplicate keys anywhere in the document are rejected (YAML parsers would
  otherwise silently keep only the last one).
- Every `links` or `labels` key must name an existing set or element; a key
  naming *both* a set and an element is rejected (the flat mapping cannot
  tell which one is meant — rename one of them). Values must be non-empty
  strings; link schemes are not restricted (relative URLs and `mailto:` are
  fine).

A set with no elements is allowed and written as `myset: []` (or an empty
value: `myset:`).

## Semantics

The set system is interpreted as a formal context: elements are objects, set
names are attributes. All derived notions used by the layout algorithms of
[Dürrschnabel & Priss (2024)](https://arxiv.org/abs/2403.03801) — the
containment order, its order dimension, and the non-empty zones — are computed
from this context and are not part of the input.

Elements outside all sets cannot be expressed (they would be invisible in the
diagram anyway); the outer zone is implicit.
