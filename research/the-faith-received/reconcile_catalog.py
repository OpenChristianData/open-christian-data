"""Build a read-only TFR catalog to OCD work-title crosswalk.

The input Markdown is a dated catalog snapshot. The script preserves each
entry's supplied fields and raw detail line, then attaches unverified exact-title
candidate links to current OCD work sidecars. It never edits library records.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_HOME = Path(__file__).resolve().parent
DEFAULT_SOURCE = OUTPUT_HOME / "source" / "the-faith-received-complete-works-20260930.md"
DEFAULT_REVIEW_NOTE = PROJECT_ROOT / "research" / "2026-09-29-mere-orthodoxy-site-review.md"

ENTRY_RE = re.compile(r"^- \[(?P<title>.+)\]\((?P<url>https?://[^\s)]+)\)\s*$")
COLLECTION_COUNT_RE = re.compile(r"^(?P<name>.*?)\s+\((?P<count>[\d,]+) entries\)$")
DECLARED_TOTAL_RE = re.compile(r"\*\*(?P<count>[\d,]+) catalogue entries\*\*")
FIELD_LABELS = (
    "Alternate title",
    "Volume",
    "Columns",
    "Tradition",
    "Party",
    "Publication place",
    "Fascicle",
    "Date/context",
    "original",
)
FIELD_LABEL_PATTERN = re.compile(
    r"(?:^|;\s*)(?P<label>" + "|".join(re.escape(label) for label in FIELD_LABELS) + r")\s*:\s*",
    re.IGNORECASE,
)
TABLE_ID_RE = re.compile(r"[?&]w=([^&\)\]]+)")
MANIFEST_SCOPE_START = "Acquisition queue"
MANIFEST_SCOPE_END = "Pipeline gaps — what parser / schema work unlocks the most"

CSV_FIELDS = [
    "catalog_snapshot_date",
    "tfr_entry_id",
    "collection",
    "catalog_author",
    "catalog_author_heading",
    "catalog_author_supplied",
    "title",
    "reader_url",
    "alternate_title",
    "volume",
    "columns",
    "tradition",
    "party",
    "publication_place",
    "fascicle",
    "date_context",
    "original",
    "site_metadata_raw",
    "source_title_line",
    "prior_item_check_count",
    "prior_item_check_records_json",
    "historical_manifest_mention_count",
    "historical_manifest_mentions_json",
    "ocd_match_status",
    "ocd_match_basis",
    "ocd_candidate_count",
    "ocd_candidate_work_ids",
    "ocd_candidates_json",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize_for_match(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value).casefold()
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", without_marks))


def parse_site_fields(raw_lines: list[str]) -> tuple[str, dict[str, str]]:
    raw = "\n".join(raw_lines)
    flattened = "; ".join(line.strip()[2:] if line.strip().startswith("- ") else line.strip() for line in raw_lines)
    matches = list(FIELD_LABEL_PATTERN.finditer(flattened))
    fields: dict[str, str] = {}
    label_by_key = {label.casefold(): label for label in FIELD_LABELS}
    for index, match in enumerate(matches):
        value_end = matches[index + 1].start() if index + 1 < len(matches) else len(flattened)
        value = flattened[match.end() : value_end].strip().rstrip("; ").strip()
        label = label_by_key[match.group("label").casefold()]
        fields[label] = value
    return raw, fields


def parse_catalog(path: Path, *, allow_duplicate_ids: bool = False) -> tuple[list[dict], dict[str, int], int | None]:
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    declared_total_match = DECLARED_TOTAL_RE.search(text)
    declared_total = int(declared_total_match.group("count").replace(",", "")) if declared_total_match else None
    current_collection: str | None = None
    current_author: str | None = None
    current_entry: dict | None = None
    declared_collection_counts: dict[str, int] = {}
    records: list[dict] = []

    for line_number, line in enumerate(lines, start=1):
        if line.startswith("### ") and not line.startswith("#### "):
            current_entry = None
            heading = line[4:].strip()
            count_match = COLLECTION_COUNT_RE.match(heading)
            if count_match:
                current_collection = count_match.group("name").strip()
                declared_collection_counts[current_collection] = int(count_match.group("count").replace(",", ""))
                current_author = None
            continue
        if line.startswith("#### "):
            current_entry = None
            current_author = line[5:].strip()
            continue

        match = ENTRY_RE.match(line)
        if match and "/the-faith-received/read/" in match.group("url"):
            url = match.group("url")
            parsed_url = urlparse(url)
            query = parse_qs(parsed_url.query)
            ids = query.get("w", [])
            if parsed_url.hostname not in {"mereorthodoxy.com", "www.mereorthodoxy.com"}:
                raise ValueError(f"Unexpected reader host at source line {line_number}: {parsed_url.hostname}")
            if len(ids) != 1 or not ids[0].strip():
                raise ValueError(f"Reader URL has no unique w= identifier at source line {line_number}: {url}")
            if current_collection is None:
                raise ValueError(f"Catalogue entry has no collection heading at source line {line_number}")
            current_entry = {
                "tfr_entry_id": ids[0],
                "collection": current_collection,
                "catalog_author_heading": current_author or "",
                "catalog_author": "" if normalize_for_match(current_author or "") == "author not supplied" else (current_author or ""),
                "catalog_author_supplied": normalize_for_match(current_author or "") != "author not supplied" and bool(current_author),
                "title": match.group("title"),
                "reader_url": url,
                "source_title_line": line_number,
                "source_metadata_lines": [],
            }
            records.append(current_entry)
            continue

        if current_entry is not None:
            if not line.strip():
                continue
            if line.startswith("  "):
                current_entry["source_metadata_lines"].append(line)
                continue
            current_entry = None

    for record in records:
        raw, fields = parse_site_fields(record["source_metadata_lines"])
        record["site_metadata_raw"] = raw
        record["site_metadata_fields"] = fields

    ids = [record["tfr_entry_id"] for record in records]
    urls = [record["reader_url"] for record in records]
    if not allow_duplicate_ids and len(ids) != len(set(ids)):
        raise ValueError("TFR reader identifiers are not unique in the supplied snapshot")
    if not allow_duplicate_ids and len(urls) != len(set(urls)):
        raise ValueError("TFR reader URLs are not unique in the supplied snapshot")
    if declared_total is not None and len(records) != declared_total:
        raise ValueError(f"Parsed {len(records)} entries; source declares {declared_total}")
    actual_collection_counts = Counter(record["collection"] for record in records)
    if declared_collection_counts != dict(actual_collection_counts):
        raise ValueError(
            "Collection counts disagree: declared="
            f"{declared_collection_counts!r}; parsed={dict(actual_collection_counts)!r}"
        )
    for record in records:
        if not record["title"].strip() or not record["reader_url"].strip():
            raise ValueError(f"Empty title or reader URL at source line {record['source_title_line']}")
    return records, declared_collection_counts, declared_total


def read_current_works(works_root: Path) -> tuple[list[dict], str, Counter]:
    if not works_root.is_dir():
        raise FileNotFoundError(f"Canonical work sidecar directory not found: {works_root}")
    work_paths = sorted(works_root.glob("*/work.json"))
    works: list[dict] = []
    seen_work_ids: set[str] = set()
    roster_digest = hashlib.sha256()
    aggregate_target_stages: Counter = Counter()

    for work_path in work_paths:
        state_path = work_path.with_name("state.json")
        try:
            work = json.loads(work_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Cannot parse canonical work sidecar {work_path}: {exc}") from exc
        if work.get("work_id") != work_path.parent.name:
            raise ValueError(
                f"work_id/path mismatch at {work_path}: {work.get('work_id')!r} != {work_path.parent.name!r}"
            )
        work_id = work.get("work_id")
        if not isinstance(work_id, str) or not work_id:
            raise ValueError(f"Missing work_id in {work_path}")
        if work_id in seen_work_ids:
            raise ValueError(f"Duplicate canonical work_id: {work_id}")
        seen_work_ids.add(work_id)
        if not state_path.is_file():
            raise ValueError(f"Missing canonical state sidecar for {work_id}: {state_path}")
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Cannot parse canonical state sidecar {state_path}: {exc}") from exc
        if state.get("work_id") != work_id:
            raise ValueError(f"work_id mismatch between {work_path} and {state_path}")

        relative_work = work_path.relative_to(PROJECT_ROOT).as_posix()
        relative_state = state_path.relative_to(PROJECT_ROOT).as_posix()
        roster_digest.update(relative_work.encode("utf-8"))
        roster_digest.update(b"\0")
        roster_digest.update(sha256_file(work_path).encode("ascii"))
        roster_digest.update(b"\0")
        roster_digest.update(relative_state.encode("utf-8"))
        roster_digest.update(b"\0")
        roster_digest.update(sha256_file(state_path).encode("ascii"))
        roster_digest.update(b"\n")

        creators = [
            creator.get("name", "")
            for creator in work.get("creators", [])
            if isinstance(creator, dict) and isinstance(creator.get("name"), str) and creator["name"].strip()
        ]
        title_values: list[tuple[str, str]] = []
        if isinstance(work.get("title"), str) and work["title"].strip():
            title_values.append(("work_title", work["title"]))
        for form in work.get("textual_forms", []):
            if not isinstance(form, dict):
                continue
            for edition in form.get("editions", []):
                if isinstance(edition, dict) and isinstance(edition.get("title"), str) and edition["title"].strip():
                    title_values.append(("edition_title", edition["title"]))

        target_summary: dict[str, dict[str, int]] = {"acquisition": {}, "edition": {}}
        for target in state.get("targets", []):
            if not isinstance(target, dict):
                continue
            target_type = target.get("target_type")
            stage = target.get("stage")
            if target_type in target_summary and isinstance(stage, str):
                target_summary[target_type][stage] = target_summary[target_type].get(stage, 0) + 1
                aggregate_target_stages[(target_type, stage)] += 1

        works.append(
            {
                "work_id": work_id,
                "path": relative_work,
                "title": work.get("title", ""),
                "creators": creators,
                "title_values": title_values,
                "target_summary": target_summary,
            }
        )

    return works, roster_digest.hexdigest(), aggregate_target_stages


def read_prior_item_checks(path: Path | None) -> dict[str, list[dict]]:
    if path is None or not path.is_file():
        return {}
    checks: dict[str, list[dict]] = defaultdict(list)
    current_section = ""
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if line.startswith("#"):
            current_section = line.lstrip("# ").strip()
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not cells or all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells):
            continue
        ids = list(dict.fromkeys(TABLE_ID_RE.findall(line)))
        if not ids:
            continue
        item = {
            "evidence_path": path.relative_to(PROJECT_ROOT).as_posix(),
            "evidence_line": line_number,
            "section": current_section,
            "row_markdown": line,
            "cells": cells,
        }
        for tfr_id in ids:
            checks[tfr_id].append(item)
    return dict(checks)


def read_historical_manifest_work_rows(path: Path) -> tuple[list[dict], str, dict]:
    """Read work-column rows from the dated acquisition/research sections only."""
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    in_scope = False
    major_section = ""
    subsection = ""
    table: list[tuple[int, str]] = []
    rows: list[dict] = []
    work_rows_scanned = 0

    def flush_table() -> None:
        nonlocal table, work_rows_scanned
        if len(table) < 3:
            table = []
            return
        headers = parse_table_row(table[0][1])
        separator = parse_table_row(table[1][1])
        if len(headers) != len(separator) or not all(
            re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in separator
        ):
            table = []
            return
        work_columns = [
            index for index, header in enumerate(headers)
            if normalize_for_match(header).startswith("work")
        ]
        if not work_columns:
            table = []
            return
        section = " > ".join(value for value in (major_section, subsection) if value)
        for line_number, raw_line in table[2:]:
            cells = parse_table_row(raw_line)
            if len(cells) != len(headers):
                continue
            work_rows_scanned += 1
            columns = dict(zip(headers, cells, strict=True))
            for work_column_index in work_columns:
                rows.append(
                    {
                        "manifest_line": line_number,
                        "manifest_section": section,
                        "work_column": headers[work_column_index],
                        "work_label": cells[work_column_index],
                        "columns": columns,
                        "raw_row": raw_line,
                    }
                )
        table = []

    for line_number, line in enumerate(lines, start=1):
        if line.startswith("## "):
            flush_table()
            heading = line[3:].strip()
            if heading == MANIFEST_SCOPE_START:
                in_scope = True
                major_section = heading
                subsection = ""
                continue
            if heading == MANIFEST_SCOPE_END:
                in_scope = False
                major_section = ""
                subsection = ""
                continue
            if in_scope:
                major_section = heading
                subsection = ""
            continue
        if not in_scope:
            continue
        if line.startswith("### "):
            flush_table()
            subsection = line[4:].strip()
            continue
        if line.startswith("#### "):
            flush_table()
            subsection = f"{subsection} > {line[5:].strip()}".strip(" >")
            continue
        if line.startswith("|"):
            table.append((line_number, line))
        else:
            flush_table()
    flush_table()

    legacy_lead_path = path.parent / "acquisition-leads.jsonl"
    legacy_lead_summary = {
        "path": legacy_lead_path.relative_to(PROJECT_ROOT).as_posix(),
        "used_as_match_source": False,
        "record_count": 0,
        "unique_lead_ids": 0,
        "recorded_manifest_hashes": [],
        "source_hash_matches_current_manifest": None,
        "dispositions": {},
    }
    if legacy_lead_path.is_file():
        lead_ids: set[str] = set()
        recorded_hashes: set[str] = set()
        dispositions: Counter = Counter()
        record_count = 0
        with legacy_lead_path.open("r", encoding="utf-8-sig") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Invalid lead JSON at {legacy_lead_path}:{line_number}: {exc}") from exc
                record_count += 1
                if isinstance(record.get("lead_id"), str):
                    lead_ids.add(record["lead_id"])
                evidence = record.get("evidence", {})
                if isinstance(evidence, dict) and isinstance(evidence.get("sha256"), str):
                    recorded_hashes.add(evidence["sha256"])
                if isinstance(record.get("disposition"), str):
                    dispositions[record["disposition"]] += 1
        current_hash = sha256_file(path)
        legacy_lead_summary.update(
            {
                "record_count": record_count,
                "unique_lead_ids": len(lead_ids),
                "recorded_manifest_hashes": sorted(recorded_hashes),
                "source_hash_matches_current_manifest": bool(recorded_hashes) and recorded_hashes == {current_hash},
                "dispositions": dict(sorted(dispositions.items())),
            }
        )

    return rows, sha256_file(path), {
        "work_table_rows_scanned": work_rows_scanned,
        "manifest_scope_start": MANIFEST_SCOPE_START,
        "manifest_scope_end_exclusive": MANIFEST_SCOPE_END,
        "legacy_lead_extract": legacy_lead_summary,
    }


def match_manifest_rows(record: dict, manifest_rows: list[dict]) -> list[dict]:
    """Return exact normalized title mentions in manifest work columns."""
    variants = [("tfr_title", record["title"])]
    alternate_title = record["site_metadata_fields"].get("Alternate title", "")
    if alternate_title:
        variants.append(("tfr_alternate_title", alternate_title))
    normalized_variants = [
        (field_name, title, normalize_for_match(title))
        for field_name, title in variants
        if normalize_for_match(title)
    ]
    matches: list[dict] = []
    for row in manifest_rows:
        work_label_norm = normalize_for_match(row["work_label"])
        for field_name, title, title_norm in normalized_variants:
            exact_cell = title_norm == work_label_norm
            phrase_in_cell = (
                len(title_norm.split()) >= 2
                and f" {title_norm} " in f" {work_label_norm} "
            )
            if exact_cell or phrase_in_cell:
                matches.append(
                    {
                        "manifest_line": row["manifest_line"],
                        "manifest_section": row["manifest_section"],
                        "work_column": row["work_column"],
                        "work_label": row["work_label"],
                        "matched_tfr_title_field": field_name,
                        "matched_tfr_title": title,
                        "match_basis": "normalized_exact_work_cell" if exact_cell else "normalized_exact_title_phrase_in_work_cell",
                        "columns": row["columns"],
                        "raw_row": row["raw_row"],
                    }
                )
    unique_matches = {
        (item["manifest_line"], item["matched_tfr_title_field"]): item
        for item in matches
    }
    return [unique_matches[key] for key in sorted(unique_matches)]


def build_title_index(works: list[dict]) -> dict[str, list[tuple[dict, str, str]]]:
    index: dict[str, list[tuple[dict, str, str]]] = defaultdict(list)
    for work in works:
        for title_kind, title in work["title_values"]:
            index[normalize_for_match(title)].append((work, title_kind, title))
    return index


def match_record(record: dict, title_index: dict[str, list[tuple[dict, str, str]]]) -> tuple[str, list[dict], str]:
    variants = [("tfr_title", record["title"])]
    alternate_title = record["site_metadata_fields"].get("Alternate title", "")
    if alternate_title:
        variants.append(("tfr_alternate_title", alternate_title))

    candidates: dict[str, dict] = {}
    author_norm = normalize_for_match(record["catalog_author"])
    for variant_kind, variant_title in variants:
        for work, ocd_title_kind, ocd_title in title_index.get(normalize_for_match(variant_title), []):
            candidate = candidates.setdefault(
                work["work_id"],
                {
                    "work_id": work["work_id"],
                    "work_title": work["title"],
                    "creators": work["creators"],
                    "creator_match": "tfr_author_missing",
                    "matched_titles": [],
                    "target_stages": work["target_summary"],
                    "work_sidecar": work["path"],
                },
            )
            if record["catalog_author_supplied"]:
                if any(author_norm == normalize_for_match(creator) for creator in work["creators"]):
                    candidate["creator_match"] = "exact_normalized_name"
                elif work["creators"]:
                    candidate["creator_match"] = "no_exact_name_match"
                else:
                    candidate["creator_match"] = "creator_not_recorded_in_work_sidecar"
            match = {
                "tfr_title_field": variant_kind,
                "tfr_title_value": variant_title,
                "ocd_title_field": ocd_title_kind,
                "ocd_title_value": ocd_title,
            }
            if match not in candidate["matched_titles"]:
                candidate["matched_titles"].append(match)

    ordered_candidates = [candidates[work_id] for work_id in sorted(candidates)]
    exact_creator_count = sum(c["creator_match"] == "exact_normalized_name" for c in ordered_candidates)
    if not ordered_candidates:
        status = "no_exact_title_candidate"
    elif len(ordered_candidates) == 1 and exact_creator_count:
        status = "exact_title_creator_candidate"
    elif len(ordered_candidates) > 1 and exact_creator_count:
        status = "multiple_title_candidates_with_creator_match"
    elif len(ordered_candidates) > 1:
        status = "multiple_exact_title_candidates_creator_unverified"
    elif not record["catalog_author_supplied"]:
        status = "single_exact_title_candidate_tfr_author_missing"
    elif ordered_candidates[0]["creator_match"] == "creator_not_recorded_in_work_sidecar":
        status = "single_exact_title_candidate_ocd_creator_missing"
    else:
        status = "single_exact_title_candidate_creator_name_differs"

    if not ordered_candidates:
        basis = "no_normalized_exact_match_on_work_or_edition_title"
    else:
        basis = "normalized_exact_title"
        if alternate_title and any(
            title_match["tfr_title_field"] == "tfr_alternate_title"
            for candidate in ordered_candidates
            for title_match in candidate["matched_titles"]
        ):
            basis += "; normalized_exact_alternate_title"
        if exact_creator_count:
            basis += "; normalized_exact_creator_name_candidate"
    return status, ordered_candidates, basis


def parse_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def write_outputs(
    records: list[dict],
    works: list[dict],
    source_path: Path,
    source_sha256: str,
    snapshot_date: str,
    output_csv: Path,
    output_metadata: Path,
    work_roster_sha256: str,
    target_stage_counts: Counter,
    prior_checks: dict[str, list[dict]],
    manifest_rows: list[dict],
    manifest_sha256: str,
    manifest_summary: dict,
    overwrite: bool,
) -> dict:
    output_home = OUTPUT_HOME.resolve()
    for output_path in (output_csv.resolve(), output_metadata.resolve()):
        if not output_path.is_relative_to(output_home):
            raise ValueError(f"Output path must remain under {output_home}: {output_path}")
        if output_path.exists() and not overwrite:
            raise FileExistsError(f"Output already exists; pass --overwrite to replace this task output: {output_path}")
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    output_metadata.parent.mkdir(parents=True, exist_ok=True)

    work_index = build_title_index(works)
    status_counts: Counter = Counter()
    per_collection: dict[str, Counter] = defaultdict(Counter)
    candidate_edges = 0
    distinct_candidate_work_ids: set[str] = set()
    exact_creator_rows = 0
    rows: list[dict] = []
    prior_check_ids_present: set[str] = set()
    historical_manifest_match_rows = 0
    historical_manifest_match_edges = 0

    for record in records:
        status, candidates, basis = match_record(record, work_index)
        status_counts[status] += 1
        per_collection[record["collection"]][status] += 1
        candidate_edges += len(candidates)
        distinct_candidate_work_ids.update(candidate["work_id"] for candidate in candidates)
        if any(candidate["creator_match"] == "exact_normalized_name" for candidate in candidates):
            exact_creator_rows += 1

        record_checks = prior_checks.get(record["tfr_entry_id"], [])
        if record_checks:
            prior_check_ids_present.add(record["tfr_entry_id"])
        manifest_matches = match_manifest_rows(record, manifest_rows)
        if manifest_matches:
            historical_manifest_match_rows += 1
        historical_manifest_match_edges += len(manifest_matches)
        fields = record["site_metadata_fields"]
        candidates_json = json.dumps(candidates, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        checks_json = json.dumps(record_checks, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        manifest_matches_json = json.dumps(manifest_matches, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        rows.append(
            {
                "catalog_snapshot_date": snapshot_date,
                "tfr_entry_id": record["tfr_entry_id"],
                "collection": record["collection"],
                "catalog_author": record["catalog_author"],
                "catalog_author_heading": record["catalog_author_heading"],
                "catalog_author_supplied": str(record["catalog_author_supplied"]).lower(),
                "title": record["title"],
                "reader_url": record["reader_url"],
                "alternate_title": fields.get("Alternate title", ""),
                "volume": fields.get("Volume", ""),
                "columns": fields.get("Columns", ""),
                "tradition": fields.get("Tradition", ""),
                "party": fields.get("Party", ""),
                "publication_place": fields.get("Publication place", ""),
                "fascicle": fields.get("Fascicle", ""),
                "date_context": fields.get("Date/context", ""),
                "original": fields.get("original", ""),
                "site_metadata_raw": record["site_metadata_raw"],
                "source_title_line": record["source_title_line"],
                "prior_item_check_count": len(record_checks),
                "prior_item_check_records_json": checks_json,
                "historical_manifest_mention_count": len(manifest_matches),
                "historical_manifest_mentions_json": manifest_matches_json,
                "ocd_match_status": status,
                "ocd_match_basis": basis,
                "ocd_candidate_count": len(candidates),
                "ocd_candidate_work_ids": " | ".join(candidate["work_id"] for candidate in candidates),
                "ocd_candidates_json": candidates_json,
            }
        )

    with output_csv.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)

    with output_csv.open("r", encoding="utf-8-sig", newline="") as stream:
        reread = list(csv.DictReader(stream))
    if len(reread) != len(records):
        raise ValueError(f"CSV round-trip row count changed: {len(records)} -> {len(reread)}")
    reread_ids = [row["tfr_entry_id"] for row in reread]
    if len(reread_ids) != len(set(reread_ids)):
        raise ValueError("CSV round-trip introduced duplicate TFR identifiers")
    if any(not row["reader_url"] or not row["title"] for row in reread):
        raise ValueError("CSV round-trip produced an empty title or reader URL")
    parsed_fields = {
        "Alternate title": "alternate_title",
        "Volume": "volume",
        "Columns": "columns",
        "Tradition": "tradition",
        "Party": "party",
        "Publication place": "publication_place",
        "Fascicle": "fascicle",
        "Date/context": "date_context",
        "original": "original",
    }
    for source_record, output_row in zip(records, reread, strict=True):
        if output_row["site_metadata_raw"] != source_record["site_metadata_raw"]:
            raise ValueError(f"Raw site metadata changed during CSV round-trip for {source_record['tfr_entry_id']}")
        if int(output_row["source_title_line"]) != source_record["source_title_line"]:
            raise ValueError(f"Source locator changed during CSV round-trip for {source_record['tfr_entry_id']}")
        for field_name, output_name in parsed_fields.items():
            if output_row[output_name] != source_record["site_metadata_fields"].get(field_name, ""):
                raise ValueError(f"Parsed source field {field_name} changed for {source_record['tfr_entry_id']}")
        candidate_payload = json.loads(output_row["ocd_candidates_json"])
        if len(candidate_payload) != int(output_row["ocd_candidate_count"]):
            raise ValueError(f"Candidate count changed during CSV round-trip for {source_record['tfr_entry_id']}")
        manifest_payload = json.loads(output_row["historical_manifest_mentions_json"])
        if len(manifest_payload) != int(output_row["historical_manifest_mention_count"]):
            raise ValueError(f"Historical manifest mention count changed for {source_record['tfr_entry_id']}")

    metadata_field_counts = Counter(
        field for record in records for field in record["site_metadata_fields"]
    )
    source_collection_counts = Counter(record["collection"] for record in records)
    checks_not_in_catalog = sorted(set(prior_checks) - {record["tfr_entry_id"] for record in records})
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    try:
        source_path_for_metadata = source_path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        source_path_for_metadata = str(source_path)
    summary = {
        "schema_version": "1.0",
        "generated_at_utc": generated_at,
        "catalog_snapshot_date": snapshot_date,
        "source_catalog_path": source_path_for_metadata,
        "source_catalog_sha256": source_sha256,
        "source_catalog_entries": len(records),
        "source_unique_reader_urls": len({record["reader_url"] for record in records}),
        "source_unique_tfr_ids": len({record["tfr_entry_id"] for record in records}),
        "source_author_missing": sum(not record["catalog_author_supplied"] for record in records),
        "source_collection_counts": dict(sorted(source_collection_counts.items())),
        "source_metadata_field_counts": dict(sorted(metadata_field_counts.items())),
        "canonical_library_root": "library/works",
        "canonical_work_state_pairs": len(works),
        "canonical_work_roster_sha256": work_roster_sha256,
        "canonical_target_stage_counts": {
            f"{target_type}:{stage}": count
            for (target_type, stage), count in sorted(target_stage_counts.items())
        },
        "historical_acquisition_manifest": {
            "path": (PROJECT_ROOT / "research" / "MANIFEST.md").relative_to(PROJECT_ROOT).as_posix(),
            "sha256": manifest_sha256,
            **manifest_summary,
            "exact_title_mention_catalog_rows": historical_manifest_match_rows,
            "exact_title_mention_edges": historical_manifest_match_edges,
            "match_method": "normalized TFR title or alternate title compared with work-column labels in Markdown tables within dated acquisition/research sections; exact cell or contiguous exact phrase only",
            "authority_limit": "Historical research mention only; does not establish current acquisition intent, identity, acquisition status, edition identity, rights, or source availability.",
        },
        "match_method": {
            "normalization": "Unicode NFKD; casefold; remove combining marks; compare alphanumeric word sequences",
            "tfr_title_fields": ["title", "Alternate title when supplied"],
            "ocd_title_fields": ["work.json title", "work.json textual_forms[].editions[].title"],
            "creator_candidate_rule": "exact normalized TFR catalog author to work.json creators[].name",
            "fuzzy_matching": False,
            "automatic_identity_confirmation": False,
        },
        "crosswalk_rows_by_status": dict(sorted(status_counts.items())),
        "crosswalk_rows_by_collection": {
            collection: dict(sorted(counts.items()))
            for collection, counts in sorted(per_collection.items())
        },
        "rows_with_exact_creator_name_candidate": exact_creator_rows,
        "candidate_work_edges": candidate_edges,
        "distinct_candidate_work_ids": len(distinct_candidate_work_ids),
        "prior_item_check_ids_in_catalog": len(prior_check_ids_present),
        "prior_item_check_ids_not_in_catalog": checks_not_in_catalog,
        "limits": [
            "Every OCD link is an unverified title-level candidate, not an established work or edition identity.",
            "No fuzzy or semantic title matching was performed; no exact-title candidate does not prove no overlap.",
            "A current OCD acquisition or edition target may describe a different edition or witness than the TFR item.",
            "The supplied all-works snapshot contains no item-level AI-translation, public-domain, reuse-rights, or download-availability field.",
            "Previously recorded reader checks are copied as dated evidence from the linked research note; they were not refreshed in this run.",
        ],
        "output_csv_path": output_csv.resolve().relative_to(PROJECT_ROOT).as_posix(),
        "output_csv_sha256": sha256_file(output_csv),
        "output_csv_rows_roundtrip": len(reread),
    }
    output_metadata.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_SOURCE, help="TFR all-works snapshot Markdown (defaults to the preserved project snapshot)")
    parser.add_argument("--output-csv", required=True, type=Path, help="Output crosswalk CSV, under this script's directory")
    parser.add_argument("--output-metadata", required=True, type=Path, help="Output JSON metadata, under this script's directory")
    parser.add_argument("--snapshot-date", required=True, help="Date printed in the source snapshot (YYYY-MM-DD)")
    parser.add_argument("--review-note", type=Path, default=DEFAULT_REVIEW_NOTE, help="Existing TFR research note with prior reader checks")
    parser.add_argument("--overwrite", action="store_true", help="Replace these exact generated outputs")
    args = parser.parse_args()

    source_path = args.input.expanduser().resolve(strict=True)
    output_csv = args.output_csv if args.output_csv.is_absolute() else PROJECT_ROOT / args.output_csv
    output_metadata = args.output_metadata if args.output_metadata.is_absolute() else PROJECT_ROOT / args.output_metadata
    works_root = PROJECT_ROOT / "library" / "works"
    review_note = args.review_note if args.review_note.is_absolute() else PROJECT_ROOT / args.review_note

    records, declared_collection_counts, declared_total = parse_catalog(source_path)
    source_sha256 = sha256_file(source_path)
    works, work_roster_sha256, target_stage_counts = read_current_works(works_root)
    prior_checks = read_prior_item_checks(review_note)
    manifest_path = PROJECT_ROOT / "research" / "MANIFEST.md"
    manifest_rows, manifest_sha256, manifest_summary = read_historical_manifest_work_rows(manifest_path)
    summary = write_outputs(
        records=records,
        works=works,
        source_path=source_path,
        source_sha256=source_sha256,
        snapshot_date=args.snapshot_date,
        output_csv=output_csv,
        output_metadata=output_metadata,
        work_roster_sha256=work_roster_sha256,
        target_stage_counts=target_stage_counts,
        prior_checks=prior_checks,
        manifest_rows=manifest_rows,
        manifest_sha256=manifest_sha256,
        manifest_summary=manifest_summary,
        overwrite=args.overwrite,
    )
    summary["source_declared_total"] = declared_total
    summary["source_declared_collection_counts"] = dict(sorted(declared_collection_counts.items()))
    # These source declarations are repeated in the metadata file for a direct audit trail.
    output_metadata.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, FileExistsError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
