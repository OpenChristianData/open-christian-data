"""Compute publication statistics from the flattened Hugging Face JSONL export.

The export is a projection of the schema-backed records: the seven metadata fields
are inlined with a leading underscore, while content fields retain their schema
names.  Token counts therefore use only these schema-derived content fields and
never serialize or tokenize the JSON object itself.

For ``commentary`` and ``reference_entry``, this module rehydrates the flattened
row into the nested ``meta``/``data`` shape and reuses
``ocd_kernel.lib.text_extractor.extract_text``.  That preserves the project's
canonical definitions: ``commentary_text`` for commentary and ``term``,
``alt_terms``, and ``definition_blocks`` for reference entries.

The other export schemas are not supported by that resource-type-specific
extractor, so ``EXPLICIT_TEXT_FIELDS`` is a second, explicit definition kept in
step with ``ocd_kernel/lib/text_extractor.py`` and the source schemas.  It counts
the following human-facing content fields: Bible ``text``; catechism
``question``/``answer`` (including nested sub-question pairs); church-father
``quote``; devotional, prayer, and sermon ``content_blocks``; doctrinal
``content``; hymn ``stanzas``; structured-text ``text``; and topical-reference
``topic``, alternate/related topics, and subtopic labels.  Identifiers, titles,
authors, references, URLs, serialization punctuation, and precomputed count
fields are excluded.  Content strings are encoded independently so no synthetic
separator token is introduced between fields.

``--check-parity`` compares export row counts with the
``legacy_hf_export_records_by_schema`` values produced by
``build/tools/count_dataset_records.py``.  Those are comparable quantities: both
count the published-row semantics, including its leaf handling for nested
structured and doctrinal records; this tool additionally measures the actual
export files' bytes and text tokens.
"""

from __future__ import annotations

import argparse
import gzip
import importlib
import io
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

from ocd_kernel.lib.text_extractor import extract_text


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXPORTS_DIR = REPO_ROOT / "exports" / "huggingface"
SCHEMAS_DIR = REPO_ROOT / "schemas" / "v1"
DEFAULT_ENCODING = "o200k_base"
CONFIGS = (
    "bible_text",
    "catechism_qa",
    "church_fathers",
    "commentary",
    "devotional",
    "doctrinal_document",
    "hymn_collection",
    "prayer",
    "reference_entry",
    "sermon",
    "structured_text",
    "topical_reference",
)
CANONICAL_SCHEMA_TYPES = frozenset({"commentary", "reference_entry"})
CANONICAL_BATCH_SIZE = 10_000

# These are schema field names, not guessed JSON keys.  The canonical extractor
# remains authoritative for the two resource types it supports.
EXPLICIT_TEXT_FIELDS = {
    "bible_text": ("text",),
    "church_fathers": ("quote",),
    "devotional": ("content_blocks",),
    "doctrinal_document": ("content",),
    "hymn_collection": ("stanzas",),
    "prayer": ("content_blocks",),
    "sermon": ("content_blocks",),
    "structured_text": ("text",),
}


def load_encoding(name: str):
    """Load a tiktoken encoding or fail clearly without an approximation."""
    try:
        tiktoken = importlib.import_module("tiktoken")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "tiktoken is required for export statistics; install the pinned dependency from requirements.txt"
        ) from exc
    try:
        return tiktoken.get_encoding(name)
    except (KeyError, ValueError) as exc:
        raise RuntimeError(f"tiktoken does not provide encoding {name!r}") from exc


def _content_strings(value: Any, field_path: str) -> Iterable[str]:
    if isinstance(value, str):
        if value:
            yield value
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            yield from _content_strings(item, f"{field_path}[{index}]")
        return
    if isinstance(value, Mapping):
        text = value.get("text")
        if isinstance(text, str):
            if text:
                yield text
            return
        raise ValueError(f"{field_path} contains an object without a text field")
    if value is None:
        return
    raise ValueError(f"{field_path} has unexpected content type {type(value).__name__}")


def _canonical_texts(records: Iterable[Mapping[str, Any]]) -> list[str]:
    records = list(records)
    first = records[0]
    flattened = [{key: value for key, value in record.items() if not key.startswith("_")} for record in records]
    meta = {
        "id": first.get("_source_id"),
        "title": first.get("_source_title"),
        "author": first.get("_author"),
        "contributors": first.get("_contributors") or [],
        "schema_type": first.get("_schema_type"),
        "license": first.get("_license"),
        "provenance": {"source_url": first.get("_source_url", "")},
    }
    nested = {"meta": meta, "data": flattened}
    return [text for _, _, text, *_ in extract_text(nested, SCHEMAS_DIR)]


def _explicit_texts(record: Mapping[str, Any], schema_type: str) -> list[str]:
    if schema_type == "catechism_qa":
        texts = []
        for field in ("question", "answer"):
            texts.extend(_content_strings(record.get(field), field))
        for index, sub_question in enumerate(record.get("sub_questions") or []):
            if not isinstance(sub_question, Mapping):
                raise ValueError(f"sub_questions[{index}] is not an object")
            for field in ("question", "answer"):
                texts.extend(_content_strings(sub_question.get(field), f"sub_questions[{index}].{field}"))
        return texts

    if schema_type == "topical_reference":
        texts = list(_content_strings(record.get("topic"), "topic"))
        texts.extend(_content_strings(record.get("alt_topics"), "alt_topics"))
        texts.extend(_content_strings(record.get("related_topics"), "related_topics"))
        for index, subtopic in enumerate(record.get("subtopics") or []):
            if not isinstance(subtopic, Mapping):
                raise ValueError(f"subtopics[{index}] is not an object")
            texts.extend(_content_strings(subtopic.get("label"), f"subtopics[{index}].label"))
        return texts

    try:
        fields = EXPLICIT_TEXT_FIELDS[schema_type]
    except KeyError as exc:
        raise ValueError(f"unsupported export schema type {schema_type!r}") from exc
    texts = []
    for field in fields:
        texts.extend(_content_strings(record.get(field), field))
    return texts


def record_texts(record: Mapping[str, Any]) -> list[str]:
    """Return only the human text selected for one flattened export row."""
    schema_type = record.get("_schema_type")
    if not isinstance(schema_type, str) or not schema_type:
        raise ValueError("export record is missing a non-empty _schema_type")
    if schema_type in CANONICAL_SCHEMA_TYPES:
        return _canonical_texts([record])
    return _explicit_texts(record, schema_type)


def _gzip_size(path: Path) -> int:
    compressed = io.BytesIO()
    with path.open("rb") as source, gzip.GzipFile(fileobj=compressed, mode="wb", mtime=0) as target:
        shutil.copyfileobj(source, target, length=1024 * 1024)
    return len(compressed.getvalue())


def count_file(path: Path, encoding: Any, expected_schema_type: str | None = None) -> dict[str, int | str]:
    """Count records and selected text tokens in one JSONL export file."""
    records = 0
    tokens = 0
    canonical_batch: list[Mapping[str, Any]] = []
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON in {path} line {line_number}: {exc.msg}") from exc
            if not isinstance(record, Mapping):
                raise ValueError(f"{path} line {line_number} is not a JSON object")
            schema_type = record.get("_schema_type")
            if expected_schema_type is not None and schema_type != expected_schema_type:
                raise ValueError(
                    f"{path} line {line_number} has _schema_type {schema_type!r}; "
                    f"expected {expected_schema_type!r}"
                )
            records += 1
            if schema_type in CANONICAL_SCHEMA_TYPES:
                canonical_batch.append(record)
                if len(canonical_batch) >= CANONICAL_BATCH_SIZE:
                    tokens += sum(
                        len(encoding.encode(text, disallowed_special=()))
                        for text in _canonical_texts(canonical_batch)
                    )
                    canonical_batch.clear()
            else:
                tokens += sum(len(encoding.encode(text, disallowed_special=())) for text in record_texts(record))
    if canonical_batch:
        tokens += sum(len(encoding.encode(text, disallowed_special=())) for text in _canonical_texts(canonical_batch))
    return {
        "configuration": expected_schema_type or str(path.stem),
        "records": records,
        "tokens": tokens,
        "uncompressed_bytes": path.stat().st_size,
        "gzip_bytes": _gzip_size(path),
    }


def collect_stats(exports_dir: Path = DEFAULT_EXPORTS_DIR, encoding_name: str = DEFAULT_ENCODING) -> dict[str, Any]:
    encoding = load_encoding(encoding_name)
    expected_paths = {name: exports_dir / f"{name}.jsonl" for name in CONFIGS}
    missing = [str(path) for path in expected_paths.values() if not path.exists()]
    if missing:
        raise FileNotFoundError("missing expected export file(s): " + ", ".join(missing))
    unexpected = sorted(path.name for path in exports_dir.glob("*.jsonl") if path.name not in {p.name for p in expected_paths.values()})
    if unexpected:
        raise ValueError("unexpected JSONL export file(s): " + ", ".join(unexpected))

    rows = [count_file(expected_paths[name], encoding, name) for name in CONFIGS]
    total = {
        "configuration": "total",
        "records": sum(int(row["records"]) for row in rows),
        "tokens": sum(int(row["tokens"]) for row in rows),
        "uncompressed_bytes": sum(int(row["uncompressed_bytes"]) for row in rows),
        "gzip_bytes": sum(int(row["gzip_bytes"]) for row in rows),
    }
    return {"tokenizer_encoding": encoding_name, "configurations": rows, "total": total}


def render_markdown(stats: Mapping[str, Any]) -> str:
    encoding = stats["tokenizer_encoding"]
    lines = [
        f"Tokenizer encoding: `{encoding}`",
        "",
        "| Configuration | Records | Tokens | Uncompressed bytes | Gzip bytes |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in [*stats["configurations"], stats["total"]]:
        label = "**Total**" if row["configuration"] == "total" else row["configuration"]
        lines.append(
            f"| {label} | {int(row['records']):,} | {int(row['tokens']):,} | "
            f"{int(row['uncompressed_bytes']):,} | {int(row['gzip_bytes']):,} |"
        )
    lines.extend(
        [
            "",
            f"Token counts cover only schema-defined human text fields and use tiktoken `{encoding}`; JSON scaffolding, metadata, identifiers, references, and URLs are excluded.",
            "",
        ]
    )
    return "\n".join(lines)


def render_json(stats: Mapping[str, Any]) -> str:
    return json.dumps(stats, ensure_ascii=False, indent=2) + "\n"


def parity_mismatches(stats: Mapping[str, Any]) -> list[tuple[str, int | None, int | None]]:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from build.tools.count_dataset_records import collect_work_catalog

    authoritative = collect_work_catalog().summary.get("legacy_hf_export_records_by_schema", {})
    actual = {row["configuration"]: int(row["records"]) for row in stats["configurations"]}
    names = sorted(set(actual) | set(authoritative))
    return [
        (name, actual.get(name), int(authoritative[name]) if name in authoritative else None)
        for name in names
        if actual.get(name) != (int(authoritative[name]) if name in authoritative else None)
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compute token and size statistics for the Hugging Face JSONL export.")
    parser.add_argument("--exports-dir", type=Path, default=DEFAULT_EXPORTS_DIR)
    parser.add_argument("--encoding", default=DEFAULT_ENCODING)
    parser.add_argument("--output", type=Path, help="Also write the selected markdown or JSON output to this path.")
    parser.add_argument("--json", action="store_true", help="Emit the statistics as JSON instead of a markdown table.")
    parser.add_argument("--check-parity", action="store_true", help="Compare export record counts with count_dataset_records.py.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        stats = collect_stats(args.exports_dir, args.encoding)
        rendered = render_json(stats) if args.json else render_markdown(stats)
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        sys.stdout.write(rendered)
        if args.check_parity:
            mismatches = parity_mismatches(stats)
            if mismatches:
                for name, actual, authoritative in mismatches:
                    print(
                        f"parity mismatch: {name}: export={actual!r}, count_dataset_records={authoritative!r}",
                        file=sys.stderr,
                    )
                return 1
            print("Parity check: PASS", file=sys.stderr)
        return 0
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
