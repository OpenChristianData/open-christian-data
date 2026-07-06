"""Greek/Hebrew pilot -- conservative closed-corpus verse matching.

B16 deliverable #4. Implements locked decision #4 (research-synthesis R4 /
section 4.4): a verse match against the closed biblical corpus generates a
*candidate*, never an auto-correction oracle. A candidate is promoted to an
auto-correction only when ALL of the conservative gates hold:

  * the span is citation-pinned (a nearby explicit reference fixes the verse),
  * the span is longer than one token,
  * the match is unique,
  * the edit distance is low under BOTH the raw and the diacritic-stripped
    comparison,
  * the scan and candidate are from a compatible edition family (never silently
    correct a Textus-Receptus reading toward a critical text), and
  * the correction adds NO diacritic that is absent from the scan.

The last gate is the hard invariant: weak engines drop Greek accents and Hebrew
pointing, and the reference editions carry them, so a naive "fill from the verse"
would inject canonical pointing the page never printed (R4-D8). That is rejected
outright -- the diplomatic text keeps the scanned reading.

A match that scores above the confident bar but fails a gate is the
*wrong-confident match* -- the dangerous false positive. It is rejected, never
silently applied. The pilot report measures the verse-match rate and the
wrong-confident-match rate; the rates on real corpus pages are a phase-2
measurement, this module is the machinery proven on fixtures.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import unicodedata
from typing import Sequence


# --- decisions ---
DECISION_AUTO_CORRECT = "auto_correct"
DECISION_CANDIDATE = "candidate"
DECISION_REJECT = "reject"

# --- thresholds (phase-2 calibration tunes the exact values; R4 leaves the
# verse-match / wrong-confident rates as a local measurement) ---
# Diacritic-insensitive match score at/above which a match is "confident".
CONFIDENT_MATCH_BAR = 0.85
# Score at/above which a verse match is judged to exist at all.
MATCH_BAR = 0.70
# Both raw and stripped scores must reach this for an auto-correction.
LOW_EDIT_SCORE = 0.90
# Verse auto-correction is never applied to a one-token span (R4-D2).
MIN_AUTOCORRECT_SPAN_TOKENS = 2


def strip_diacritics(text: str) -> str:
    """Drop every nonspacing combining mark (Greek accents, Hebrew niqqud).

    Decompose to NFD, remove category-Mn marks, recompose to NFC so precomposed
    and decomposed inputs compare equal.
    """
    decomposed = unicodedata.normalize("NFD", text)
    without_marks = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return unicodedata.normalize("NFC", without_marks)


def _base_mark_pairs(text: str) -> list[tuple[str, str]]:
    """Associate each combining mark with the base character it sits on (NFD order).

    A whole-string mark *set* is too coarse: it lets the candidate add an accent
    to a second token when the same mark type already appears on a first token.
    Pairing each mark with its base character makes the comparison per-base-char
    enough to catch that (Codex review finding #3).
    """
    pairs: list[tuple[str, str]] = []
    base = ""
    for ch in unicodedata.normalize("NFD", text):
        if unicodedata.category(ch) == "Mn":
            pairs.append((base, ch))
        else:
            base = ch
    return pairs


def added_diacritics(*, scan_text: str, candidate_text: str) -> set[tuple[str, str]]:
    """Return the (base, mark) pairs the candidate adds beyond what the scan carries.

    Conservative multiset containment: a mark on a base character is "added" when
    the candidate carries more of that (base, mark) pair than the scan does. A
    non-empty result means promoting the candidate to diplomatic text would inject
    a diacritic the page never printed on that character (R4-D8).
    """
    scan_counts = Counter(_base_mark_pairs(scan_text))
    candidate_counts = Counter(_base_mark_pairs(candidate_text))
    return {pair for pair, count in candidate_counts.items() if count > scan_counts.get(pair, 0)}


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost))
        previous = current
    return previous[-1]


def _match_score(a: str, b: str) -> float:
    longest = max(len(a), len(b))
    if longest == 0:
        return 1.0
    return 1.0 - _levenshtein(a, b) / longest


def _edition_compatible(scan_family: str | None, candidate_family: str | None) -> bool:
    # Conservative: only an explicit same-family pairing is compatible. Unknown
    # or differing families fail the gate (never correct TR toward a critical text).
    if not scan_family or not candidate_family:
        return False
    return scan_family == candidate_family


@dataclass(frozen=True)
class MatchResult:
    decision: str
    reasons: tuple[str, ...]
    is_confident: bool
    has_verse_match: bool
    output_status: str
    diplomatic_text: str
    raw_score: float
    stripped_score: float


def evaluate_match(
    *,
    scan_text: str,
    candidate_text: str,
    span_token_count: int,
    citation_pinned: bool,
    unique_match: bool,
    scan_edition_family: str | None,
    candidate_edition_family: str | None,
) -> MatchResult:
    """Decide whether a closed-corpus candidate may correct the scanned span.

    Returns a ``MatchResult``. ``diplomatic_text`` is the text the pilot would
    keep: the candidate only when it is safe to auto-correct, otherwise the
    scanned reading unchanged.
    """
    raw_score = _match_score(scan_text, candidate_text)
    stripped_score = _match_score(strip_diacritics(scan_text), strip_diacritics(candidate_text))
    is_confident = stripped_score >= CONFIDENT_MATCH_BAR
    has_verse_match = stripped_score >= MATCH_BAR

    # Hard invariant first: never inject a diacritic absent from the scan. The
    # diplomatic text stays the scanned reading.
    if added_diacritics(scan_text=scan_text, candidate_text=candidate_text):
        return MatchResult(
            decision=DECISION_REJECT,
            reasons=("would_add_diacritics",),
            is_confident=is_confident,
            has_verse_match=has_verse_match,
            output_status="unresolved",
            diplomatic_text=scan_text,
            raw_score=raw_score,
            stripped_score=stripped_score,
        )

    reasons: list[str] = []
    if not citation_pinned:
        reasons.append("not_citation_pinned")
    if span_token_count < MIN_AUTOCORRECT_SPAN_TOKENS:
        reasons.append("span_too_short")
    if not unique_match:
        reasons.append("not_unique_match")
    if not _edition_compatible(scan_edition_family, candidate_edition_family):
        reasons.append("incompatible_edition")
    if raw_score < LOW_EDIT_SCORE:
        reasons.append("raw_edit_distance_high")
    if stripped_score < LOW_EDIT_SCORE:
        reasons.append("stripped_edit_distance_high")

    if not reasons:
        return MatchResult(
            decision=DECISION_AUTO_CORRECT,
            reasons=(),
            is_confident=True,
            has_verse_match=True,
            output_status="restored_from_reference",
            diplomatic_text=candidate_text,
            raw_score=raw_score,
            stripped_score=stripped_score,
        )

    # A confident match that failed a gate is the wrong-confident danger: reject,
    # never silently apply. A non-confident match is routed to human review.
    decision = DECISION_REJECT if is_confident else DECISION_CANDIDATE
    return MatchResult(
        decision=decision,
        reasons=tuple(reasons),
        is_confident=is_confident,
        has_verse_match=has_verse_match,
        output_status="unresolved",
        diplomatic_text=scan_text,
        raw_score=raw_score,
        stripped_score=stripped_score,
    )


@dataclass(frozen=True)
class PilotObservation:
    """One evaluated span plus the reviewer/fixture ground truth.

    ``is_true_match`` is the phase-2 reviewer verdict (or fixture label) for
    whether the candidate verse is actually the right reading. The decision
    function never sees it; the report uses it to measure the realized
    wrong-confident-match rate.
    """

    evaluation: MatchResult
    is_true_match: bool


def gh_pilot_report(observations: Sequence[PilotObservation]) -> dict:
    """Aggregate evaluated spans into the pilot's verse-match / wrong-confident report.

    The load-bearing safety invariant is ``wrong_confident_autocorrected == 0``:
    the conservative gates must catch every confident-but-wrong match before it
    is applied.
    """
    n_spans = len(observations)
    verse_match_count = sum(1 for o in observations if o.evaluation.has_verse_match)
    confident = [o for o in observations if o.evaluation.is_confident]
    wrong_confident = [o for o in confident if not o.is_true_match]
    wrong_confident_autocorrected = sum(
        1
        for o in observations
        if o.evaluation.decision == DECISION_AUTO_CORRECT and not o.is_true_match
    )
    by_decision = Counter(o.evaluation.decision for o in observations)

    return {
        "report_kind": "gh_pilot_report",
        "n_spans": n_spans,
        "verse_match_count": verse_match_count,
        "verse_match_rate": (verse_match_count / n_spans) if n_spans else 0.0,
        "confident_match_count": len(confident),
        "wrong_confident_match_count": len(wrong_confident),
        "wrong_confident_match_rate": (len(wrong_confident) / len(confident)) if confident else 0.0,
        "wrong_confident_autocorrected": wrong_confident_autocorrected,
        "by_decision": dict(by_decision),
    }
