"""Measure historical-lexicon coverage against resource JSON files."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib.historical_lexicon import SUPPORTED_LANGS, archaic_forms, coverage_status  # noqa: E402
from build.lib.lang_classifier import classify_spans  # noqa: E402
from build.lib.text_extractor import extract_text  # noqa: E402
from build.lib.paths import REPO_ROOT  # noqa: E402


SCHEMAS_DIR = REPO_ROOT / "schemas" / "v1"
OUTPUT_DIR = REPO_ROOT / "build" / "lexicon-coverage-reports"
CONVERGENCE_THRESHOLD = 2
MIN_PRODUCTION_RUNS = 3


def build_coverage_report(resource_paths: list[Path], lexicon: str, runs: int) -> dict[str, Any]:
    if lexicon not in SUPPORTED_LANGS:
        raise ValueError(f"Unsupported lexicon {lexicon!r}; choose one of {', '.join(SUPPORTED_LANGS)}")
    if runs < 1:
        raise ValueError("--runs must be >= 1")

    corpus_texts = _extract_corpus_texts(resource_paths)
    segment_cache: dict[tuple[int, str], list[str]] = {}
    snapshots = [_unmatched_top_50(corpus_texts, lexicon, segment_cache) for _ in range(runs)]
    changes = _top_50_changes(snapshots)
    convergence = _convergence_check(resource_paths, runs, changes)
    declared_status = coverage_status(lexicon)
    effective_status = declared_status
    if declared_status == "production" and not convergence["passed"]:
        effective_status = "candidate_pending_convergence"

    return {
        "schema_version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "lexicon": lexicon,
        "resource_paths": [str(path) for path in resource_paths],
        "unmatched_top_50": snapshots[-1],
        "convergence_check": convergence,
        "declared_coverage_status": declared_status,
        "lexicon_status": effective_status,
        "run_count": runs,
    }


def write_report(report: dict[str, Any], out: Path | None = None) -> Path:
    target = out or _default_report_path(str(report["lexicon"]))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def _extract_corpus_texts(resource_paths: list[Path]) -> list[tuple[str, list[dict[str, Any]]]]:
    texts: list[tuple[str, list[dict[str, Any]]]] = []
    for resource_path in resource_paths:
        record = json.loads(resource_path.read_text(encoding="utf-8"))
        for _entry_id, _field_path, text, _lang_hint, lang_spans in extract_text(record, SCHEMAS_DIR):
            texts.append((text, lang_spans))
    return texts


def _unmatched_top_50(
    corpus_texts: list[tuple[str, list[dict[str, Any]]]],
    lang: str,
    segment_cache: dict[tuple[int, str], list[str]],
) -> list[dict[str, Any]]:
    lexicon_keys = {key.casefold() for key in archaic_forms(lang)}
    counts: Counter[str] = Counter()
    for index, (text, lang_spans) in enumerate(corpus_texts):
        cache_key = (index, lang)
        if cache_key not in segment_cache:
            segment_cache[cache_key] = _segments_for_lang(text, lang, lang_spans)
        for segment in segment_cache[cache_key]:
            for candidate in _candidate_forms(segment, lang):
                folded = candidate.casefold()
                if folded in lexicon_keys:
                    continue
                counts[candidate] += 1
    return [
        {"surface": surface, "count": count}
        for surface, count in sorted(counts.items(), key=lambda item: (-item[1], item[0].casefold()))[:50]
    ]


def _segments_for_lang(text: str, lang: str, lang_spans: list[dict[str, Any]] | None = None) -> list[str]:
    spans = lang_spans or classify_spans(text)
    if lang == "en":
        excluded = [
            (int(span["start"]), int(span["end"]))
            for span in spans
            if span.get("lang") != "en" and span.get("confidence") in {"medium", "high"}
        ]
        return _inverse_segments(text, excluded)
    selected = [
        text[int(span["start"]) : int(span["end"])]
        for span in spans
        if span.get("lang") == lang and _span_has_offsets(span, len(text))
    ]
    return selected


def _candidate_forms(text: str, lang: str) -> list[str]:
    if lang == "la":
        return re.findall(r"(?<!\w)[A-Za-z]{1,8}\.(?!\w)", text)
    if lang in {"grc", "hbo_latn"}:
        return [text] if text.strip() else []
    tokens = re.findall(r"(?<!\w)[A-Za-z][A-Za-z'-]{2,}(?!\w)", text)
    return [token for token in tokens if _looks_archaic_english(token)]


def _looks_archaic_english(token: str) -> bool:
    if token[:1].isupper():
        return False
    lowered = token.casefold().strip("'")
    if lowered.endswith("tieth") or lowered in {"beth", "teeth", "eth", "leth", "shibboleth", "bosheth", "kapporeth", "seth"}:
        return False
    return bool(
        re.search(r"eth$", lowered)
        or re.search(r"(defence|offence|pretence|expence|connexion)", lowered)
        or lowered.startswith(("persw", "intreat", "enquir", "expenc", "antient"))
        or lowered in {"thou", "thee", "thy", "thine", "ye", "hath", "doth", "saith", "shew", "shewed"}
    )


def _inverse_segments(text: str, excluded: list[tuple[int, int]]) -> list[str]:
    if not excluded:
        return [text]
    segments: list[str] = []
    cursor = 0
    for start, end in sorted(excluded):
        if start > cursor:
            segments.append(text[cursor:start])
        cursor = max(cursor, end)
    if cursor < len(text):
        segments.append(text[cursor:])
    return segments


def _span_has_offsets(span: dict[str, Any], text_length: int) -> bool:
    try:
        start = int(span["start"])
        end = int(span["end"])
    except (KeyError, TypeError, ValueError):
        return False
    return 0 <= start < end <= text_length


def _top_50_changes(snapshots: list[list[dict[str, Any]]]) -> list[int]:
    changes: list[int] = []
    for previous, current in zip(snapshots, snapshots[1:], strict=False):
        previous_set = {item["surface"] for item in previous}
        current_set = {item["surface"] for item in current}
        changes.append(len(previous_set.symmetric_difference(current_set)))
    return changes


def _convergence_check(resource_paths: list[Path], runs: int, changes: list[int]) -> dict[str, Any]:
    last_change_count = changes[-1] if changes else None
    passed = runs >= MIN_PRODUCTION_RUNS and last_change_count is not None and last_change_count <= CONVERGENCE_THRESHOLD
    reason = None if passed else "production_status_requires_three_runs_with_last_top_50_change_count_at_or_below_2"
    return {
        "passed": passed,
        "threshold": CONVERGENCE_THRESHOLD,
        "minimum_runs": MIN_PRODUCTION_RUNS,
        "changes_between_runs": changes,
        "last_top_50_change_count": last_change_count,
        "corpus_fingerprint": _corpus_fingerprint(resource_paths),
        "refusal_reason": reason,
    }


def _corpus_fingerprint(resource_paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(resource_paths, key=lambda item: str(item)):
        digest.update(str(path).replace("\\", "/").encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _default_report_path(lang: str) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    return OUTPUT_DIR / f"{lang}-{timestamp}.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resource-paths", nargs="+", type=Path, required=True)
    parser.add_argument("--lexicon", choices=SUPPORTED_LANGS, required=True)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--out", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_coverage_report(args.resource_paths, args.lexicon, args.runs)
    print(write_report(report, args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
