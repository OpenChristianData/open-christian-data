import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.review_warnings import collect_review_warnings, warning_counts_by_severity  # noqa: E402


def _entry(**overrides):
    entry = {
        "entry_id": "sample.Gen.1.1",
        "book": "Genesis",
        "book_osis": "Gen",
        "chapter": 1,
        "verse_range": "1",
        "verse_range_osis": "Gen.1.1",
        "verse_text": None,
        "commentary_text": "Grace and peace.",
        "cross_references": [],
        "word_count": 3,
    }
    entry.update(overrides)
    return entry


def _codes(entries):
    return {warning.code for warning in collect_review_warnings(entries)}


def test_warns_about_duplicate_ids():
    warnings = collect_review_warnings([_entry(), _entry()])

    assert "duplicate_entry_id" in {warning.code for warning in warnings}


def test_warns_about_missing_text():
    warnings = collect_review_warnings([_entry(commentary_text="")])

    assert "missing_commentary_text" in {warning.code for warning in warnings}


def test_warns_about_broken_hyphenation():
    warnings = collect_review_warnings([_entry(commentary_text="The king-\n dom came.", word_count=4)])

    assert "possible_broken_hyphenation" in {warning.code for warning in warnings}


def test_warns_about_repeated_paragraphs():
    repeated = "A fuller paragraph is repeated here."

    warnings = collect_review_warnings(
        [
            _entry(entry_id="sample.Gen.1.1", commentary_text=repeated, word_count=6),
            _entry(entry_id="sample.Gen.1.2", verse_range_osis="Gen.1.2", commentary_text=repeated, word_count=6),
        ]
    )

    assert "repeated_paragraph" in {warning.code for warning in warnings}


def test_warns_about_word_count_mismatch():
    warnings = collect_review_warnings([_entry(commentary_text="Grace and peace.", word_count=99)])

    assert "word_count_mismatch" in {warning.code for warning in warnings}


def test_warning_severity_counts_include_all_severities():
    warnings = collect_review_warnings(
        [
            _entry(entry_id="", commentary_text="", word_count=0),
            _entry(
                entry_id="sample.Gen.1.2",
                verse_range_osis="Gen.1.2",
                commentary_text="Brief.",
                word_count=1,
            ),
        ]
    )

    counts = warning_counts_by_severity(warnings)

    assert counts["error"] == 2
    assert counts["info"] == 1
    assert "warning" in counts


def test_warns_about_non_string_cross_references():
    warnings = collect_review_warnings(
        [
            _entry(
                cross_references=["Gen.1.1", 7],
                word_count=3,
            )
        ]
    )

    assert {"non_string_cross_reference"} <= {warning.code for warning in warnings}


def test_warns_about_intro_with_osis_and_likely_ocr_junk():
    codes = _codes(
        [
            _entry(
                verse_range="intro",
                verse_range_osis="Gen.1.1",
                commentary_text="Readable text with ||| broken OCR.",
                word_count=6,
            )
        ]
    )

    assert {"intro_entry_unexpected_verse_range_osis", "likely_ocr_junk_sequence"} <= codes
