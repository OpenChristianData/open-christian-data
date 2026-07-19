"""B16 deliverable #4 -- Greek/Hebrew pilot (TEST-16: wrong-confident bar +
no-added-diacritics invariant).

Contract: ``plans/2026-05-28-research-synthesis.md`` R4 / locked decision #4
(section 4.4) -- closed-corpus matching is candidate generation, NOT an
auto-correction oracle. Auto-correct only when ALL hold: citation-pinned AND
span > 1 token AND unique match AND low edit distance under BOTH raw and
diacritic-stripped comparison AND compatible edition family AND no diacritics
added that are absent from the scan. A confident-scoring match that fails any
gate is rejected, never silently applied (the wrong-confident-match danger).

The verse-match / wrong-confident-match *rates* on real corpus pages are a
phase-2 measurement; this suite proves the decision + measurement machinery on
synthetic fixtures. The Greek/Hebrew literals were written directly and verified
intact at the codepoint level (precomposed bases + combining marks survived the
write -- PY-08); the comments give the readable transliteration.
"""

from __future__ import annotations

import unicodedata

import pytest

from build.lib import gh_pilot
from ocd_kernel.lib.schema_enums import get_enum


# Readable forms in comments; escapes are authoritative so the diacritics survive.
LOGOS_BARE = "λογος"          # logos, no accent
LOGOS_ACCENT = "λόγος"        # logos with acute on omicron
JOHN_1_1_SCAN = "ἐν ἀρχῇ ἦν ὁ λόγος"  # polytonic, as printed
GENESIS_CONSONANTAL = "בראשית"  # br'shyt, no niqqud
GENESIS_POINTED = "בְּרֵאשִׁית"  # with niqqud/dagesh


def _has_combining(text: str) -> bool:
    return any(unicodedata.category(ch) == "Mn" for ch in unicodedata.normalize("NFD", text))


# ---------------------------------------------------------------------------
# Diacritic primitives
# ---------------------------------------------------------------------------

def test_strip_diacritics_removes_greek_accent():
    assert gh_pilot.strip_diacritics(LOGOS_ACCENT) == LOGOS_BARE


def test_strip_diacritics_removes_hebrew_niqqud():
    assert gh_pilot.strip_diacritics(GENESIS_POINTED) == GENESIS_CONSONANTAL


def test_added_diacritics_detects_introduced_accent():
    # Candidate adds the acute absent from the scan.
    added = gh_pilot.added_diacritics(scan_text=LOGOS_BARE, candidate_text=LOGOS_ACCENT)
    assert added  # non-empty -> would inject a mark absent from the page


def test_added_diacritics_empty_when_scan_already_pointed():
    added = gh_pilot.added_diacritics(scan_text=LOGOS_ACCENT, candidate_text=LOGOS_ACCENT)
    assert added == set()


def test_added_diacritics_detects_accent_on_a_different_token():
    # The mark TYPE already appears in the scan (on the first word) but the
    # candidate adds it to a second, unaccented token. A whole-string mark-set
    # diff misses this; the invariant must still fire (Codex review finding #3).
    scan = LOGOS_ACCENT + " " + LOGOS_BARE        # first word accented, second bare
    candidate = LOGOS_ACCENT + " " + LOGOS_ACCENT  # accent injected on the second word
    assert gh_pilot.added_diacritics(scan_text=scan, candidate_text=candidate)


def test_pilot_rejects_accent_added_to_a_different_token():
    scan = LOGOS_ACCENT + " " + LOGOS_BARE
    candidate = LOGOS_ACCENT + " " + LOGOS_ACCENT
    result = gh_pilot.evaluate_match(
        scan_text=scan,
        candidate_text=candidate,
        span_token_count=2,
        citation_pinned=True,
        unique_match=True,
        scan_edition_family="WH",
        candidate_edition_family="WH",
    )
    assert result.decision == gh_pilot.DECISION_REJECT
    assert "would_add_diacritics" in result.reasons
    assert gh_pilot.added_diacritics(scan_text=scan, candidate_text=result.diplomatic_text) == set()


# ---------------------------------------------------------------------------
# The no-added-diacritics invariant (hard reject)
# ---------------------------------------------------------------------------

def test_pilot_never_adds_a_diacritic_absent_from_the_scan():
    # Hebrew: pointed candidate from the reference, consonantal scan.
    result = gh_pilot.evaluate_match(
        scan_text=GENESIS_CONSONANTAL,
        candidate_text=GENESIS_POINTED,
        span_token_count=1,
        citation_pinned=True,
        unique_match=True,
        scan_edition_family="MT",
        candidate_edition_family="MT",
    )
    assert result.decision == gh_pilot.DECISION_REJECT
    assert "would_add_diacritics" in result.reasons
    # Whatever text the pilot would emit, it carries no mark absent from the scan.
    assert gh_pilot.added_diacritics(scan_text=GENESIS_CONSONANTAL, candidate_text=result.diplomatic_text) == set()


# ---------------------------------------------------------------------------
# The wrong-confident-match bar
# ---------------------------------------------------------------------------

def test_confident_but_unpinned_short_span_is_rejected_not_applied():
    # A lone confident token match (logos) is the canonical false-positive: it
    # matches many verses. Above the confident bar, but not pinned / not long
    # enough -> must be rejected, never auto-applied.
    result = gh_pilot.evaluate_match(
        scan_text=LOGOS_ACCENT,
        candidate_text=LOGOS_ACCENT,
        span_token_count=1,
        citation_pinned=False,
        unique_match=False,
        scan_edition_family="WH",
        candidate_edition_family="WH",
    )
    assert result.is_confident is True
    assert result.decision != gh_pilot.DECISION_AUTO_CORRECT
    assert result.decision == gh_pilot.DECISION_REJECT


def test_confident_match_to_incompatible_edition_is_rejected():
    # Same surface, but the scan is a TR reading and the candidate is a critical
    # text -- never silently correct TR toward a critical reading (R4-D4).
    result = gh_pilot.evaluate_match(
        scan_text=JOHN_1_1_SCAN,
        candidate_text=JOHN_1_1_SCAN,
        span_token_count=5,
        citation_pinned=True,
        unique_match=True,
        scan_edition_family="TR",
        candidate_edition_family="WH",
    )
    assert result.decision == gh_pilot.DECISION_REJECT
    assert "incompatible_edition" in result.reasons


def test_safe_long_pinned_unique_match_auto_corrects():
    result = gh_pilot.evaluate_match(
        scan_text=JOHN_1_1_SCAN,
        candidate_text=JOHN_1_1_SCAN,
        span_token_count=5,
        citation_pinned=True,
        unique_match=True,
        scan_edition_family="WH",
        candidate_edition_family="WH",
    )
    assert result.decision == gh_pilot.DECISION_AUTO_CORRECT
    assert result.output_status in get_enum("gold-record-v1", "output_status")
    assert result.output_status == "restored_from_reference"


def test_one_token_span_never_auto_corrects():
    result = gh_pilot.evaluate_match(
        scan_text=LOGOS_ACCENT,
        candidate_text=LOGOS_ACCENT,
        span_token_count=1,
        citation_pinned=True,
        unique_match=True,
        scan_edition_family="WH",
        candidate_edition_family="WH",
    )
    assert result.decision != gh_pilot.DECISION_AUTO_CORRECT


# ---------------------------------------------------------------------------
# Pilot report -- verse-match + wrong-confident-match rates
# ---------------------------------------------------------------------------

def _eval(scan, candidate, *, tokens, pinned, unique, scan_ed, cand_ed, true_match):
    result = gh_pilot.evaluate_match(
        scan_text=scan,
        candidate_text=candidate,
        span_token_count=tokens,
        citation_pinned=pinned,
        unique_match=unique,
        scan_edition_family=scan_ed,
        candidate_edition_family=cand_ed,
    )
    return gh_pilot.PilotObservation(evaluation=result, is_true_match=true_match)


def test_pilot_report_rates_and_no_wrong_confident_autocorrect():
    observations = [
        # safe true match -> auto_correct
        _eval(JOHN_1_1_SCAN, JOHN_1_1_SCAN, tokens=5, pinned=True, unique=True,
              scan_ed="WH", cand_ed="WH", true_match=True),
        # confident but wrong (incompatible edition) -> rejected
        _eval(JOHN_1_1_SCAN, JOHN_1_1_SCAN, tokens=5, pinned=True, unique=True,
              scan_ed="TR", cand_ed="WH", true_match=False),
        # lone token, no match worth applying
        _eval(LOGOS_ACCENT, LOGOS_ACCENT, tokens=1, pinned=False, unique=False,
              scan_ed="WH", cand_ed="WH", true_match=False),
    ]
    report = gh_pilot.gh_pilot_report(observations)
    assert report["n_spans"] == 3
    # Two of three scored as a verse match (the lone-token surface still matches).
    assert report["verse_match_count"] >= 1
    assert 0.0 <= report["verse_match_rate"] <= 1.0
    assert 0.0 <= report["wrong_confident_match_rate"] <= 1.0
    # The load-bearing safety property: no confident-but-wrong match was applied.
    assert report["wrong_confident_autocorrected"] == 0
