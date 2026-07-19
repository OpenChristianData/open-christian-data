"""Build index.md -- a human-readable catalog of recognized works in data/.

Output: index.md at repo root, organized by category.

Work identity and exclusions come from ``count_dataset_records.collect_work_catalog``
so this public index cannot drift from ``docs/WORK_CATALOG.md`` or the release count.
"""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
OUT = ROOT / "index.md"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from build.tools.count_dataset_records import collect_work_catalog  # noqa: E402

CATEGORY_LABELS = {
    "bible-text": "Bible Translations",
    "catechisms": "Catechisms",
    "church-fathers": "Church Fathers",
    "commentaries": "Commentaries",
    "devotionals": "Devotionals",
    "doctrinal-documents": "Doctrinal Documents",
    "hymns": "Hymns",
    "prayers": "Prayers",
    "reference": "Dictionaries and Encyclopedias",
    "sermons": "Sermons",
    "structured-text": "Books and Long-Form Works",
    "topical-reference": "Topical Bibles and Indexes",
}


def collect_entries():
    catalog = collect_work_catalog(DATA_DIR)
    entries = []
    for work in catalog.works:
        metadata = work["metadata_fields"]
        traditions = metadata.get("tradition", [])
        entries.append(
            {
                "id": work["work_id"],
                "title": work["title"],
                "category": work["category"],
                "file_count": work["file_count"],
                "author": work.get("author"),
                "year": work.get("publication_date"),
                "tradition": ", ".join(traditions) if traditions else None,
            }
        )
    entries.sort(key=lambda e: (e["category"], e["title"] or ""))
    skipped = catalog.summary.get("skipped", {})
    print(f"  Skipped by authoritative catalog rules: {sum(skipped.values())}")
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
