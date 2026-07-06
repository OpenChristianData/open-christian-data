"""Shared parser-framework helpers.

Centralises checks that any parser with a WORK_CONFIG entry should run before
emitting structured output. Keeping these here lets the rule live in code rather
than only in `.claude/rules/parser-source-evidence.md`.

Public surface:

    assert_source_evidence(cfg, text)
        Confirm every string in `cfg["expected_source_evidence"]` appears in the
        raw source text. Raises ValueError on miss. Catches wrong-edition cases
        that schema validation can't (translator/year/author align but the
        edition is wrong).

    assert_evidence_for_synthetic_boundaries(cfg)
        Config-time guard. When a WORK_CONFIG entry declares
        `has_synthetic_boundaries: True` (TOC marker, OCR-corrupt heading like
        CHAPTLR, manual section override) it must also declare a non-empty
        `expected_source_evidence` list. Raises ValueError otherwise.

Both helpers raise ValueError so existing per-parser error handling that
catches ValueError continues to work without change.
"""

from __future__ import annotations


def assert_source_evidence(cfg: dict, text: str) -> None:
    needles = cfg.get("expected_source_evidence", [])
    missing = [needle for needle in needles if needle not in text]
    if missing:
        slug = cfg.get("slug") or cfg.get("work_id") or "<unknown>"
        raise ValueError(f"{slug}: missing expected source evidence: {missing}")


def assert_evidence_for_synthetic_boundaries(cfg: dict) -> None:
    if not cfg.get("has_synthetic_boundaries"):
        return
    if cfg.get("expected_source_evidence"):
        return
    slug = cfg.get("slug") or cfg.get("work_id") or "<unknown>"
    raise ValueError(
        f"{slug}: has_synthetic_boundaries=True requires a non-empty "
        f"expected_source_evidence list (see .claude/rules/parser-source-evidence.md)"
    )
