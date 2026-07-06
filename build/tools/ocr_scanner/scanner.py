"""scanner.py -- OCR scanner pipeline for OCD JSON corpus files.

Loads per-source configs, applies detector functions from patterns.py,
returns ScanResult. Never auto-corrects; produces a candidate list only.

Import-safe: no file I/O, no side effects at import time (PY-06).
"""
from __future__ import annotations

import json
import math
import re
import sys
from datetime import datetime, tzinfo
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from build.tools.ocr_scanner.models import Candidate, ScanResult
from build.tools.ocr_scanner import patterns as pat

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_SCANNER_DIR = Path(__file__).resolve().parent
_CONFIGS_DIR = _SCANNER_DIR / "configs"

# ---------------------------------------------------------------------------
# Detector dispatch table -- maps pattern_set name to list of (reason, func) pairs.
# Tier 3 detectors are NOT listed here; they are appended when tier3_enabled=True.
# ---------------------------------------------------------------------------

_DETECTORS_BY_PATTERN_SET: dict[str, list[tuple[str, object]]] = {
    "ia_djvu": [
        ("digit_in_letter", pat.detect_digit_in_letter),
        ("ligature_bracket", pat.detect_ligature_bracket),
        ("stray_pipe_backslash", pat.detect_stray_pipe_backslash),
        ("short_allcaps_orphan", pat.detect_short_allcaps_orphan),
        ("apparent_space_insertion", pat.detect_apparent_space_insertion),
        ("apparent_space_deletion", pat.detect_apparent_space_deletion),
    ],
    "ccel_thml": [
        ("entity_leak", pat.detect_entity_leak),
        ("unusual_bigram", pat.detect_unusual_bigram),
    ],
    "pdf": [],  # placeholder -- no PDF source in OCD as of 2026-04-15
    "html_transcription": [],  # clean HTML/transcription -- no OCR artifacts expected
}

# Tier 3 detectors -- only appended to the run list when tier3_enabled=True in config.
_TIER3_DETECTORS_BY_PATTERN_SET: dict[str, list[tuple[str, object]]] = {
    "ia_djvu": [
        ("ligature_ae_loss", pat.detect_ligature_ae_loss),
    ],
    "ccel_thml": [],
    "pdf": [],
    "html_transcription": [],
}

# Field-level detectors -- run on full field text (not token-by-token).
# Applied to all pattern_sets; each entry is a (reason, func) pair where func
# takes (text: str, ctx: DetectorContext) -> Optional[Candidate].
_FIELD_DETECTORS: list[tuple[str, object]] = [
    ("pg_header", pat.detect_pg_header),
]

_KNOWN_PATTERN_SETS = set(_DETECTORS_BY_PATTERN_SET.keys())

# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def load_config(source_id: str) -> dict:
    """Load and validate build/tools/ocr_scanner/configs/<source_id>.json.

    Raises:
        FileNotFoundError: if the config file does not exist.
        ValueError: if required keys are missing or pattern_set is unknown.
    """
    config_path = _CONFIGS_DIR / f"{source_id}.json"
    if not config_path.exists():
        raise FileNotFoundError(
            f"No config found for source '{source_id}' at {config_path}"
        )
    with config_path.open(encoding="utf-8") as f:
        config = json.load(f)

    required_keys = {"source_id", "pattern_set", "pattern_set_version",
                     "scan_fields", "ignore_fields", "whitelist_terms",
                     "whitelist_patterns", "tier3_enabled"}
    missing = required_keys - config.keys()
    if missing:
        raise ValueError(f"Config '{source_id}' is missing required keys: {missing}")

    if config["pattern_set"] not in _KNOWN_PATTERN_SETS:
        raise ValueError(
            f"Config '{source_id}' uses unknown pattern_set '{config['pattern_set']}'. "
            f"Known sets: {sorted(_KNOWN_PATTERN_SETS)}"
        )

    # Validate whitelist_patterns are compilable regex strings at load time.
    # A typo here causes silent suppression failure if caught later; raise early.
    for pat_str in config.get("whitelist_patterns", []):
        try:
            re.compile(pat_str)
        except re.error as exc:
            raise ValueError(
                f"Config '{source_id}' has invalid whitelist_pattern '{pat_str}': {exc}"
            ) from exc

    return config


# ---------------------------------------------------------------------------
# Field iteration
# ---------------------------------------------------------------------------


def _field_iter(entry: dict, scan_fields: list[str], ignore_fields: set[str]):
    """Yield (field_path: str, text: str) for every scannable text blob in entry."""
    for fname in scan_fields:
        if fname in ignore_fields:
            continue
        val = entry.get(fname)
        if val is None:
            continue
        if isinstance(val, str):
            yield fname, val
        elif isinstance(val, list):
            for idx, item in enumerate(val):
                if isinstance(item, str):
                    yield f"{fname}[{idx}]", item


# ---------------------------------------------------------------------------
# Tokenisation
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> list[str]:
    """Split text on whitespace. Preserves case; does not strip punctuation.

    Detectors decide whether trailing punctuation matters.
    """
    return text.split()


# ---------------------------------------------------------------------------
# Context extraction
# ---------------------------------------------------------------------------


def _get_context(text: str, token: str, start: int) -> tuple[str, str]:
    """Return (context_before, context_after) -- up to 40 chars each side of token."""
    end = start + len(token)
    before = text[max(0, start - 40):start].strip()
    after = text[end:end + 40].strip()
    return before, after


# ---------------------------------------------------------------------------
# Candidate ID counter
# ---------------------------------------------------------------------------


class _CandidateCounter:
    def __init__(self):
        self._n = 0

    def next(self) -> str:
        self._n += 1
        return f"cand-{self._n:04d}"


_WHITELIST_STRIP_CHARS = frozenset("()[]{}.,;:!?")


def _strip_for_whitelist(token: str) -> str:
    """Return token with leading/trailing punctuation stripped for whitelist matching.

    Strips ( ) [ ] { } . , ; : ! ? so that '(MPL,' matches whitelisted 'MPL'.
    Does NOT alter the token seen by detectors -- used only for suppression check.
    """
    return token.strip("".join(_WHITELIST_STRIP_CHARS))


# ---------------------------------------------------------------------------
# Main scan pipeline
# ---------------------------------------------------------------------------


def scan_entries(
    entries: list[dict],
    config: dict,
    source_id: str,
    dictionary: "pat.DictionaryStack",
    max_candidates: int | float | None = 500,
    timestamp_timezone: tzinfo | None = None,
) -> ScanResult:
    """Scan a list of OCD JSON entries for OCR-corruption candidates.

    Args:
        entries:        List of entry dicts from an OCD JSON file's 'data' array.
        config:         Loaded config dict from load_config().
        source_id:      Source identifier (must match config['source_id']).
        dictionary:     Initialised DictionaryStack (layered word lookup).
        max_candidates: Hard cap on candidates in the result. Pass math.inf
                        or None to disable truncation.
        timestamp_timezone: Timezone for scanned_at. Defaults to the legacy
                        CLI timezone, Australia/Melbourne. Producer callers
                        pass timezone.utc.

    Returns:
        ScanResult with all candidate OCR-corruption flags.
    """
    pattern_set = config["pattern_set"]
    if max_candidates is None:
        max_candidates = math.inf
    no_candidate_limit = math.isinf(max_candidates)
    scan_fields: list[str] = config.get("scan_fields", [])
    ignore_fields: set[str] = set(config.get("ignore_fields", []))
    whitelist_terms: set[str] = {t.upper() for t in config.get("whitelist_terms", [])}
    tier3_enabled: bool = config.get("tier3_enabled", False)

    # Compile whitelist_patterns from config (list of regex strings)
    whitelist_patterns: list[re.Pattern] = []
    for pat_str in config.get("whitelist_patterns", []):
        try:
            whitelist_patterns.append(re.compile(pat_str))
        except re.error as exc:
            raise ValueError(
                f"Invalid whitelist_pattern '{pat_str}' in config "
                f"for source '{source_id}': {exc}"
            ) from exc

    # Build detector list for this pattern_set
    detectors = list(_DETECTORS_BY_PATTERN_SET.get(pattern_set, []))
    if tier3_enabled:
        detectors += list(_TIER3_DETECTORS_BY_PATTERN_SET.get(pattern_set, []))

    # Pre-flight estimate: warn when estimated candidates may exceed the hard cap.
    # Rough upper bound: one candidate per (entry * detector) pair.
    estimate = len(entries) * len(detectors)
    if not no_candidate_limit and estimate > max_candidates * 2:
        print(
            f"Warning: estimated candidates (~{estimate}) may exceed "
            f"max_candidates ({max_candidates}). Consider raising max_candidates.",
            file=sys.stderr,
        )

    scanned_at = datetime.now(tz=timestamp_timezone or ZoneInfo("Australia/Melbourne")).isoformat()
    counter = _CandidateCounter()
    all_candidates: list[Candidate] = []
    truncated = False
    truncated_reason: Optional[str] = None

    for entry in entries:
        entry_id = entry.get("entry_id", "")

        for field_path, text in _field_iter(entry, scan_fields, ignore_fields):
            # Field-level detectors: operate on the full field text before tokenizing.
            for _reason, field_detect_fn in _FIELD_DETECTORS:
                if not no_candidate_limit and len(all_candidates) >= max_candidates:
                    truncated = True
                    truncated_reason = (
                        f"max_candidates={max_candidates} exceeded; "
                        f"some candidates not reported"
                    )
                    break
                field_ctx = pat.DetectorContext(
                    source_id=source_id,
                    entry_id=entry_id,
                    field_path=field_path,
                    context_before="",
                    context_after="",
                    cand_id=counter.next(),
                    dictionary=dictionary,
                    whitelist_terms=whitelist_terms,
                    whitelist_patterns=whitelist_patterns,
                    adjacent_prev=None,
                    adjacent_next=None,
                )
                candidate = field_detect_fn(text, field_ctx)
                if candidate is not None:
                    all_candidates.append(candidate)

            tokens = _tokenize(text)

            for token_idx, token in enumerate(tokens):
                if not no_candidate_limit and len(all_candidates) >= max_candidates:
                    truncated = True
                    truncated_reason = (
                        f"max_candidates={max_candidates} exceeded; "
                        f"some candidates not reported"
                    )
                    break

                # Skip whitelisted tokens -- check raw form AND stripped form
                token_upper = token.upper()
                token_stripped_upper = _strip_for_whitelist(token).upper()
                if token_upper in whitelist_terms or token_stripped_upper in whitelist_terms:
                    continue
                if any(p.match(token) for p in whitelist_patterns):
                    continue

                # Build context around this token
                # Find the token's char position for context extraction
                char_start = _find_token_start(text, tokens, token_idx)
                ctx_before, ctx_after = _get_context(text, token, char_start)

                adjacent_prev = tokens[token_idx - 1] if token_idx > 0 else None
                adjacent_next = tokens[token_idx + 1] if token_idx < len(tokens) - 1 else None

                ctx = pat.DetectorContext(
                    source_id=source_id,
                    entry_id=entry_id,
                    field_path=field_path,
                    context_before=ctx_before,
                    context_after=ctx_after,
                    cand_id=counter.next(),
                    dictionary=dictionary,
                    whitelist_terms=whitelist_terms,
                    whitelist_patterns=whitelist_patterns,
                    adjacent_prev=adjacent_prev,
                    adjacent_next=adjacent_next,
                )

                for reason, detect_fn in detectors:
                    candidate = detect_fn(token, ctx)
                    if candidate is not None:
                        all_candidates.append(candidate)
                        # Refresh context with a new cand_id for the next token
                        ctx = pat.DetectorContext(
                            source_id=source_id,
                            entry_id=entry_id,
                            field_path=field_path,
                            context_before=ctx_before,
                            context_after=ctx_after,
                            cand_id=counter.next(),  # fresh ID for next detector
                            dictionary=dictionary,
                            whitelist_terms=whitelist_terms,
                            whitelist_patterns=whitelist_patterns,
                            adjacent_prev=adjacent_prev,
                            adjacent_next=adjacent_next,
                        )
                        break  # one candidate per token -- first match wins

            if truncated:
                break
        if truncated:
            break

    return ScanResult(
        source_id=source_id,
        scanned_at=scanned_at,
        entries_scanned=len(entries),
        pattern_set=pattern_set,
        pattern_set_version=config.get("pattern_set_version", "1"),
        candidates=all_candidates,
        truncated=truncated,
        truncated_reason=truncated_reason,
    )


def _find_token_start(text: str, tokens: list[str], token_idx: int) -> int:
    """Find the character offset of tokens[token_idx] in text.

    Walks through tokens in order, advancing a cursor. O(n) but only called
    once per token and text is short (a single field value).
    """
    cursor = 0
    for i, tok in enumerate(tokens):
        pos = text.find(tok, cursor)
        if pos == -1:
            return cursor  # fallback: token not found (shouldn't happen)
        if i == token_idx:
            return pos
        cursor = pos + len(tok)
    return 0
