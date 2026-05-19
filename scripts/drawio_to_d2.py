#!/usr/bin/env python3
"""Convert draw.io (mxGraph) XML to D2 diagram source."""

from __future__ import annotations

import html
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def clean_html(s: str) -> str:
    s = html.unescape(s or "")
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)

    def link_repl(m: re.Match[str]) -> str:
        href, text = m.group(1), m.group(2)
        return f"[{text}]({href})"

    s = re.sub(
        r'<a\s+href=["\']([^"\']+)["\'][^>]*>([^<]*)</a>',
        link_repl,
        s,
        flags=re.I,
    )
    s = re.sub(r"<[^>]+>", "", s)
    s = (
        s.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )
    return s.strip()


def d2_escape_label(s: str) -> str:
    """Quote label for D2 if needed."""
    if not s:
        return '""'
    if "\n" in s:
        inner = s.replace("\\", "\\\\").replace('"', '\\"')
        return f'|md\n  {inner.replace(chr(10), chr(10) + "  ")}\n|'
    if re.search(r'[#|;\[\]{}]', s) or s.startswith("|"):
        return f'"{s.replace(chr(92), chr(92)*2).replace(chr(34), chr(92)+chr(34))}"'
    return s


def slug(text: str, used: set[str]) -> str:
    special = {"[]": "py_list_literal", "()": "py_tuple_literal"}
    if text in special:
        base = special[text]
    else:
        base = re.sub(r"[^a-zA-Z0-9]+", "_", text.lower())[:48].strip("_") or "node"
    s = base
    i = 2
    while s in used:
        s = f"{base}_{i}"
        i += 1
    used.add(s)
    return s


def is_orphan_label_node(value: str, style: str, nid: str, edges: list) -> bool:
    """Skip free-floating Yes/No captions that are not real decision nodes."""
    v = clean_html(value)
    if v not in ("Yes", "No"):
        return False
    if "rhombus" in style:
        return False
    connected = any(e["src"] == nid or e["tgt"] == nid for e in edges)
    return not connected


def node_shape(style: str) -> str | None:
    if "rhombus" in style:
        return "diamond"
    if "shape=process" in style:
        return "rectangle"
    return None


def parse_drawio(path: Path) -> tuple[dict, list, dict]:
    root = ET.parse(path).getroot()
    nodes: dict[str, dict] = {}

    for uo in root.iter("UserObject"):
        cid = uo.get("id")
        if not cid:
            continue
        style = ""
        for cell in uo:
            if cell.tag.endswith("mxCell"):
                style = cell.get("style", "")
        nodes[cid] = {
            "value": uo.get("label", ""),
            "style": style,
            "link": uo.get("link", ""),
        }

    for cell in root.iter("mxCell"):
        cid = cell.get("id")
        if cell.get("vertex") != "1" or cell.get("connectable") == "0":
            continue
        parent = cell.get("parent")
        if parent not in ("0", "1", None):
            continue
        if cid and cid not in nodes:
            nodes[cid] = {
                "value": cell.get("value") or "",
                "style": cell.get("style", ""),
                "link": "",
            }

    edges: list[dict] = []
    edge_labels: dict[str, str] = {}
    for cell in root.iter("mxCell"):
        cid = cell.get("id")
        if cell.get("edge") == "1":
            src, tgt = cell.get("source"), cell.get("target")
            style = cell.get("style", "")
            if src:
                edges.append(
                    {
                        "id": cid,
                        "src": src,
                        "tgt": tgt,
                        "cross": "endArrow=cross" in style,
                    }
                )
        parent = cell.get("parent")
        if parent and cell.get("connectable") == "0":
            val = cell.get("value") or ""
            if val and parent:
                edge_labels[parent] = clean_html(val)

    return nodes, edges, edge_labels


def emit_d2(nodes: dict, edges: list, edge_labels: dict) -> str:
    used_ids: set[str] = set()
    id_map: dict[str, str] = {}
    labels: dict[str, str] = {}

    for nid, n in nodes.items():
        v = clean_html(n["value"])
        if not v:
            continue
        if is_orphan_label_node(n["value"], n.get("style", ""), nid, edges):
            continue
        first_line = v.split("\n")[0][:40]
        id_map[nid] = slug(v if v in ("[]", "()") else first_line, used_ids)
        labels[id_map[nid]] = v

    # Edges without target (e.g. "not in Python stdlib" strikethroughs)
    for e in edges:
        if e.get("tgt") or e["src"] not in id_map:
            continue
        lbl = edge_labels.get(e["id"], "N/A")
        note_id = slug(f"note_{lbl[:24]}", used_ids)
        id_map[e["id"] + "_note"] = note_id
        labels[note_id] = lbl

    lines: list[str] = [
        "# Collection Decision Tree",
        "# Converted from draw.io — edit layout in D2 as needed.",
        "",
        "direction: down",
        "",
    ]

    for d2_id, label in sorted(labels.items(), key=lambda x: x[0]):
        shape = None
        link = None
        for nid, mapped in id_map.items():
            if mapped != d2_id:
                continue
            n = nodes[nid]
            shape = node_shape(n.get("style", ""))
            link = n.get("link") or None
            break

        lbl = d2_escape_label(label)
        lines.append(f"{d2_id}: {lbl}")
        if shape:
            lines.append(f"{d2_id}.shape: {shape}")
        if link:
            lines.append(f"{d2_id}.link: {link}")
        lines.append("")

    lines.append("# --- edges ---")
    lines.append("")
    seen_edges: set[tuple[str, str, str]] = set()
    for e in edges:
        src = e["src"]
        tgt = e.get("tgt")
        if src not in id_map:
            continue
        s_id = id_map[src]
        if not tgt:
            note_key = e["id"] + "_note"
            if note_key not in id_map:
                continue
            t_id = id_map[note_key]
            lbl = edge_labels.get(e["id"], "")
            key = (s_id, t_id, lbl)
            if key in seen_edges:
                continue
            seen_edges.add(key)
            if lbl:
                el = d2_escape_label(lbl)
                lines.append(f"{s_id} -> {t_id}: {el}")
            else:
                lines.append(f"{s_id} -> {t_id}")
            continue
        if tgt not in id_map:
            continue
        s_id, t_id = id_map[src], id_map[tgt]
        lbl = edge_labels.get(e["id"], "")
        key = (s_id, t_id, lbl)
        if key in seen_edges:
            continue
        seen_edges.add(key)
        if lbl:
            el = d2_escape_label(lbl)
            lines.append(f"{s_id} -> {t_id}: {el}")
        else:
            lines.append(f"{s_id} -> {t_id}")

    return "\n".join(lines) + "\n"


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: drawio_to_d2.py <input.drawio.xml> [output.d2]", file=sys.stderr)
        return 1
    inp = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else inp.with_suffix("").with_suffix(".d2")
    if out.suffix != ".d2":
        out = out.with_name(out.stem + ".d2")

    nodes, edges, edge_labels = parse_drawio(inp)
    d2_src = emit_d2(nodes, edges, edge_labels)
    out.write_text(d2_src, encoding="utf-8")
    print(f"Wrote {out} ({len(nodes)} nodes, {len(edges)} edges)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
