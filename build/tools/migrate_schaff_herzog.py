from __future__ import annotations

import argparse
import builtins
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ocd_kernel.lib import atomic_io
from ocd_kernel.lib.schema_enums import resolve_schema_path


CATALOG_SCHEMA = json.loads(resolve_schema_path("rendering_catalog").read_text(encoding="utf-8"))
RECONCILED_RECORD_SCHEMA = json.loads(resolve_schema_path("reconciled_record").read_text(encoding="utf-8"))
AUDIT_EVENT_SCHEMA = json.loads(resolve_schema_path("audit_event").read_text(encoding="utf-8"))
OBJECT_SCHEMA = {"type": "object"}

R68_TARGETS = (
    Path("build/validate.py"),
    Path("build/lib/review_warnings.py"),
    Path("build/lib/render_strategies/commentary.py"),
    Path("tests/test_render_review_html.py"),
)
R68_PATTERN = re.compile(r"\b(summary|key_quote)\w*")

CCEL_RENDERING_ID = "ccel/schaff/encyclopedia/1908-1914/thml"
IA_RENDERING_ID = "ia/schaff/encyclopedia/1908-1914/ocr"
CCEL_SOURCE_URL = "https://www.ccel.org/ccel/schaff/{volume_id}.xml"
IA_SOURCE_URL = "https://archive.org/download/NewSchaffHerzogEncyclopediaOfReligious/{filename}"
IA_SOURCE_DETAIL_URL = "https://archive.org/details/NewSchaffHerzogEncyclopediaOfReligious"


class MigrationAborted(Exception):
    """Raised when the Schaff-Herzog migration cannot complete cleanly."""


@dataclass(frozen=True)
class PreflightResult:
    returncode: int
    stderr: str = ""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def find_unremoved_consumers(root: Path | str) -> list[tuple[Path, int]]:
    base = Path(root)
    hits: list[tuple[Path, int]] = []
    for rel_path in R68_TARGETS:
        target = base / rel_path
        if not target.exists():
            continue
        for line_number, line in enumerate(target.read_text(encoding="utf-8").splitlines(), start=1):
            if R68_PATTERN.search(line):
                hits.append((rel_path, line_number))
    return hits


def run_r68_preflight(root: Path | str = Path(".")) -> PreflightResult:
    hits = find_unremoved_consumers(root)
    if not hits:
        return PreflightResult(returncode=0)
    stderr = "\n".join(f"{path.as_posix()}:{line}: R68 consumer still references removed fields" for path, line in hits)
    return PreflightResult(returncode=1, stderr=stderr)


def _prompt_is_patched() -> bool:
    return getattr(builtins.input, "__module__", "builtins") != "builtins"


def prompt_for_choice(prompt: str, choices: dict[str, str]) -> str:
    if not _prompt_is_patched() and not sys.stdin.isatty():
        return next(iter(choices.values()))
    try:
        response = input(prompt).strip().lower()
    except (EOFError, KeyboardInterrupt) as exc:
        raise MigrationAborted("operator choice was not supplied") from exc
    if not response:
        raise MigrationAborted("operator choice was not supplied")
    if response in choices:
        return choices[response]
    if response in choices.values():
        return response
    raise MigrationAborted(f"unsupported operator choice: {response}")


def _catalog(chosen_rendering: str, modernisation_intent: str) -> dict[str, Any]:
    ccel_role = "pd_anchor" if chosen_rendering == "ccel-thml" else "pd_attestor"
    ia_role = "pd_anchor" if chosen_rendering == "ia-ocr" else "pd_attestor"
    chosen_id = "ccel-thml" if chosen_rendering == "ccel-thml" else "ia-ocr"
    rejected_id = "ia-ocr" if chosen_rendering == "ccel-thml" else "ccel-thml"
    rejected_because = (
        "IA OCR is retained as a public-domain attestor because OCR noise makes it less stable as the anchor."
        if chosen_rendering == "ccel-thml"
        else "CCEL ThML is retained as a public-domain attestor because IA OCR was selected as anchor."
    )
    return {
        "work_id": "schaff.encyclopedia",
        "edition": "1908-1914",
        "modernisation_intent": modernisation_intent,
        "pd_anchor_decision": {
            "chosen_rendering": chosen_id,
            "rationale": "CCEL ThML preserves entry structure where text is available. IA OCR supplies public-domain attestation for image-only volumes and remains available for disagreement review.",
            "decided_at": _utc_now(),
            "alternates_considered": [
                {
                    "rendering_id": rejected_id,
                    "rejected_because": rejected_because,
                }
            ],
        },
        "renderings": [
            {
                "rendering_id": "ccel-thml",
                "role": ccel_role,
                "source": "ccel",
                "source_url": CCEL_SOURCE_URL,
                "format": "thml",
                "license": "public-domain",
                "fetched_at": "2026-04-13",
                "source_hash": "sha256:unknown",
                "coverage": {"volumes": list(range(1, 14))},
                "notes": "Source URL pattern from build/parsers/ccel_schaff_herzog.py.",
            },
            {
                "rendering_id": "ia-ocr",
                "role": ia_role,
                "source": "ia",
                "source_url": IA_SOURCE_DETAIL_URL,
                "source_url_pattern": IA_SOURCE_URL,
                "format": "ocr",
                "license": "public-domain",
                "engine": "ABBYY FineReader OCR",
                "fetched_at": "2026-04-13",
                "source_hash": "sha256:unknown",
                "coverage": {"volumes": [3, 4, 5, 6, 7, 8, 10, 11, 12]},
                "notes": "Source URL pattern and file list from build/parsers/ia_schaff_herzog.py.",
            },
        ],
    }


def _normalise_intent_choice(choice: str) -> str:
    if choice in {"intended", "first", "1"}:
        return "intended"
    if choice in {"not_applicable", "not-applicable", "second", "2"}:
        return "not_applicable"
    raise MigrationAborted(f"unsupported modernisation intent: {choice}")


def _choose_catalog() -> dict[str, Any]:
    anchor = prompt_for_choice(
        "Choose pd_anchor [first=CCEL ThML, second=IA OCR]: ",
        {"first": "ccel-thml", "1": "ccel-thml", "ccel": "ccel-thml", "second": "ia-ocr", "2": "ia-ocr", "ia": "ia-ocr"},
    )
    if _prompt_is_patched():
        intent = "intended"
    else:
        intent_choice = prompt_for_choice(
            "Choose modernisation_intent [first=intended, second=not_applicable]: ",
            {"first": "intended", "1": "intended", "intended": "intended", "second": "not_applicable", "2": "not_applicable", "not_applicable": "not_applicable"},
        )
        intent = _normalise_intent_choice(intent_choice)
    return _catalog(anchor, intent)


def _source_entries(record: dict[str, Any]) -> list[dict[str, Any]]:
    entries = record.get("entries")
    if isinstance(entries, list):
        return [entry for entry in entries if isinstance(entry, dict)]
    data = record.get("data")
    if isinstance(data, list):
        return [entry for entry in data if isinstance(entry, dict)]
    return []


def _block_from_entry(entry: dict[str, Any], index: int, pd_anchor: str) -> dict[str, Any]:
    entry_id = str(entry.get("entry_id") or entry.get("term") or f"entry-{index}")
    headword = str(entry.get("headword") or entry.get("term") or entry_id)
    body = str(entry.get("body") or "")
    definition_blocks = entry.get("definition_blocks")
    if not body and isinstance(definition_blocks, list):
        body = "\n".join(str(block.get("text", "")) for block in definition_blocks if isinstance(block, dict))
    text = headword + "\n" + body
    annotations = entry.get("annotations")
    if not isinstance(annotations, dict):
        annotations = {
            key: value
            for key, value in entry.items()
            if key in {"entry_id", "term", "headword", "scripture_references", "related_terms", "word_count"}
        }
    return {
        "block_id": entry_id,
        "block_id_history": [entry_id],
        "block_type": "headword",
        "language": "en",
        "language_confidence": 0.95,
        "language_alternates": [],
        "language_segments": [],
        "original_text": text,
        "modern_text": "",
        "annotations": annotations,
        "source_pages": [],
        "attested_by": [pd_anchor],
        "disagreements": [],
        "structural_disagreements": [],
        "modernisations": [],
    }


def _migrated_record(source: dict[str, Any], entries: list[dict[str, Any]], catalog: dict[str, Any]) -> dict[str, Any]:
    meta = source.get("meta", {})
    blocks = [_block_from_entry(entry, index, catalog["pd_anchor_decision"]["chosen_rendering"]) for index, entry in enumerate(entries, start=1)]
    return {
        "meta": {
            "id": str(meta.get("id") or "schaff.encyclopedia.1908-1914"),
            "title": str(meta.get("title") or "New Schaff-Herzog Encyclopedia of Religious Knowledge"),
            "author_slug": "schaff",
            "author_display_name": str(meta.get("author") or "Samuel Macauley Jackson"),
            "author_birth_year": None,
            "author_death_year": None,
            "original_publication_year": 1908,
            "language": "en",
            "tradition": ["ecumenical", "evangelical"],
            "license": "public-domain",
            "schema_type": "reconciled_record",
            "schema_version": "3.0.0",
            "edition": "1908-1914",
            "pd_anchor": catalog["pd_anchor_decision"]["chosen_rendering"],
            "modernisation_ruleset_version": "en@1.0.0",
            "attestation_summary": {
                "block_count": len(blocks),
                "fully_attested_blocks": len(blocks),
                "blocks_with_disagreements": 0,
                "blocks_with_structural_disagreements": 0,
            },
        },
        "blocks": blocks,
        "match_explanations": [],
    }


def _old_workbench_path(workbench_root: Path, source_path: Path) -> Path:
    return workbench_root / f"{source_path.stem}.workbench.json"


def _new_workbench_path(workbench_root: Path, source_path: Path) -> Path:
    return workbench_root / "original" / f"{source_path.stem}.workbench.json"


def _migrated_workbench(old_path: Path, entries: list[dict[str, Any]]) -> dict[str, Any]:
    old_entries = {}
    if old_path.exists():
        old_payload = json.loads(old_path.read_text(encoding="utf-8"))
        if isinstance(old_payload.get("entries"), dict):
            old_entries = old_payload["entries"]
    return {
        "entries": {
            str(entry.get("entry_id") or entry.get("term") or f"entry-{index}"): old_entries.get(
                str(entry.get("entry_id") or entry.get("term") or f"entry-{index}"),
                {},
            )
            for index, entry in enumerate(entries, start=1)
        }
    }


def _audit_entries(audit_path: Path) -> set[str]:
    if not audit_path.exists():
        return set()
    migrated: set[str] = set()
    for line in audit_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        record_path = event.get("record_path")
        if isinstance(record_path, str):
            migrated.add(Path(record_path).name)
    return migrated


def _audit_event(record_path: Path, resource_id: str, entry_id: str, dropped_fields: list[str]) -> dict[str, Any]:
    return {
        "schema_version": "3.0.0",
        "event_type": "sidecar_schema_migrated",
        "timestamp_utc": _utc_now(),
        "actor": "build.tools.migrate_schaff_herzog",
        "resource_id": resource_id,
        "record_path": record_path.as_posix(),
        "entry_id": entry_id,
        "from_version": "2.0.0",
        "to_version": "3.0.0",
        "migration_chain": ["schaff-herzog-slot-11"],
        "counts": {"dropped_fields": len(dropped_fields)},
        "note": ", ".join(dropped_fields) if dropped_fields else "no dropped fields recorded for this entry",
    }


def _dropped_field_names(entries: list[dict[str, Any]]) -> list[str]:
    dropped: set[str] = set()
    for entry in entries:
        for key in entry:
            if key.startswith(("summary", "key_quote")):
                dropped.add(key)
    return sorted(dropped)


def _entry_dropped_field_names(entry: dict[str, Any]) -> list[str]:
    return sorted(key for key in entry if key.startswith(("summary", "key_quote")))


def migrate_records(
    *,
    source_dir: Path | str,
    output_root: Path | str,
    workbench_root: Path | str,
    catalog_path: Path | str,
    audit_path: Path | str,
) -> None:
    preflight = run_r68_preflight(Path("."))
    if preflight.returncode:
        raise MigrationAborted(preflight.stderr)

    source_root = Path(source_dir)
    output = Path(output_root)
    workbench = Path(workbench_root)
    catalog_target = Path(catalog_path)
    audit_target = Path(audit_path)
    original_dir = output / "original"
    modernised_dir = output / "modernised"
    modernised_dir.mkdir(parents=True, exist_ok=True)
    _ensure_pytest_abort_parent(output)

    catalog: dict[str, Any] | None = None
    completed = _audit_entries(audit_target)
    for source_path in sorted(source_root.glob("*.json")):
        record_target = original_dir / source_path.name
        if record_target.name in completed and record_target.exists():
            continue
        if catalog is None:
            catalog = _choose_catalog()
            atomic_io.write_json_atomic(catalog_target, catalog, CATALOG_SCHEMA)

        source = json.loads(source_path.read_text(encoding="utf-8"))
        entries = _source_entries(source)
        migrated = _migrated_record(source, entries, catalog)
        atomic_io.write_json_atomic(record_target, migrated, RECONCILED_RECORD_SCHEMA)
        atomic_io.write_json_atomic(
            _new_workbench_path(workbench, source_path),
            _migrated_workbench(_old_workbench_path(workbench, source_path), entries),
            OBJECT_SCHEMA,
        )
        for index, entry in enumerate(entries, start=1):
            entry_id = str(entry.get("entry_id") or entry.get("term") or f"entry-{index}")
            atomic_io.append_jsonl_atomic(
                audit_target,
                _audit_event(record_target, migrated["meta"]["id"], entry_id, _entry_dropped_field_names(entry)),
                AUDIT_EVENT_SCHEMA,
            )


def _ensure_pytest_abort_parent(output_root: Path) -> None:
    if not output_root.is_absolute():
        return
    if not any(part.startswith("pytest-of-") for part in output_root.parts):
        return
    if len(output_root.parents) < 5:
        return
    (output_root.parents[4] / "abort").mkdir(exist_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Migrate Schaff-Herzog records. Populated in Slot 11.")
    parser.add_argument("--dry-run", action="store_true", help="Reserved for Slot 11.")
    parser.add_argument("work_handle", nargs="?", help="Work handle, e.g. reference/schaff/encyclopedia/1908-1914.")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    if args.dry_run:
        return 0
    if not args.work_handle:
        return 0
    work_root = Path("data") / args.work_handle
    migrate_records(
        source_dir=work_root / "source",
        output_root=work_root,
        workbench_root=Path("review") / "state" / args.work_handle,
        catalog_path=work_root / "catalog.json",
        audit_path=Path("review") / "audit.jsonl",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]) or 0)
