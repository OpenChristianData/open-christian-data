"""Rules-driven modernisation pipeline stages.

Slot 5 ships Transliterate only. Slot 6 adds Modernise here.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from ocd_kernel.lib.schema_enums import resolve_schema_path
from ocd_kernel.lib.source_transliteration_lexicons import load_source_transliteration_lexicons


_RULESET_DIR = Path(__file__).resolve().parent / "rulesets" / "transliteration"
_MODERNISE_RULESET_DIR = Path(__file__).resolve().parent / "rulesets"
_NON_LATIN_RE = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff\u0590-\u05ff]")
_GREEK_RE = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]+(?:\s+[\u0370-\u03ff\u1f00-\u1fff]+)*")
_HEBREW_RE = re.compile(r"[\u0590-\u05ff]+(?:\s+[\u0590-\u05ff]+)*")
_TOKEN_RE = re.compile(r"[A-Za-zÀ-ɏ]+")
_RULESET_LANGS = ("grc", "hbo")
_GREEK_COMBINING_SMOOTH = "\u0313"
_GREEK_COMBINING_ROUGH = "\u0314"
_GREEK_COMBINING_IOTA_SUBSCRIPT = "\u0345"
_HEBREW_MARK_RANGES = (
    range(0x0591, 0x05BE),
    range(0x05BF, 0x05C8),
)


def transliterate_record(record: dict) -> dict:
    """Apply source-transliteration detection and active transliteration."""
    rulesets = {lang: _load_ruleset(lang) for lang in _RULESET_LANGS}
    source_lexicons = {lang: _load_source_lexicon(lang) for lang in _RULESET_LANGS}
    audit_events: list[dict[str, Any]] = []

    for block in record.get("blocks", []):
        text = block.get("original_text", "")
        existing_segments = block.get("language_segments", [])
        preserved = [
            segment
            for segment in existing_segments
            if segment.get("editorial_override") is True
        ]

        source_segments = _detect_source_transliterations(text, source_lexicons)
        has_non_latin = _has_non_latin(text)
        if (
            block.get("language") == "en"
            and not has_non_latin
            and not source_segments
            and not preserved
        ):
            continue

        active_segments: list[dict[str, Any]] = []
        block_language = block.get("language")
        if block_language in _RULESET_LANGS and has_non_latin:
            transliteration = _transliterate_text(text, block_language, rulesets[block_language])
            active_segments.append(
                _language_segment(
                    text=text,
                    start=0,
                    end=len(text),
                    language=block_language,
                    original_script=text,
                    transliteration=transliteration,
                )
            )
            audit_events.append(
                _audit_event(record, block, "active_transliteration", block_language, text, transliteration)
            )
        else:
            for language, pattern in (("grc", _GREEK_RE), ("hbo", _HEBREW_RE)):
                for match in pattern.finditer(text):
                    original = match.group(0)
                    transliteration = _transliterate_text(original, language, rulesets[language])
                    active_segments.append(
                        _language_segment(
                            text=text,
                            start=match.start(),
                            end=match.end(),
                            language=language,
                            original_script=original,
                            transliteration=transliteration,
                        )
                    )
                    audit_events.append(
                        _audit_event(record, block, "active_transliteration", language, original, transliteration)
                    )

        block["language_segments"] = preserved + source_segments + active_segments

    _append_optional_audit(record, audit_events)
    return record


def _load_ruleset(language: str) -> dict[str, str]:
    path = _RULESET_DIR / f"{language}.yaml"
    entries = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return {str(entry["source"]): str(entry["target"]) for entry in entries}


def _load_source_lexicon(language: str) -> list[dict[str, Any]]:
    entries = load_source_transliteration_lexicons(language)
    return [entry for entry in entries if entry.get("enabled", True)]


def _has_non_latin(text: str) -> bool:
    return bool(_NON_LATIN_RE.search(text))


def _detect_source_transliterations(
    text: str,
    source_lexicons: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    for token_match in _TOKEN_RE.finditer(text):
        token = token_match.group(0)
        token_lower = token.lower()
        for language, entries in source_lexicons.items():
            for entry in entries:
                source_tokens = entry.get("source_tokens", [])
                if any(token_lower == str(source_token).lower() for source_token in source_tokens):
                    segments.append(
                        _language_segment(
                            text=text,
                            start=token_match.start(),
                            end=token_match.end(),
                            language=language,
                            original_script=None,
                            transliteration=token,
                            transliterated_from=language,
                        )
                    )
                    break
            else:
                continue
            break
    return segments


def _language_segment(
    *,
    text: str,
    start: int,
    end: int,
    language: str,
    original_script: str | None,
    transliteration: str,
    transliterated_from: str | None = None,
) -> dict[str, Any]:
    segment: dict[str, Any] = {
        "span": _token_span(text, start, end),
        "language": language,
        "original_script": original_script,
        "transliteration": transliteration,
    }
    if transliterated_from is not None:
        segment["transliterated_from"] = transliterated_from
    return segment


def _token_span(text: str, start: int, end: int) -> dict[str, int]:
    before = text[:start]
    covered = text[start:end]
    start_token = len(before.split())
    token_count = len(covered.split()) or 1
    return {"start_token": start_token, "end_token": start_token + token_count}


def _transliterate_text(text: str, language: str, ruleset: dict[str, str]) -> str:
    if language == "grc":
        return _normalise_spacing(_transliterate_greek(text, ruleset))
    if language == "hbo":
        return _normalise_spacing(_transliterate_hebrew(text, ruleset))
    return _normalise_spacing(text)


def _transliterate_greek(text: str, ruleset: dict[str, str]) -> str:
    output: list[str] = []
    for char in text:
        if char.isspace():
            output.append(" ")
            continue
        decomposed = unicodedata.normalize("NFD", char)
        base = decomposed[0]
        marks = decomposed[1:]
        prefix = ruleset.get(_GREEK_COMBINING_ROUGH, "") if _GREEK_COMBINING_ROUGH in marks else ""
        target = ruleset.get(base, base)
        suffix = ruleset.get(_GREEK_COMBINING_IOTA_SUBSCRIPT, "") if _GREEK_COMBINING_IOTA_SUBSCRIPT in marks else ""
        if _GREEK_COMBINING_SMOOTH in marks:
            prefix += ruleset.get(_GREEK_COMBINING_SMOOTH, "")
        output.append(prefix + target + suffix)
    return "".join(output)


def _transliterate_hebrew(text: str, ruleset: dict[str, str]) -> str:
    output: list[str] = []
    index = 0
    ordered_sources = sorted(ruleset, key=len, reverse=True)
    while index < len(text):
        char = text[index]
        if char.isspace():
            output.append(" ")
            index += 1
            continue
        match = next((source for source in ordered_sources if text.startswith(source, index)), None)
        if match is not None:
            output.append(ruleset[match])
            index += len(match)
            continue
        if _is_hebrew_mark(char):
            index += 1
            continue
        output.append(char)
        index += 1
    return "".join(output)


def _is_hebrew_mark(char: str) -> bool:
    codepoint = ord(char)
    return any(codepoint in mark_range for mark_range in _HEBREW_MARK_RANGES)


def _normalise_spacing(text: str) -> str:
    return " ".join(text.split())


def _audit_event(
    record: dict,
    block: dict,
    action: str,
    language: str,
    original: str,
    transliteration: str,
) -> dict[str, Any]:
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "actor": "transliterate_record",
        "resource_id": record.get("meta", {}).get("id", ""),
        "record_path": record.get("meta", {}).get("record_path", ""),
        "entry_id": block.get("block_id", ""),
        "event_type": action,
        "language": language,
        "original": original,
        "transliteration": transliteration,
    }


def _modernise_audit_event(
    record: dict,
    block: dict,
    rule_id: str,
    original: str,
    modern: str,
) -> dict[str, Any]:
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "actor": "modernise_record",
        "resource_id": record.get("meta", {}).get("id", ""),
        "record_path": record.get("meta", {}).get("record_path", ""),
        "entry_id": block.get("block_id", ""),
        "event_type": "modernise_rule_application",
        "rule_id": rule_id,
        "original": original,
        "modern": modern,
    }


def _append_optional_audit(record: dict, audit_events: list[dict[str, Any]]) -> None:
    audit_path_value = record.get("meta", {}).get("audit_path")
    if not audit_path_value or not audit_events:
        return
    audit_path = Path(audit_path_value)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("a", encoding="utf-8") as audit_file:
        for event in audit_events:
            audit_file.write(json.dumps(event, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Slot 6 — Modernise function
# ---------------------------------------------------------------------------


def modernise_record(record: dict) -> dict:
    """Apply English modernisation rules to a Reviewer-clean post-Transliterate record."""
    schema_type = record.get("meta", {}).get("schema_type", "")
    if schema_type not in ("reconciled_record", "modernised_record"):
        raise ValueError(
            f"modernise_record requires a post-Transliterate record, got schema_type '{schema_type}'"
        )
    ruleset_data = yaml.safe_load(
        (_MODERNISE_RULESET_DIR / "en.yaml").read_text(encoding="utf-8")
    ) or {}
    version = ruleset_data.get("version", "1.0.0")
    ruleset_id = f"en@{version}"
    enabled_rules = [r for r in ruleset_data.get("rules", []) if r.get("enabled", True)]

    audit_events: list[dict[str, Any]] = []
    new_blocks: list[dict[str, Any]] = []

    for block in record.get("blocks", []):
        original_text = block.get("original_text", "")
        existing_editorial = [
            m for m in block.get("modernisations", []) if m.get("rule_id") is None
        ]
        modern_text, rule_mods = _apply_modernisation_rules(original_text, enabled_rules, ruleset_id)
        for mod in rule_mods:
            audit_events.append(
                _modernise_audit_event(record, block, mod["rule_id"], mod["original"], mod["modern"])
            )
        new_blocks.append(
            {**block, "modern_text": modern_text, "modernisations": existing_editorial + rule_mods}
        )

    modernised: dict[str, Any] = {
        "meta": {
            **record.get("meta", {}),
            "schema_type": "modernised_record",
            "modernisation_ruleset_version": ruleset_id,
            "paired_with": record.get("meta", {}).get("id", ""),
        },
        "blocks": new_blocks,
        "match_explanations": record.get("match_explanations", []),
    }
    _append_optional_audit(record, audit_events)
    return modernised


def _apply_modernisation_rules(
    text: str, rules: list[dict[str, Any]], ruleset_id: str
) -> tuple[str, list[dict[str, Any]]]:
    modern = text
    mods: list[dict[str, Any]] = []
    for rule in rules:
        rule_id = rule.get("id", "")
        kind = rule.get("kind", "")
        if kind == "table":
            modern, new_mods = _apply_mod_table(modern, rule, rule_id, ruleset_id)
        elif kind == "regex":
            modern, new_mods = _apply_mod_regex(modern, rule, rule_id, ruleset_id)
        elif kind == "literal":
            modern, new_mods = _apply_mod_literal(modern, rule, rule_id, ruleset_id)
        else:
            continue
        mods.extend(new_mods)
    return modern, mods


def _apply_mod_table(
    text: str, rule: dict, rule_id: str, ruleset_id: str
) -> tuple[str, list[dict[str, Any]]]:
    table = rule.get("table", {})
    tokens = text.split()
    new_tokens = list(tokens)
    mods: list[dict[str, Any]] = []
    for i, token in enumerate(tokens):
        stripped = token.strip(".,;:!?\"'()")
        lower = stripped.lower()
        if lower in table:
            replacement = table[lower]
            if stripped and stripped[0].isupper():
                replacement = replacement[0].upper() + replacement[1:]
            new_tokens[i] = token.replace(stripped, replacement, 1)
            mods.append(_mod_entry(rule_id, ruleset_id, i, i + 1, stripped, replacement))
    return " ".join(new_tokens), mods


def _apply_mod_regex(
    text: str, rule: dict, rule_id: str, ruleset_id: str
) -> tuple[str, list[dict[str, Any]]]:
    pattern = rule.get("pattern", "")
    replacement = rule.get("replacement", "")
    exceptions_lower = {e.lower() for e in rule.get("exceptions", [])}
    if not pattern:
        return text, []
    compiled = re.compile(pattern)

    def _replace_fn(m: re.Match) -> str:
        matched = m.group(0)
        if matched.lower() in exceptions_lower:
            return matched
        return m.expand(replacement)

    new_text = compiled.sub(_replace_fn, text)
    if new_text == text:
        return text, []
    orig_tokens = text.split()
    new_tokens = new_text.split()
    mods: list[dict[str, Any]] = []
    for i, (orig, new) in enumerate(zip(orig_tokens, new_tokens, strict=False)):
        if orig != new:
            mods.append(_mod_entry(rule_id, ruleset_id, i, i + 1, orig, new))
    return new_text, mods


def _apply_mod_literal(
    text: str, rule: dict, rule_id: str, ruleset_id: str
) -> tuple[str, list[dict[str, Any]]]:
    pattern = rule.get("pattern", "")
    replacement = rule.get("replacement", "")
    if not pattern or pattern not in text:
        return text, []
    new_text = text.replace(pattern, replacement)
    orig_tokens = text.split()
    new_tokens = new_text.split()
    mods: list[dict[str, Any]] = []
    for i, (orig, new) in enumerate(zip(orig_tokens, new_tokens, strict=False)):
        if orig != new:
            mods.append(_mod_entry(rule_id, ruleset_id, i, i + 1, orig, new))
    return new_text, mods


def _mod_entry(
    rule_id: str, ruleset_id: str, start: int, end: int, original: str, modern: str
) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "rule_version": ruleset_id,
        "span": {"start_token": start, "end_token": end},
        "original": original,
        "modern": modern,
    }


if __name__ == "__main__":
    import json as _json
    import sys

    from jsonschema import Draft202012Validator

    _schema_path = resolve_schema_path("modernised_record")
    _bootstrap_dir = Path(__file__).resolve().parent.parent.parent.parent / "tests" / "fixtures" / "modernise" / "bootstrap"

    _schema = _json.loads(_schema_path.read_text(encoding="utf-8"))
    _validator = Draft202012Validator(_schema)

    _paths = [Path(p) for p in sys.argv[1:]] if sys.argv[1:] else sorted(_bootstrap_dir.glob("*.json"))

    _exit_code = 0
    for _fixture_path in _paths:
        _record = _json.loads(_fixture_path.read_text(encoding="utf-8"))
        _modernised = modernise_record(_record)
        _errors = list(_validator.iter_errors(_modernised))
        if _errors:
            print(f"FAIL {_fixture_path.name}: {_errors[0].message}")
            _exit_code = 1
        else:
            print(f"OK {_fixture_path.name}")

    sys.exit(_exit_code)
