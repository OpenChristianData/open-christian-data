"""Generate text-confidence reports from review-state sidecars."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib import historical_lexicon
from build.lib import review_state  # noqa: E402
from build.lib.lang_classifier import classify_spans  # noqa: E402
from build.lib.text_extractor import extract_text  # noqa: E402
from build.lib.paths import REPO_ROOT  # noqa: E402


CONFIDENCE_AXES = ("structural_fidelity", "text_fidelity", "edition_provenance")
SCHEMAS_DIR = REPO_ROOT / "schemas" / "v1"


def build_confidence_report(
    record_path: Path,
    sidecar_path: Path | None = None,
    **_legacy_inputs: Any,
) -> dict[str, Any]:
    """Build a confidence report from the sidecar attached to ``record_path``."""
    record_path = Path(record_path)
    record = json.loads(record_path.read_text(encoding="utf-8"))
    if sidecar_path is None:
        sidecar_path = review_state.derive_sidecar_path(record_path, repo_root=REPO_ROOT)
    sidecar = review_state.load_sidecar(sidecar_path) if Path(sidecar_path).exists() else _empty_sidecar(record, record_path)
    schema = review_state.load_schema()
    tiers = _confidence_tiers(schema)
    confidence = {axis: str((sidecar.get("confidence") or {}).get(axis) or "unverified") for axis in CONFIDENCE_AXES}
    lexicon_blockers = _seed_only_lexicon_blockers(record, confidence)
    if lexicon_blockers and confidence["text_fidelity"] == "reference-grade":
        confidence["text_fidelity"] = "human-reviewed"

    return {
        "resource_id": str((record.get("meta") or {}).get("id") or sidecar.get("record_resource_id") or ""),
        "title": (record.get("meta") or {}).get("title"),
        "source_file": str(record_path),
        "sidecar_file": str(sidecar_path),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tier": _overall_tier(confidence, tiers),
        "available_tiers": tiers,
        "confidence_axes": confidence,
        "tier_evidence_rules": _tier_evidence_rules(schema, tiers),
        "missing_evidence": _missing_evidence(confidence),
        "blockers": _blockers(confidence) + lexicon_blockers,
    }


def write_confidence_reports(report: dict[str, Any], json_path: Path, markdown_path: Path) -> tuple[Path, Path]:
    json_path = Path(json_path)
    markdown_path = Path(markdown_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown_report(report), encoding="utf-8")
    return json_path, markdown_path


def render_markdown_report(report: dict[str, Any]) -> str:
    axes = report["confidence_axes"]
    missing = report["missing_evidence"] or ["No missing sidecar confidence evidence reported."]
    blockers = report["blockers"] or ["No reference-grade blockers under current sidecar axes."]
    return "\n".join(
        [
            f"# Text Confidence Report: {report['resource_id']}",
            "",
            f"- Tier: `{report['tier']}`",
            f"- Source file: `{report['source_file']}`",
            f"- Sidecar file: `{report['sidecar_file']}`",
            f"- Generated at: `{report['generated_at']}`",
            "",
            "## Confidence Axes",
            "",
            *[f"- {axis}: `{axes[axis]}`" for axis in CONFIDENCE_AXES],
            "",
            "## Tier Evidence Rules",
            "",
            *[f"- {tier}: {report['tier_evidence_rules'][tier]}" for tier in report["available_tiers"]],
            "",
            "## Missing Evidence",
            "",
            *[f"- {item}" for item in missing],
            "",
            "## Reference-Grade Blockers",
            "",
            *[f"- {item}" for item in blockers],
            "",
            "This report summarises sidecar state only. It does not certify textual correctness.",
            "",
        ]
    )


def _empty_sidecar(record: dict[str, Any], record_path: Path) -> dict[str, Any]:
    record_bytes = json.dumps(record, sort_keys=True, ensure_ascii=False).encode("utf-8")
    meta = record.get("meta") if isinstance(record, dict) else {}
    return review_state.empty_sidecar(
        record_path=str(record_path),
        record_resource_id=str((meta or {}).get("id") or "unknown"),
        record_checksum_sha256=hashlib.sha256(record_bytes).hexdigest(),
        parser_version_seen=str(((meta or {}).get("provenance") or {}).get("processing_script_version") or "unknown@unknown"),
    )


def _confidence_tiers(schema: dict[str, Any]) -> list[str]:
    tiers = (((schema.get("$defs") or {}).get("confidence_tier") or {}).get("enum") or [])
    if not all(isinstance(tier, str) for tier in tiers):
        raise ValueError("review_state schema does not expose confidence_tier enum")
    return list(tiers)


def _tier_evidence_rules(schema: dict[str, Any], tiers: list[str]) -> dict[str, str]:
    axes = ", ".join(CONFIDENCE_AXES)
    schema_version = schema.get("properties", {}).get("schema_version", {}).get("description", "sidecar schema")
    return {
        tier: f"Declared by review_state sidecar confidence axes ({axes}); allowed by schema tier enum. Schema note: {schema_version}"
        for tier in tiers
    }


def _overall_tier(confidence: dict[str, str], tiers: list[str]) -> str:
    rank = {tier: index for index, tier in enumerate(tiers)}
    axis_tiers = [tier for tier in confidence.values() if tier in rank]
    if not axis_tiers:
        return "unverified"
    return min(axis_tiers, key=lambda tier: rank[tier])


def _missing_evidence(confidence: dict[str, str]) -> list[str]:
    return [f"{axis} remains unverified in the sidecar." for axis, tier in confidence.items() if tier == "unverified"]


def _blockers(confidence: dict[str, str]) -> list[str]:
    return [
        f"{axis} is {tier}, not reference-grade."
        for axis, tier in confidence.items()
        if tier != "reference-grade"
    ]


def _seed_only_lexicon_blockers(record: dict[str, Any], confidence: dict[str, str]) -> list[str]:
    if confidence.get("text_fidelity") != "reference-grade":
        return []
    dominant_lang = _dominant_non_english_lang(record)
    if dominant_lang is None:
        return []
    try:
        status = historical_lexicon.coverage_status(dominant_lang)
    except ValueError:
        return []
    if status != "production":
        return [
            f"text_fidelity reference-grade blocked: dominant language {dominant_lang} uses {status} historical lexicon coverage."
        ]
    return []


def _dominant_non_english_lang(record: dict[str, Any]) -> str | None:
    totals: dict[str, int] = {}
    total_chars = 0
    try:
        extracted = list(extract_text(record, SCHEMAS_DIR))
    except ValueError:
        return None
    for _entry_id, _field_path, text, _lang_hint, lang_spans in extracted:
        total_chars += len("".join(text.split()))
        spans = lang_spans or classify_spans(text)
        for span in spans:
            lang = str(span.get("lang") or "")
            confidence = str(span.get("confidence") or "")
            if lang == "en" or confidence not in {"medium", "high"}:
                continue
            try:
                start = int(span["start"])
                end = int(span["end"])
            except (KeyError, TypeError, ValueError):
                continue
            totals[lang] = totals.get(lang, 0) + max(0, end - start)
    if not totals or total_chars <= 0:
        return None
    dominant_lang, dominant_chars = max(totals.items(), key=lambda item: item[1])
    if dominant_chars / total_chars > 0.5:
        return dominant_lang
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record_path", type=Path)
    parser.add_argument("--sidecar", type=Path, help="Optional explicit review/state sidecar path.")
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_confidence_report(args.record_path, sidecar_path=args.sidecar)
    write_confidence_reports(report, args.output_json, args.output_md)
    print(args.output_json)
    print(args.output_md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
