"""Reading projections for explicit retained text formats; original bytes stay bound."""
import csv
import io
import json
import re
import tomllib

from cvw_app.renderer_nodes import _node, _finalize_structure, _heading_contexts, project_visible_text


def _book(nodes, outline):
    def normalize(node):
        if node["type"] != "preformatted":
            node["text"] = project_visible_text(node["text"])
        for child in node.get("children", []):
            normalize(child)
    for node in nodes:
        normalize(node)
    outline = [{**entry, "label": project_visible_text(entry["label"])} for entry in outline]
    return _finalize_structure("exact-text", nodes, outline, _heading_contexts(nodes, outline))


def render_structured_text(media_type, exact):
    nodes, outline = [], []

    def heading(label, location):
        nodes.append(_node("heading", label, level=2, location=location))
        outline.append(dict(location=location, label=label, level=2))

    if media_type == "application/x-ndjson":
        try:
            rows = [(number, json.loads(line)) for number, line in enumerate(exact.splitlines(), 1) if line.strip()]
        except json.JSONDecodeError:
            return None
        if not rows or any(not isinstance(row, dict) or set(row) != {"term", "definitions"}
                           or not isinstance(row["term"], str) or not row["term"].strip()
                           or not isinstance(row["definitions"], list) or not row["definitions"]
                           or any(not isinstance(text, str) for text in row["definitions"]) for _, row in rows):
            return None
        for number, row in rows:
            heading(row["term"], f"line-{number}")
            nodes.extend(_node("paragraph", text) for text in row["definitions"])
        return _book(nodes, outline)
    if media_type == "application/toml":
        try:
            data = tomllib.loads(exact)
        except tomllib.TOMLDecodeError:
            return None
        rows = data.get("commentary")
        if set(data) != {"commentary"} or not isinstance(rows, list) or not rows or any(
            not isinstance(row, dict) or not isinstance(row.get("quote"), str) for row in rows
        ):
            return None
        for number, row in enumerate(rows, 1):
            heading(row.get("source_title") or f"Quotation {number}", f"commentary-{number}")
            nodes.append(_node("paragraph", row["quote"]))
            fields = [_node("paragraph", f"{key.replace('_', ' ').capitalize()}: {value}")
                      for key, value in row.items() if key not in {"quote", "source_title"}]
            if fields:
                nodes.append(_node("details", "Source details", children=fields))
        return _book(nodes, outline)
    if media_type in {"text/csv", "text/tab-separated-values"}:
        try:
            if media_type == "text/csv" and exact.removeprefix('\ufeff').startswith('Title,"Full text",'):
                # The sealed viewer cannot import build tools; keep this reader identical to build/tei/hymnary_csv.py.
                from cvw_app.hymnary_csv import read_rows
                rows = [[field.value for field in row.fields] for row in read_rows(exact.encode('utf8'))]
            else:
                rows = list(csv.reader(io.StringIO(exact, newline=""), delimiter="," if media_type == "text/csv" else "\t", strict=True))
        except (csv.Error, ValueError):
            return None
        if len(rows) < 2 or not rows[0] or any(len(row) != len(rows[0]) for row in rows):
            return None
        # Hymnary's explicit title/text columns are books, not spreadsheet cells.
        if rows[0][:2] == ["Title", "Full text"]:
            for number, row in enumerate(rows[1:], 2):
                heading(row[0] or f"Hymn {number - 1}", f"row-{number}")
                text=re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]',lambda match:f"[source control U+{ord(match.group()):04X}]",row[1])
                nodes.append(_node("preformatted", text))
                nodes.append(_node("details", "Hymn details", children=[_node("paragraph", f"{key}: {value}") for key, value in zip(rows[0][2:], row[2:], strict=True)]))
            return _book(nodes, outline)
        cells = [_node("table-row", "", children=[_node("table-header" if index == 0 else "table-cell", text, **({"scope": "col"} if index == 0 else {})) for text in row]) for index, row in enumerate(rows)]
        return _book([_node("table", "", children=cells)], [])
    if media_type == "text/x-usfm":
        metadata = []
        for number, line in enumerate(exact.splitlines(), 1):
            match = re.match(r"^\\([a-z0-9]+)\s*(.*)$", line)
            if not match:
                if line.strip():
                    nodes.append(_node("paragraph", line))
                continue
            marker, value = match.groups()
            if marker in {"id", "ide", "h", "toc1", "toc2", "toc3", "usfm", "rem"}:
                metadata.append(_node("paragraph", f"{marker}: {value}"))
            elif marker == "c":
                heading(f"Chapter {value}", f"line-{number}")
            elif marker in {"mt", "mt1", "mt2", "s", "s1", "s2", "s3", "ms", "ms1"} and value.strip():
                heading(value, f"line-{number}")
            elif marker in {"v", "p", "m", "q", "q1", "q2", "q3", "pi", "pi1", "b", "nb", "r", "d", "ip", "imt", "imt1", "cl", "ca", "cp"}:
                if value.strip():
                    # shortcut: Unmapped inline markers stay literal; add a complete source-backed inline projection when needed.
                    nodes.append(_node("paragraph", value))
            else:
                nodes.append(_node("preformatted", line))
        if metadata:
            nodes.insert(0, _node("details", "About this source", children=metadata))
        return _book(nodes, outline) if nodes else None
    return None
