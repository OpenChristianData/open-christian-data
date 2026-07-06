"""Build index.md -- a human-readable catalogue of every work in data/.

Output: index.md at repo root, organized by category.

Deduplication: files sharing the same meta.id within the same top-level
category represent a single work split across Bible books or volumes.
They collapse to one entry; file_count > 1 is noted in the table.

Excluded:
  - data/authors/        (author registry, not works)
  - files with rendering_id at top level (NSH OCR pipeline data)
  - files where meta.title == 'Fixture Work' (test fixtures)
  - _manifest.json and catalog.json (internal bookkeeping)
"""

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
OUT = ROOT / "index.md"

CATEGORY_LABELS = {
    "bible-text": "Bible Text",
    "catechisms": "Catechisms",
    "church-fathers": "Church Fathers",
    "commentaries": "Commentaries",
    "devotionals": "Devotionals",
    "doctrinal-documents": "Doctrinal Documents",
    "hymns": "Hymns",
    "lexicon": "Lexicon",
    "prayers": "Prayers",
    "reference": "Reference",
    "sermons": "Sermons",
    "structured-text": "Structured Text",
    "topical-reference": "Topical Reference",
}


def _str(val):
    return val if isinstance(val, str) and val else None


def _int(val):
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _list(val):
    return val if isinstance(val, list) and val else None


def load_file(path: pathlib.Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"  WARN: {path.relative_to(ROOT)} -- JSON error: {e}", file=sys.stderr)
        return None


def is_pipeline_data(raw: dict) -> bool:
    return "rendering_id" in raw


def is_fixture(meta: dict) -> bool:
    return meta.get("title") == "Fixture Work"


def entry_from_meta(meta: dict, category: str, path: pathlib.Path, file_count: int) -> dict:
    slug = path.stem
    title = _str(meta.get("title")) or _str(meta.get("author")) or slug
    tradition = _list(meta.get("tradition"))
    return {
        "id": _str(meta.get("id")) or slug,
        "title": title,
        "category": category,
        "file_count": file_count,
        "author": _str(meta.get("author")),
        "year": _int(meta.get("original_publication_year")),
        "tradition": ", ".join(tradition) if tradition else None,
        "era": _str(meta.get("era")),
        "language": _str(meta.get("language")),
    }


def collect_entries():
    files = sorted(
        (f for f in DATA_DIR.rglob("*.json") if "authors" not in f.parts and f != OUT),
        key=lambda f: (f.relative_to(DATA_DIR).parts[0], f.stem),
    )

    groups: dict[tuple, dict] = {}
    skipped_pipeline = skipped_fixture = skipped_internal = 0

    for path in files:
        raw = load_file(path)
        if raw is None:
            continue

        category = path.relative_to(DATA_DIR).parts[0]

        if is_pipeline_data(raw):
            skipped_pipeline += 1
            continue

        if path.name.startswith("_") or path.name == "catalog.json":
            skipped_internal += 1
            continue

        meta = raw.get("meta") or {}

        if is_fixture(meta):
            skipped_fixture += 1
            continue

        mid = _str(meta.get("id"))

        group_key = (category, mid) if mid else (category, str(path))

        if group_key not in groups:
            groups[group_key] = {"meta": meta, "path": path, "file_count": 0, "category": category}
        groups[group_key]["file_count"] += 1

    entries = [
        entry_from_meta(g["meta"], g["category"], g["path"], g["file_count"])
        for g in groups.values()
    ]
    entries.sort(key=lambda e: (e["category"], e["title"] or ""))

    print(f"  Skipped: {skipped_pipeline} pipeline, {skipped_fixture} fixture, {skipped_internal} internal")
    return entries


def md_row(*cells):
    return "| " + " | ".join(str(c) if c is not None else "" for c in cells) + " |"


def write_md(entries: list[dict]):
    lines = []
    lines.append("# Open Christian Data -- Work Index")
    lines.append("")

    # Summary table
    from collections import Counter
    counts = Counter(e["category"] for e in entries)
    lines.append(f"**{len(entries)} works** across {len(counts)} categories.")
    lines.append("")
    lines.append("| Category | Works |")
    lines.append("|---|---|")
    for cat in sorted(counts):
        label = CATEGORY_LABELS.get(cat, cat)
        lines.append(f"| {label} | {counts[cat]} |")
    lines.append("")

    # Per-category sections
    from itertools import groupby
    for category, group in groupby(entries, key=lambda e: e["category"]):
        label = CATEGORY_LABELS.get(category, category)
        group = list(group)
        lines.append(f"## {label} ({len(group)})")
        lines.append("")

        # Decide columns based on what's populated in this category.
        # Suppress Author if it's always identical to Title (e.g. church-fathers schema).
        has_author = any(e["author"] for e in group) and not all(
            e["author"] == e["title"] for e in group
        )
        has_year = any(e["year"] for e in group)
        has_tradition = any(e["tradition"] for e in group)
        has_multifile = any(e["file_count"] > 1 for e in group)

        headers = ["Title"]
        if has_author:
            headers.append("Author")
        if has_year:
            headers.append("Year")
        if has_tradition:
            headers.append("Tradition")
        if has_multifile:
            headers.append("Files")

        lines.append("| " + " | ".join(headers) + " |")
        lines.append("|" + "|".join("---" for _ in headers) + "|")

        for e in group:
            title = e["title"] or e["id"]
            cells = [title]
            if has_author:
                cells.append(e["author"] or "")
            if has_year:
                cells.append(str(e["year"]) if e["year"] else "")
            if has_tradition:
                cells.append(e["tradition"] or "")
            if has_multifile:
                cells.append(str(e["file_count"]) if e["file_count"] > 1 else "")
            lines.append("| " + " | ".join(cells) + " |")

        lines.append("")

    OUT.write_text("\n".join(lines), encoding="utf-8")


def build():
    entries = collect_entries()
    write_md(entries)
    print(f"Wrote {len(entries)} entries to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    build()
