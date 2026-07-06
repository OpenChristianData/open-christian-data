"""report.py -- OCR scan report writer.

Emits two files per scan:
  <source_id>_<date>.json  -- machine-readable candidate list (mutation-safe)
  <source_id>_<date>.md    -- human-readable context (read-only for reviewer)

The reviewer edits a separate <source_id>_<date>_approved.json file (not written here).
Import-safe: no file I/O at import time (PY-06).
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from build.tools.ocr_scanner.models import ScanResult


def write_report(
    scan_result: ScanResult,
    output_dir: Path,
    date_str: Optional[str] = None,
) -> tuple[Path, Path]:
    """Write JSON + Markdown report pair for a ScanResult.

    Args:
        scan_result:  The ScanResult from scanner.scan_entries().
        output_dir:   Directory in which to create the report files.
        date_str:     Optional YYYY-MM-DD override (used in tests for reproducibility).
                      Defaults to today in Australia/Melbourne timezone.

    Returns:
        (json_path, md_path) -- the two files created.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if date_str is None:
        date_str = datetime.now(tz=ZoneInfo("Australia/Melbourne")).strftime("%Y-%m-%d")

    stem = f"{scan_result.source_id}_{date_str}"
    json_path = output_dir / f"{stem}.json"
    md_path = output_dir / f"{stem}.md"

    _write_json(scan_result, json_path)
    _write_markdown(scan_result, md_path, date_str)

    return json_path, md_path


# ---------------------------------------------------------------------------
# JSON writer
# ---------------------------------------------------------------------------

def _write_json(scan_result: ScanResult, json_path: Path) -> None:
    """Write the machine-readable JSON report."""
    data = scan_result.to_dict()
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=True)
        f.write("\n")


# ---------------------------------------------------------------------------
# Markdown writer
# ---------------------------------------------------------------------------

def _write_markdown(scan_result: ScanResult, md_path: Path, date_str: str) -> None:
    """Write the human-readable Markdown context report (read-only for reviewer)."""
    lines: list[str] = []

    # Header
    lines.append(f"# OCR candidates -- {scan_result.source_id} -- {date_str}")
    lines.append("")
    by_tier = scan_result.candidates_by_tier()
    lines.append(
        f"Scanned: {scan_result.entries_scanned:,} entries. "
        f"Candidates: {len(scan_result.candidates)} "
        f"(Tier 1: {by_tier['tier1']}, "
        f"Tier 2: {by_tier['tier2']}, "
        f"Tier 3: {by_tier['tier3']})."
    )
    if scan_result.truncated:
        lines.append(f"**Truncated:** {scan_result.truncated_reason}")
    lines.append("")
    lines.append(
        "> This file is READ-ONLY context for the reviewer. "
        "To approve/reject candidates, edit the `_approved.json` file."
    )
    lines.append("")

    # Group candidates by tier, then by reason
    for tier_num in (1, 2, 3):
        tier_candidates = [c for c in scan_result.candidates if c.tier == tier_num]
        if not tier_candidates:
            continue

        tier_label = {1: "high confidence", 2: "heuristic", 3: "exploratory"}.get(tier_num, "")
        lines.append(f"## Tier {tier_num} -- {tier_label} ({len(tier_candidates)})")
        lines.append("")

        # Group by reason within tier
        reasons_seen: list[str] = []
        by_reason: dict[str, list] = {}
        for c in tier_candidates:
            if c.reason not in by_reason:
                reasons_seen.append(c.reason)
                by_reason[c.reason] = []
            by_reason[c.reason].append(c)

        for reason in reasons_seen:
            candidates = by_reason[reason]
            lines.append(f"### {reason} ({len(candidates)})")
            lines.append("")
            for c in candidates:
                suggestion_str = f" -> {c.suggestion}" if c.suggestion else " (no suggestion)"
                lines.append(f"**{c.id}** -- `{c.value}`{suggestion_str}  ({c.entry_id}, {c.occurrences} occurrence(s))")
                lines.append(
                    f"Context: ...{c.context_before} | `{c.value}` | {c.context_after}..."
                )
                lines.append("")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        f.write("\n")
