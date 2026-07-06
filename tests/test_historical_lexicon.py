import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.historical_lexicon import scan_historical_variants  # noqa: E402
from build.lib.review_warnings import collect_review_warnings  # noqa: E402
from build.tools.render_review_html import render_commentary_html  # noqa: E402


def _entry(text: str) -> dict:
    return {
        "entry_id": "sample.Gen.1.1",
        "book": "Genesis",
        "book_osis": "Gen",
        "chapter": 1,
        "verse_range": "1",
        "verse_range_osis": "Gen.1.1",
        "verse_text": None,
        "commentary_text": text,
        "summary": None,
        "summary_review_status": "withheld",
        "cross_references": [],
        "word_count": len(text.split()),
    }


def _payload(text: str) -> dict:
    return {
        "meta": {
            "id": "sample-commentary",
            "title": "Sample Commentary",
            "author": "Test Author",
            "license": "public-domain",
            "schema_type": "commentary",
            "schema_version": "2.2.0",
            "provenance": {},
        },
        "data": [_entry(text)],
    }


def test_detects_exact_surface_match():
    matches = scan_historical_variants("Esaias speaks here.")

    assert [(match.surface, match.normalised, match.variant_type) for match in matches] == [
        ("Esaias", "Isaiah", "biblical_person")
    ]


def test_case_handling_preserves_surface():
    matches = scan_historical_variants("ELIAS and elias are both old forms.")

    assert [match.surface for match in matches] == ["ELIAS", "elias"]
    assert {match.normalised for match in matches} == {"Elijah"}


def test_offsets_and_snippets_are_reported():
    text = "The old writer named Chrysostome in this place."

    match = scan_historical_variants(text)[0]

    assert match.start == text.index("Chrysostome")
    assert match.end == match.start + len("Chrysostome")
    assert "Chrysostome" in match.snippet


def test_scan_does_not_rewrite_source_text():
    text = "He shewed the connexion plainly."

    scan_historical_variants(text)

    assert text == "He shewed the connexion plainly."


def test_apocalypse_requires_biblical_book_context():
    assert scan_historical_variants("The apocalypse of empire was sudden.") == []

    matches = scan_historical_variants("Book of Apocalypse 1:1 is cited.")

    assert [(match.surface, match.normalised) for match in matches] == [("Apocalypse", "Revelation")]


def test_multiple_matches_in_one_text():
    matches = scan_historical_variants("Esaias shewed this to Chrysostome.")

    assert [match.surface for match in matches] == ["Esaias", "shewed", "Chrysostome"]


def test_review_warnings_include_lexicon_findings_as_info():
    warnings = collect_review_warnings([_entry("Esaias shewed it.")])
    lexicon_warnings = [warning for warning in warnings if warning.code == "historical_lexicon_variant"]

    assert len(lexicon_warnings) == 2
    assert {warning.severity for warning in lexicon_warnings} == {"info"}


def test_renderer_shows_lexicon_findings_through_warning_panel():
    html = render_commentary_html(_payload("Jeremias shewed the connexion."))

    assert "historical_lexicon_variant" in html
    assert "Jeremias -&gt; Jeremiah" in html
    assert "shewed -&gt; showed" in html
    assert "connexion -&gt; connection" in html
