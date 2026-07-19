"""Historical lexicon warning producer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ocd_kernel.lib.historical_lexicon import scan_historical_variants
from ocd_kernel.lib.lang_classifier import classify_spans
from ocd_kernel.lib.text_extractor import extract_text
from build.lib.warning_producers import WARNING_OUTPUT_SCHEMA, build_warning


PRODUCER_ID = "historical_lexicon"
SIGNATURE_VERSION = 1
WARNING_CODES = {
    "archaic_variant": {
        "severity": "info",
        "description": "Historical spelling or naming variant detected.",
        "signature_fields": ["entry_id", "field_path", "code", "lang", "archaic_form"],
    },
}
APPLIES_TO_RESOURCE_TYPES = None
REQUIRES_CAPABILITIES = {}
CONSUMES = []
PRODUCES_SCHEMA = WARNING_OUTPUT_SCHEMA
SCOPE = "record_local"
SCHEMAS_DIR = Path(__file__).resolve().parents[3] / "schemas" / "v1"


def run(record: dict, meta: dict, upstream_outputs: dict) -> dict:
    warnings: list[dict[str, Any]] = []
    for entry_id, field_path, text, lang_hint, lang_spans in extract_text(record, SCHEMAS_DIR):
        effective_spans = lang_spans or classify_spans(text)
        for match in scan_historical_variants(text, lang_hint=lang_hint, lang_spans=effective_spans):
            evidence = match.to_record()
            evidence.update(
                {
                    "archaic_form": match.surface,
                    "suggested_modern_form": match.normalised,
                    "lang_hint": match.lang,
                    "confidence_band": match.confidence_band or "default",
                }
            )
            warnings.append(
                build_warning(
                    producer=__import__(__name__, fromlist=[""]),
                    code="archaic_variant",
                    entry_id=entry_id or None,
                    field_path=field_path,
                    message=f"{entry_id or 'Entry'}: {match.lang} historical variant {match.surface} -> {match.normalised}.",
                    evidence=evidence,
                )
            )
    return {"warnings": warnings}
