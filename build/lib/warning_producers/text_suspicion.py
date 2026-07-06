"""Universal suspicious text warning producer."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from pathlib import Path
from typing import Any

from build.lib.text_extractor import extract_text
from build.lib.warning_producers import WARNING_OUTPUT_SCHEMA, build_warning


PRODUCER_ID = "text_suspicion"
SIGNATURE_VERSION = 1
WARNING_CODES = {
    "replacement_character": {
        "severity": "warning",
        "description": "Text contains Unicode replacement characters.",
        "signature_fields": ["entry_id", "field_path", "code"],
    },
    "possible_broken_hyphenation": {
        "severity": "warning",
        "description": "Text may contain a line or token break after a hyphen.",
        "signature_fields": ["entry_id", "field_path", "code", "surface"],
    },
    "odd_double_quotes": {
        "severity": "warning",
        "description": "Text contains an odd number of double quotes.",
        "signature_fields": ["entry_id", "field_path", "code"],
    },
    "repeated_paragraph": {
        "severity": "warning",
        "description": "The same paragraph appears more than once in a resource.",
        "signature_fields": ["code", "surface"],
    },
    "likely_ocr_junk_sequence": {
        "severity": "warning",
        "description": "Text contains a likely OCR junk sequence.",
        "signature_fields": ["entry_id", "field_path", "code", "surface"],
    },
    "suspiciously_short": {
        "severity": "info",
        "description": "Text has fewer than three words.",
        "signature_fields": ["entry_id", "field_path", "code"],
    },
    "suspiciously_long": {
        "severity": "info",
        "description": "Text has more than 1500 words.",
        "signature_fields": ["entry_id", "field_path", "code"],
    },
}
APPLIES_TO_RESOURCE_TYPES = None
REQUIRES_CAPABILITIES = {}
CONSUMES = []
PRODUCES_SCHEMA = WARNING_OUTPUT_SCHEMA
SCOPE = "record_local"
SHORT_THRESHOLD = 3
LONG_THRESHOLD = 1500
SCHEMAS_DIR = Path(__file__).resolve().parents[3] / "schemas" / "v1"
LONG_FORM_FIELD_PREFIXES = ("definition_blocks.",)
MAX_WARNINGS_BY_RESOURCE_TYPE = {
    "encyclopedia": {
        "possible_broken_hyphenation": 150,
        "suspiciously_short": 100,
        "odd_double_quotes": 100,
        "repeated_paragraph": 100,
        "likely_ocr_junk_sequence": 100,
        "suspiciously_long": 10,
    }
}


def run(record: dict, meta: dict, upstream_outputs: dict) -> dict:
    warnings: list[dict[str, Any]] = []
    extracted = list(extract_text(record, SCHEMAS_DIR))
    paragraph_counts = _paragraph_counts(extracted)
    warned_paragraphs: set[str] = set()

    for entry_id, field_path, text, _lang_hint, _lang_spans in extracted:
        entry_id_or_none = entry_id or None
        label = entry_id or "Entry"
        word_count = len(text.split())
        if "\ufffd" in text:
            warnings.append(
                _warning(
                    "replacement_character",
                    entry_id_or_none,
                    field_path,
                    f"{label}: replacement character found.",
                    {"snippet": _snippet(text, "\ufffd")},
                )
            )
        hyphen_match = re.search(r"\b\w+-\s+\w+\b", text)
        if hyphen_match:
            surface = hyphen_match.group(0)
            warnings.append(
                _warning(
                    "possible_broken_hyphenation",
                    entry_id_or_none,
                    field_path,
                    f"{label}: possible broken hyphenation.",
                    {"surface": surface, "snippet": _regex_snippet(text, hyphen_match)},
                )
            )
        if text.count('"') % 2 == 1:
            warnings.append(
                _warning(
                    "odd_double_quotes",
                    entry_id_or_none,
                    field_path,
                    f"{label}: odd number of double quotes.",
                    None,
                )
            )
        junk_match = re.search(r"(?:[|\\/_~^`]{3,}|\b[A-Za-z0-9]{28,}\b)", text)
        if junk_match:
            surface = junk_match.group(0)
            warnings.append(
                _warning(
                    "likely_ocr_junk_sequence",
                    entry_id_or_none,
                    field_path,
                    f"{label}: likely OCR junk sequence.",
                    {"surface": surface, "snippet": _regex_snippet(text, junk_match)},
                )
            )
        if _code_applies_to_field("suspiciously_short", field_path) and 0 < word_count < SHORT_THRESHOLD:
            warnings.append(
                _warning(
                    "suspiciously_short",
                    entry_id_or_none,
                    field_path,
                    f"{label}: suspiciously short text field.",
                    {"word_count": word_count},
                )
            )
        if _code_applies_to_field("suspiciously_long", field_path) and word_count > LONG_THRESHOLD:
            warnings.append(
                _warning(
                    "suspiciously_long",
                    entry_id_or_none,
                    field_path,
                    f"{label}: suspiciously long text field.",
                    {"word_count": word_count},
                )
            )
        for paragraph in _paragraphs(text):
            key = _paragraph_key(paragraph)
            if paragraph_counts[key] <= 1 or key in warned_paragraphs:
                continue
            warned_paragraphs.add(key)
            surface = hashlib.sha256(key.encode()).hexdigest()[:12]
            warnings.append(
                _warning(
                    "repeated_paragraph",
                    entry_id_or_none,
                    field_path,
                    f"{label}: repeated paragraph within this resource.",
                    {"surface": surface, "snippet": _truncate(paragraph)},
                )
            )
    return {"warnings": _apply_reviewability_caps(warnings, str(meta.get("resource_type") or ""))}


def _code_applies_to_field(code: str, field_path: str | None) -> bool:
    if code not in {"suspiciously_short", "suspiciously_long"}:
        return True
    if not field_path:
        return False
    return field_path == "commentary_text" or field_path.startswith(LONG_FORM_FIELD_PREFIXES)


def _apply_reviewability_caps(warnings: list[dict[str, Any]], resource_type: str) -> list[dict[str, Any]]:
    caps = MAX_WARNINGS_BY_RESOURCE_TYPE.get(resource_type)
    if not caps:
        return warnings
    emitted_by_code: Counter[str] = Counter()
    capped: list[dict[str, Any]] = []
    for warning in warnings:
        code = str(warning.get("code") or "")
        limit = caps.get(code)
        if limit is not None and emitted_by_code[code] >= limit:
            continue
        capped.append(warning)
        emitted_by_code[code] += 1
    return capped


def _warning(
    code: str,
    entry_id: str | None,
    field_path: str | None,
    message: str,
    evidence: dict[str, Any] | None,
) -> dict[str, Any]:
    return build_warning(
        producer=__import__(__name__, fromlist=[""]),
        code=code,
        entry_id=entry_id,
        field_path=field_path,
        message=message,
        evidence=evidence,
    )


def _paragraph_counts(extracted: list[tuple[str, str, str, str | None, list]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for _entry_id, _field_path, text, _lang_hint, _lang_spans in extracted:
        counts.update(_paragraph_key(paragraph) for paragraph in _paragraphs(text))
    return counts


def _paragraphs(text: str) -> list[str]:
    return [paragraph.strip() for paragraph in re.split(r"\n\s*\n+", text) if paragraph.strip()]


def _paragraph_key(paragraph: str) -> str:
    return re.sub(r"\s+", " ", paragraph).strip()


def _snippet(text: str, marker: str) -> str:
    index = text.find(marker)
    if index == -1:
        return _truncate(text)
    start = max(0, index - 40)
    end = min(len(text), index + len(marker) + 40)
    return _truncate(text[start:end])


def _regex_snippet(text: str, match: re.Match[str]) -> str:
    start = max(0, match.start() - 40)
    end = min(len(text), match.end() + 40)
    return _truncate(text[start:end])


def _truncate(text: str, limit: int = 180) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: limit - 3]}..."
