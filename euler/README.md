# euler-diagrams

Generator of rectangular Euler diagrams, based on
[Dürrschnabel & Priss: *Realizability of Rectangular Euler Diagrams* (2024)](https://arxiv.org/abs/2403.03801).

Status: the input format, the two-dimensional layout algorithm (`Euler2D`)
and an SVG renderer are implemented.

## Usage

```bash
python -m euler_diagrams examples/europe.yaml -o europe.svg
```

writes an SVG rendering ('-' for stdout), or reports that the set system has
no rectangular Euler diagram. Without `-o`, a plain-text layout summary is
printed instead. Programmatically, use `euler_diagrams.layout_2d(system)`,
which returns a `Layout` or raises `NotRealizableError`, and
`euler_diagrams.render_svg(layout)`.

The SVG has a transparent background and is cropped exactly to its content
(the viewBox is the bounding box of borders, labels, and boxes — no outer
margin). It adapts to light and dark mode and colors sets with a fixed,
colorblind-validated categorical palette; every set is labeled with text
centered on its border — the border line is structurally interrupted under
the label — and every element is drawn as a box with its name centered
inside. Labels sit on the top edge, sliding along it to avoid member boxes
and other labels (crossing a foreign border line is fine — the pill
interrupts it visually); only when every top position would cover a member
box or another label may a label fall to the bottom edge. At most 8 sets can
be rendered (fixed palette slots; hues are never generated). Every
rectangle edge gets its own inset step so that no two parallel border lines
ever coincide or touch (a contained rectangle's edge always sits deeper
than its container's on a shared grid line). Pixel coordinates come from a
per-axis constraint-graph longest-path pass (VLSI-style one-dimensional
compaction): each row and column is exactly as large as its content —
member boxes, crossing borders, label widths — requires, while every member
box keeps a fixed clearance to every border, so membership stays visually
exact. Elements sharing a zone flow into a small row-major grid whose
column count is chosen automatically (exhaustive search over all groups
when feasible, hill-climbing otherwise) to minimize the rendered diagram's
total area.

## Algorithm

The pipeline follows the paper's `Euler2D`: the set system is clarified into
a formal context, its *extended Euler-poset* is built, and a width-four
realizer is searched — one exists if and only if the diagram does (an
NP-complete question; it is decided exactly by a SAT encoding with symmetry
breaking instead of the paper's coloring heuristic). Two linear extensions
per axis are then scanned into rectangle boundaries and element points.
Because the scan gives every element a private row and column, the raw
diagram is a sparse permutation-like scatter; a lossless compaction pass
then collapses, per axis, adjacent element positions with no boundary
between them (they lie in exactly the same intervals) and adjacent
boundaries with no element between them, removing all structurally empty
rows and columns. The realizer itself is chosen for compactness: a MaxSAT
pass (RC2) picks, among all valid realizers, one that never breaks a
non-incidence on both axes when one axis suffices and prefers breaking on
the y-axis — extra rows are visually cheaper than extra columns.

Known limitations:

- Empty sets are rejected (the point-containment formalism cannot place an
  empty rectangle meaningfully).
- Sets with identical elements get identical rectangles, elements with
  identical memberships identical points; renderers must offset them.
- Two disjoint sets may be drawn as overlapping rectangles when no element
  witnesses the overlap — the paper's diagram definition constrains only
  point containment.

## Input format

Diagrams are described as YAML (or JSON) set systems, see
[docs/input-format.md](docs/input-format.md) and
[examples/languages.yaml](examples/languages.yaml):

```yaml
name: languages
sets:
  compiled: [c, cpp, rust, java]
  gc: [java, go, python]
  scripting: [python, js]
links:
  gc: https://en.wikipedia.org/wiki/Garbage_collection_(computer_science)
  rust: https://www.rust-lang.org/
```

The optional `links` mapping attaches a URL to any set or element by name:
a set link lives on its border label, an element link makes the element's
whole box clickable (rendered as native SVG `<a>` anchors, with a hover
affordance). Linked labels carry a tiny external-link arrow after the text —
in the set's color on labels, in muted ink inside member boxes.

The optional `labels` mapping overrides the displayed label of any set or
element by name; newlines in the value (quoted `"…\n…"` or a `|-` block
scalar) render as multi-line labels, with boxes, pills, and spacing sized
accordingly. The name itself stays the identity used in `sets` and `links`.

## Development

```bash
pip install -e '.[dev]'
pytest
```
