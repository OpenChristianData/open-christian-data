from __future__ import annotations

import argparse
import html
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = REPO_ROOT / "data"
DEFAULT_JSON_OUT = REPO_ROOT / "reports" / "publish" / "work_catalog.json"
DEFAULT_MD_OUT = REPO_ROOT / "reports" / "publish" / "work_catalog.md"
DEFAULT_HTML_OUT = REPO_ROOT / "reports" / "publish" / "work_catalog.html"
NSH_REFERENCE_PREFIX = ("reference", "schaff", "encyclopedia", "1908-1914")
OFFICIAL_TITLE_REVIEW_RESOURCE_IDS = {
    "calvin",
    "matthew-henry-complete",
}

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

METADATA_LABELS = {
    "id": "Resource ID",
    "title": "Title",
    "author": "Author",
    "contributors": "Contributors",
    "language": "Language",
    "tradition": "Tradition",
    "tradition_notes": "Tradition notes",
    "license": "Licence",
    "schema_type": "Schema type",
    "schema_version": "Schema version",
    "completeness": "Completeness",
    "original_publication_year": "Original publication year",
    "publication_year": "Publication year",
    "publication_date": "Publication date",
    "copyright_year": "Copyright year",
    "provenance.source_url": "Source URL",
    "provenance.source_format": "Source format",
    "provenance.source_edition": "Source edition",
    "provenance.download_date": "Download date",
    "provenance.source_hash": "Source hash",
    "provenance.processing_method": "Processing method",
    "provenance.processing_script_version": "Processing script version",
    "provenance.processing_date": "Processing date",
    "provenance.notes": "Provenance notes",
}

METADATA_FIELD_ORDER = [
    "id",
    "title",
    "author",
    "contributors",
    "language",
    "tradition",
    "original_publication_year",
    "publication_year",
    "publication_date",
    "copyright_year",
    "license",
    "completeness",
    "provenance.source_edition",
    "provenance.source_url",
    "provenance.source_format",
    "provenance.download_date",
    "provenance.processing_date",
    "provenance.processing_method",
    "provenance.processing_script_version",
    "provenance.notes",
    "schema_type",
    "schema_version",
    "provenance.source_hash",
]

PUBLICATION_META_FIELDS = (
    "publication_date",
    "publication_year",
    "published",
    "published_year",
    "original_publication_year",
    "copyright_year",
)

PUBLICATION_PROVENANCE_FIELDS = (
    "publication_date",
    "publication_year",
    "source_publication_date",
    "source_publication_year",
)


@dataclass(frozen=True)
class WorkCatalog:
    summary: dict[str, Any]
    works: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "methodology": {
                "public_inventory_unit": (
                    "Recognized title-level work units: the title a reader, library, citation, "
                    "or source catalog would treat as the work present in the corpus. Exported "
                    "records, verses, dictionary entries, topics, Q&A pairs, chapters, and "
                    "quotations are subordinate units."
                ),
                "special_rules": [
                    "Files with the same category, title, and author are one work unit, even if split by volume.",
                    "Church Fathers verse-reference quotations are one source-collection unit, not one work per quoted author.",
                    "The historical-language lexicon is an auxiliary project tool, not a work or content category.",
                    "NSH OCR/reconciliation artifacts under data/reference/schaff/encyclopedia/1908-1914 are out of dataset-side public inventory scope.",
                    "Rows with missing or slug-derived titles are kept but flagged for bibliographic review.",
                ],
            },
            "summary": self.summary,
            "works": self.works,
        }


def catalog_identity_snapshot(catalog: WorkCatalog) -> dict[str, Any]:
    """Return the compact machine-readable identity surface for catalog consumers."""

    return {
        "identity": "work-catalog-identity-v1",
        "works": [
            {
                "author": work.get("author") or "",
                "category": work["category"],
                "category_label": work["category_label"],
                "file_count": work["file_count"],
                "resource_ids": work["resource_ids"],
                "schema_types": work["schema_types"],
                "source_paths": work["source_paths"],
                "title": work["title"],
                "work_id": work["work_id"],
            }
            for work in catalog.works
        ],
    }


def serialize_catalog_identity(catalog: WorkCatalog) -> bytes:
    """Serialize the compact identity surface deterministically with LF endings."""

    return (
        json.dumps(
            catalog_identity_snapshot(catalog),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _load_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _resource_paths(data_root: Path) -> Iterable[Path]:
    for path in sorted(data_root.rglob("*.json")):
        rel_parts = path.relative_to(data_root).parts
        if not rel_parts:
            continue
        if rel_parts[0] in {"authors", "lexicon"}:
            continue
        if rel_parts[: len(NSH_REFERENCE_PREFIX)] == NSH_REFERENCE_PREFIX:
            continue
        if path.name.startswith("_") or path.name == "catalog.json":
            continue
        yield path


def _clean_str(value: Any) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped
    return None


def _normal_key(value: Any) -> str:
    text = _clean_str(value)
    if text is None:
        return ""
    return " ".join(text.casefold().replace("_", " ").replace("-", " ").split())


def _identity_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug or "unknown"


def _first_text(*values: Any) -> str | None:
    for value in values:
        text = _clean_str(value)
        if text is not None:
            return text
    return None


def _data_payload(record: Mapping[str, Any]) -> Any:
    if "data" in record:
        return record.get("data")
    if "blocks" in record:
        return record.get("blocks")
    return None


def _top_level_count(payload: Any) -> int:
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        return 1
    return 0


def _leaf_count(value: Any) -> int:
    if isinstance(value, list):
        primitive_text = sum(1 for item in value if _clean_str(item) is not None)
        return primitive_text + sum(_leaf_count(item) for item in value if isinstance(item, (dict, list)))
    if not isinstance(value, dict):
        return 0

    count = 0
    direct_text_keys = {"text", "commentary_text", "verse_text", "question", "answer", "quote", "term"}
    for key in direct_text_keys:
        if _clean_str(value.get(key)) is not None:
            count += 1
    for key, item in value.items():
        if (
            key not in direct_text_keys
            and isinstance(item, str)
            and key.endswith("_text")
            and _clean_str(item) is not None
        ):
            count += 1
    for child_key in ("data", "sections", "children", "units", "blocks", "entries", "subtopics", "content_blocks"):
        child = value.get(child_key)
        if child is not None:
            count += _leaf_count(child)
    return count


def _legacy_hf_row_count(schema_type: str | None, payload: Any) -> int:
    if isinstance(payload, list):
        return len(payload)
    if not isinstance(payload, dict):
        return 0
    if schema_type == "structured_text":
        return _count_structured_text_blocks(payload)
    if schema_type == "doctrinal_document":
        return _count_doctrinal_document_leaves(payload)
    return 1


def _count_structured_text_blocks(data: Mapping[str, Any]) -> int:
    def walk(section: Mapping[str, Any]) -> int:
        count = len(section.get("content_blocks") or [])
        for child in section.get("children") or []:
            if isinstance(child, Mapping):
                count += walk(child)
        return count

    return sum(walk(section) for section in data.get("sections") or [] if isinstance(section, Mapping))


def _count_doctrinal_document_leaves(data: Mapping[str, Any]) -> int:
    def walk(unit: Mapping[str, Any]) -> int:
        children = unit.get("children") or []
        if children:
            return sum(walk(child) for child in children if isinstance(child, Mapping))
        return 1 if _clean_str(unit.get("content")) is not None else 0

    return sum(walk(unit) for unit in data.get("units") or [] if isinstance(unit, Mapping))


def _metadata_fields(meta: Mapping[str, Any]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for key, value in meta.items():
        if key == "provenance" and isinstance(value, Mapping):
            for subkey, subvalue in value.items():
                text = _serialise_metadata_value(subvalue)
                if text is not None:
                    fields[f"provenance.{subkey}"] = text
            continue
        text = _serialise_metadata_value(value)
        if text is not None:
            fields[key] = text
    return fields


def _serialise_metadata_value(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    if isinstance(value, list):
        items = [_serialise_metadata_value(item) or "" for item in value if item not in (None, "")]
        items = [item for item in items if item]
        return ", ".join(items) if items else None
    if isinstance(value, Mapping):
        labelled = []
        for key, item in sorted(value.items()):
            text = _serialise_metadata_value(item)
            if text is not None:
                labelled.append(f"{key}: {text}")
        return "; ".join(labelled) if labelled else None
    return str(value)


def _publication_date_from_metas(
    category: str,
    metas: Iterable[Mapping[str, Any]],
    hymn_summary: Mapping[str, Any] | None,
) -> str:
    if category == "hymns" and hymn_summary is not None:
        year_range = hymn_summary.get("hymnal_year_range")
        if isinstance(year_range, str) and year_range:
            return f"Hymnal publication years {year_range}"

    explicit_values: list[str] = []
    source_edition_years: list[int] = []
    for meta in metas:
        for field in PUBLICATION_META_FIELDS:
            value = _metadata_text(meta.get(field))
            if value is not None and value not in explicit_values:
                explicit_values.append(value)
        provenance = meta.get("provenance") if isinstance(meta.get("provenance"), Mapping) else {}
        for field in PUBLICATION_PROVENANCE_FIELDS:
            value = _metadata_text(provenance.get(field))
            if value is not None and value not in explicit_values:
                explicit_values.append(value)
        source_edition = _clean_str(provenance.get("source_edition"))
        if source_edition is not None:
            source_edition_years.extend(_years_in_text(source_edition))
    if explicit_values:
        return _compact_values(explicit_values)
    if source_edition_years:
        return _format_years(source_edition_years)
    return ""


def _metadata_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, (str, int, float, bool)):
        text = str(value).strip()
        return text if text else None
    return _serialise_metadata_value(value)


def _years_in_text(text: str) -> list[int]:
    years: list[int] = []
    for match in re.findall(r"\b(1[0-9]{3}|20[0-2][0-9])\b", text):
        year = int(match)
        if year <= 2026:
            years.append(year)
    return years


def _format_years(years: Iterable[int]) -> str:
    unique = sorted(set(years))
    if not unique:
        return ""
    if len(unique) == 1:
        return str(unique[0])
    return f"{unique[0]}-{unique[-1]}"


def _compact_values(values: Iterable[str]) -> str:
    unique = []
    for value in values:
        if value not in unique:
            unique.append(value)
    if len(unique) <= 3:
        return "; ".join(unique)
    return f"{unique[0]}; {unique[1]}; {unique[2]}; +{len(unique) - 3} more"


def _hymn_summary(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, list):
        return None

    hymnal_years = [item.get("hymnal_year") for item in payload if isinstance(item, Mapping)]
    hymnal_years = [year for year in hymnal_years if isinstance(year, int)]
    written_years = [item.get("year_written") for item in payload if isinstance(item, Mapping)]
    written_years = [year for year in written_years if isinstance(year, int)]
    hymnal_titles = {
        title
        for item in payload
        if isinstance(item, Mapping)
        for title in [_clean_str(item.get("hymnal_title"))]
        if title is not None
    }
    languages = {
        language
        for item in payload
        if isinstance(item, Mapping)
        for language in [_clean_str(item.get("language"))]
        if language is not None
    }
    return {
        "hymn_entries": len(payload),
        "hymnal_year_known": len(hymnal_years),
        "hymnal_year_range": _format_years(hymnal_years),
        "year_written_known": len(written_years),
        "year_written_range": _format_years(written_years),
        "hymnal_titles": len(hymnal_titles),
        "languages": sorted(languages),
    }


def _combine_hymn_summaries(summaries: Iterable[Mapping[str, Any]]) -> dict[str, Any] | None:
    summaries = list(summaries)
    if not summaries:
        return None

    hymnal_years: list[int] = []
    written_years: list[int] = []
    languages: set[str] = set()
    for summary in summaries:
        hymnal_range = _clean_str(summary.get("hymnal_year_range"))
        if hymnal_range is not None:
            hymnal_years.extend(_years_in_text(hymnal_range))
        written_range = _clean_str(summary.get("year_written_range"))
        if written_range is not None:
            written_years.extend(_years_in_text(written_range))
        for language in summary.get("languages") or []:
            if isinstance(language, str):
                languages.add(language)

    return {
        "hymn_entries": sum(int(summary.get("hymn_entries") or 0) for summary in summaries),
        "hymnal_year_known": sum(int(summary.get("hymnal_year_known") or 0) for summary in summaries),
        "hymnal_year_range": _format_years(hymnal_years),
        "year_written_known": sum(int(summary.get("year_written_known") or 0) for summary in summaries),
        "year_written_range": _format_years(written_years),
        "hymnal_titles": sum(int(summary.get("hymnal_titles") or 0) for summary in summaries),
        "languages": sorted(languages),
    }


def _is_fixture_or_pipeline(record: Mapping[str, Any], meta: Mapping[str, Any]) -> bool:
    return "rendering_id" in record or meta.get("title") == "Fixture Work"


def _group_key(category: str, meta: Mapping[str, Any], path: Path) -> tuple[str, str, str, str]:
    if category == "church-fathers":
        return (category, "church-fathers-quotations", "", "")
    title = _first_text(meta.get("title"))
    author = _first_text(meta.get("author"))
    if title is not None:
        return (category, _normal_key(title), _normal_key(author), "")
    resource_id = _first_text(meta.get("id"), path.stem) or path.stem
    return (category, "", "", resource_id)


def _public_title(category: str, metas: list[Mapping[str, Any]], fallback_id: str) -> str:
    if category == "church-fathers":
        return "Church Fathers verse-reference quotations"
    for meta in metas:
        title = _clean_str(meta.get("title"))
        if title is not None:
            return title
    return fallback_id


def _public_author(category: str, authors: set[str]) -> str | None:
    if category == "church-fathers":
        return "Various authors"
    if not authors:
        return None
    if len(authors) == 1:
        return next(iter(authors))
    return "Various contributors"


def _audit_flags(category: str, title: str, author: str | None, metas: list[Mapping[str, Any]]) -> list[str]:
    flags: set[str] = set()
    if category != "church-fathers":
        if not any(_clean_str(meta.get("title")) for meta in metas):
            flags.add("missing_title")
        if author is None:
            flags.add("missing_author")
    if title in {str(meta.get("id")) for meta in metas if meta.get("id")}:
        flags.add("title_looks_like_internal_id")
    if "missing_title" in flags or "title_looks_like_internal_id" in flags:
        flags.add("needs_bibliographic_review")
    if any(str(meta.get("id")) in OFFICIAL_TITLE_REVIEW_RESOURCE_IDS for meta in metas):
        flags.add("official_title_unconfirmed")
        flags.add("needs_bibliographic_review")
    if not any(_clean_str((meta.get("provenance") or {}).get("source_edition")) for meta in metas):
        flags.add("missing_source_edition")
    return sorted(flags)


def collect_work_catalog(data_root: Path = DATA_ROOT) -> WorkCatalog:
    groups: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    skipped = Counter()

    for path in _resource_paths(data_root):
        raw = _load_json(path)
        if not isinstance(raw, Mapping):
            skipped["invalid_json_or_shape"] += 1
            continue
        meta = raw.get("meta") if isinstance(raw.get("meta"), Mapping) else {}
        if _is_fixture_or_pipeline(raw, meta):
            skipped["fixture_or_pipeline"] += 1
            continue

        rel = path.relative_to(data_root)
        category = "topical-reference" if meta.get("schema_type") == "topical_reference" else rel.parts[0]
        key = _group_key(category, meta, path)
        group = groups.setdefault(
            key,
            {
                "category": category,
                "paths": [],
                "metas": [],
                "metadata_fields": defaultdict(list),
                "resource_ids": set(),
                "authors": set(),
                "schema_types": set(),
                "hymn_summaries": [],
                "top_level_records": 0,
                "leaf_records": 0,
                "legacy_hf_export_records": 0,
            },
        )
        group["paths"].append(rel.as_posix())
        group["metas"].append(meta)
        resource_id = _clean_str(meta.get("id"))
        if resource_id is not None:
            group["resource_ids"].add(resource_id)
        author = _clean_str(meta.get("author"))
        if author is not None:
            group["authors"].add(author)
        schema_type = _clean_str(meta.get("schema_type"))
        if schema_type is not None:
            group["schema_types"].add(schema_type)
        payload = _data_payload(raw)
        group["top_level_records"] += _top_level_count(payload)
        group["leaf_records"] += _leaf_count(payload)
        group["legacy_hf_export_records"] += _legacy_hf_row_count(schema_type, payload)
        if category == "hymns":
            hymn_summary = _hymn_summary(payload)
            if hymn_summary is not None:
                group["hymn_summaries"].append(hymn_summary)
        for field, value in _metadata_fields(meta).items():
            if value not in group["metadata_fields"][field]:
                group["metadata_fields"][field].append(value)

    works: list[dict[str, Any]] = []
    for key, group in groups.items():
        category = group["category"]
        resource_ids = sorted(group["resource_ids"])
        fallback_id = resource_ids[0] if resource_ids else key[-1]
        work_id = "church-fathers-quotations" if category == "church-fathers" else fallback_id
        title = _public_title(category, group["metas"], fallback_id)
        author = _public_author(category, group["authors"])
        hymn_summary = _combine_hymn_summaries(group["hymn_summaries"])
        flags = _audit_flags(category, title, author, group["metas"])
        works.append(
            {
                "work_id": work_id,
                "category": category,
                "category_label": CATEGORY_LABELS.get(category, category),
                "title": title,
                "author": author,
                "publication_date": _publication_date_from_metas(category, group["metas"], hymn_summary),
                "author_count": len(group["authors"]),
                "schema_types": sorted(group["schema_types"]),
                "resource_ids": resource_ids,
                "source_paths": sorted(group["paths"]),
                "file_count": len(group["paths"]),
                "top_level_records": group["top_level_records"],
                "leaf_records": group["leaf_records"],
                "legacy_hf_export_records": group["legacy_hf_export_records"],
                "hymn_summary": hymn_summary,
                "metadata_fields": {
                    field: sorted(values)
                    for field, values in sorted(group["metadata_fields"].items())
                },
                "audit_flags": flags,
            }
        )

    work_id_counts = Counter(work["work_id"] for work in works)
    for work in works:
        if work_id_counts[work["work_id"]] > 1:
            authority = work["author"] or work["title"]
            work["work_id"] = f"{work['work_id']}--{_identity_slug(authority)}"
    resolved_work_ids = [work["work_id"] for work in works]
    if len(resolved_work_ids) != len(set(resolved_work_ids)):
        raise ValueError("work catalog cannot derive unique work identities")

    works.sort(key=lambda work: (work["category_label"], work["title"], work["work_id"]))
    category_counts = Counter(work["category"] for work in works)
    category_records = Counter()
    category_leaf_records = Counter()
    category_files = Counter()
    legacy_hf_records = Counter()
    for work in works:
        category = work["category"]
        category_records[category] += work["top_level_records"]
        category_leaf_records[category] += work["leaf_records"]
        category_files[category] += work["file_count"]
        for schema_type in work["schema_types"]:
            legacy_hf_records[schema_type] += work["legacy_hf_export_records"]
    work_authors = {
        work["author"]
        for work in works
        if isinstance(work.get("author"), str) and work["author"] not in {"Various authors", "Various contributors"}
    }
    source_author_labels: set[str] = set()
    for work in works:
        for value in work["metadata_fields"].get("author", []):
            if value not in {"Various authors", "Various contributors"}:
                source_author_labels.add(value)
    summary = {
        "work_units": len(works),
        "authors": len(work_authors),
        "source_author_labels": len(source_author_labels),
        "files": sum(work["file_count"] for work in works),
        "top_level_records": sum(work["top_level_records"] for work in works),
        "leaf_records": sum(work["leaf_records"] for work in works),
        "legacy_hf_export_records": sum(work["legacy_hf_export_records"] for work in works),
        "legacy_hf_export_records_by_schema": {
            schema_type: legacy_hf_records[schema_type] for schema_type in sorted(legacy_hf_records)
        },
        "works_by_category": {category: category_counts[category] for category in sorted(category_counts)},
        "files_by_category": {category: category_files[category] for category in sorted(category_files)},
        "top_level_records_by_category": {
            category: category_records[category] for category in sorted(category_records)
        },
        "leaf_records_by_category": {
            category: category_leaf_records[category] for category in sorted(category_leaf_records)
        },
        "works_with_audit_flags": sum(1 for work in works if work["audit_flags"]),
        "skipped": dict(sorted(skipped.items())),
    }
    return WorkCatalog(summary=summary, works=works)


def render_catalog_markdown(catalog: WorkCatalog) -> str:
    payload = catalog.to_dict()
    summary = payload["summary"]
    lines = [
        "# Open Christian Data Work Catalog",
        "",
        "This catalog counts the public inventory by recognized title-level work units. Exported records are counted separately.",
        "",
        "## Summary",
        "",
        f"- Work units: {summary['work_units']}",
        f"- Authors: {summary['authors']}",
        f"- Source files: {summary['files']}",
        f"- Top-level export/source records: {summary['top_level_records']}",
        f"- Legacy HuggingFace JSONL rows: {summary['legacy_hf_export_records']}",
        f"- Leaf text units: {summary['leaf_records']}",
        f"- Work units with audit flags: {summary['works_with_audit_flags']}",
        "",
        "## Categories",
        "",
        "| Category | Work units |",
        "|---|---:|",
    ]
    for category, count in summary["works_by_category"].items():
        lines.append(f"| {CATEGORY_LABELS.get(category, category)} | {count} |")
    lines.extend(
        [
            "",
            "## Work Metadata Audit",
            "",
            "| Category | Title | Author | Publication date | Files | Records | Audit flags |",
            "|---|---|---|---|---:|---:|---|",
        ]
    )
    for work in catalog.works:
        lines.append(
            "| "
            + " | ".join(
                [
                    _md_cell(work["category_label"]),
                    _md_cell(work["title"]),
                    _md_cell(work.get("author") or ""),
                    _md_cell(work.get("publication_date") or ""),
                    str(work["file_count"]),
                    str(work["top_level_records"]),
                    _md_cell(", ".join(work["audit_flags"])),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def _md_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def render_catalog_html(catalog: WorkCatalog) -> str:
    summary = catalog.summary
    rows = []
    for work in catalog.works:
        flags = ", ".join(work["audit_flags"])
        rows.append(
            "<tr>"
            f"<td>{_h(work['category_label'])}</td>"
            f"<td>{_h(work['title'])}</td>"
            f"<td>{_h(work.get('author') or '')}</td>"
            f"<td>{_h(work.get('publication_date') or '')}</td>"
            f"<td>{work['file_count']}</td>"
            f"<td>{work['top_level_records']}</td>"
            f"<td>{work['leaf_records']}</td>"
            f"<td>{_h(flags)}</td>"
            f"<td>{_render_metadata_details(work)}</td>"
            "</tr>"
        )
    hymn_panel = _render_hymn_panel(catalog.works)
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>Open Christian Data work catalog</title>"
        "<style>"
        "body{font-family:system-ui,-apple-system,Segoe UI,sans-serif;margin:24px;color:#1f2933;background:#fafafa}"
        "h1{font-size:28px;margin-bottom:8px} .summary{display:flex;flex-wrap:wrap;gap:8px;margin:18px 0}"
        ".summary span{border:1px solid #c9d2dc;background:white;padding:8px 10px;border-radius:4px}"
        ".note{border-left:4px solid #577399;background:white;padding:12px 14px;margin:18px 0;max-width:980px}"
        "table{border-collapse:collapse;width:100%;background:white;font-size:14px}"
        "th,td{border:1px solid #d9e1e8;padding:7px;vertical-align:top;text-align:left}"
        "th{background:#edf2f7;position:sticky;top:0}"
        "dl.metadata{display:grid;grid-template-columns:minmax(150px,220px) minmax(260px,1fr);gap:4px 12px;margin:8px 0 0;max-width:780px}"
        "dl.metadata dt{font-weight:700;color:#334e68} dl.metadata dd{margin:0;overflow-wrap:anywhere}"
        "ul.compact{margin:0;padding-left:18px} .muted{color:#627d98}"
        "</style></head><body><main>"
        "<h1>Open Christian Data work catalog</h1>"
        "<p>Public inventory is counted by recognized title-level work units. Export rows and leaf text units are secondary technical counts.</p>"
        "<div class=\"summary\">"
        f"<span>Work units: <strong>{summary['work_units']}</strong></span>"
        f"<span>Authors: <strong>{summary['authors']}</strong></span>"
        f"<span>Files: <strong>{summary['files']}</strong></span>"
        f"<span>Top-level records: <strong>{summary['top_level_records']}</strong></span>"
        f"<span>HF JSONL rows: <strong>{summary['legacy_hf_export_records']}</strong></span>"
        f"<span>Leaf text units: <strong>{summary['leaf_records']}</strong></span>"
        f"<span>Flagged works: <strong>{summary['works_with_audit_flags']}</strong></span>"
        "</div>"
        f"{hymn_panel}"
        "<table><thead><tr><th>Category</th><th>Title</th><th>Author</th><th>Publication date</th><th>Files</th><th>Records</th><th>Leaf units</th><th>Audit flags</th><th>Metadata fields</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        "</main></body></html>\n"
    )


def _render_hymn_panel(works: Iterable[Mapping[str, Any]]) -> str:
    hymn_works = [work for work in works if work.get("category") == "hymns" and work.get("hymn_summary")]
    if not hymn_works:
        return ""
    panels = []
    for work in hymn_works:
        summary = work["hymn_summary"]
        panels.append(
            "<div class=\"note\">"
            f"<strong>Hymn collection coverage:</strong> {_h(work['title'])} contains "
            f"{_h(_format_number(summary['hymn_entries']))} hymn entries. "
            f"Hymnal publication years: {_h(summary.get('hymnal_year_range') or 'unknown')} "
            f"({_h(_format_number(summary.get('hymnal_year_known') or 0))} known). "
            f"Hymn-written years: {_h(summary.get('year_written_range') or 'unknown')} "
            f"({_h(_format_number(summary.get('year_written_known') or 0))} known). "
            f"Distinct hymnal titles: {_h(_format_number(summary.get('hymnal_titles') or 0))}. "
            "Hymns are reviewed as a collection here; individual hymn rows belong in a dedicated hymn view."
            "</div>"
        )
    return "".join(panels)


def _render_metadata_details(work: Mapping[str, Any]) -> str:
    rows = _metadata_display_rows(work)
    if not rows:
        return "<span class=\"muted\">No metadata fields</span>"
    rendered = []
    for label, values in rows:
        rendered.append(f"<dt>{_h(label)}</dt><dd>{_render_metadata_values(values)}</dd>")
    return (
        "<details><summary>View fields</summary>"
        f"<dl class=\"metadata\">{''.join(rendered)}</dl>"
        "</details>"
    )


def _metadata_display_rows(work: Mapping[str, Any]) -> list[tuple[str, list[str]]]:
    fields = work["metadata_fields"]
    ordered_keys = [key for key in METADATA_FIELD_ORDER if key in fields]
    remaining_keys = sorted(key for key in fields if key not in ordered_keys)
    rows = []
    for key in ordered_keys + remaining_keys:
        label = METADATA_LABELS.get(key, _humanise_field_name(key))
        values = [str(value) for value in fields[key] if str(value)]
        if values:
            rows.append((label, _limit_values(values)))
    if work.get("resource_ids"):
        rows.append(("Resource IDs in work unit", _limit_values([str(value) for value in work["resource_ids"]])))
    if work.get("source_paths"):
        rows.append(("Source files", _limit_values([str(value) for value in work["source_paths"]])))
    return rows


def _render_metadata_values(values: list[str]) -> str:
    if len(values) == 1:
        return _h(values[0])
    return "<ul class=\"compact\">" + "".join(f"<li>{_h(value)}</li>" for value in values) + "</ul>"


def _humanise_field_name(key: str) -> str:
    return key.replace("provenance.", "Provenance: ").replace("_", " ").capitalize()


def _format_number(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def _limit_values(values: list[str], limit: int = 12) -> list[str]:
    if len(values) <= limit:
        return values
    return values[:limit] + [f"+ {len(values) - limit} more"]


def _h(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def write_outputs(
    catalog: WorkCatalog,
    json_out: Path,
    md_out: Path,
    html_out: Path,
    identity_out: Path | None = None,
) -> None:
    json_out.parent.mkdir(parents=True, exist_ok=True)
    md_out.parent.mkdir(parents=True, exist_ok=True)
    html_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(
        json.dumps(catalog.to_dict(), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    md_out.write_text(render_catalog_markdown(catalog), encoding="utf-8", newline="\n")
    html_out.write_text(render_catalog_html(catalog), encoding="utf-8", newline="\n")
    if identity_out is not None:
        identity_out.parent.mkdir(parents=True, exist_ok=True)
        identity_out.write_bytes(serialize_catalog_identity(catalog))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Count OCD records and build an author/work-led catalog.")
    parser.add_argument("--data-root", type=Path, default=DATA_ROOT)
    parser.add_argument("--json-out", type=Path, default=DEFAULT_JSON_OUT)
    parser.add_argument("--md-out", type=Path, default=DEFAULT_MD_OUT)
    parser.add_argument("--html-out", type=Path, default=DEFAULT_HTML_OUT)
    parser.add_argument(
        "--identity-out",
        type=Path,
        help="Optional compact machine-readable catalog identity snapshot.",
    )
    parser.add_argument("--no-write", action="store_true", help="Print the summary without writing reports.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    catalog = collect_work_catalog(args.data_root)
    if not args.no_write:
        write_outputs(catalog, args.json_out, args.md_out, args.html_out, args.identity_out)
    print(json.dumps(catalog.summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
