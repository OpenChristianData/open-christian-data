import hashlib
import importlib
import json
import sys
from pathlib import Path

import pytest

from build.lib._generated_enums import (
    REFERENCE_ENTRY__META__COMPLETENESS,
    REFERENCE_ENTRY__META__PROVENANCE__PROCESSING_METHOD,
    REFERENCE_ENTRY__META__TRADITION,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
PARSER_DIR = REPO_ROOT / "build" / "parsers"
OUTPUT_FILE = REPO_ROOT / "data" / "reference" / "hastings-dictionary-of-the-bible.json"
ABEL_SOURCE_FILE = (
    REPO_ROOT
    / "raw"
    / "ia"
    / "hastings-dictionary"
    / "DictionaryOfTheBibleV1_djvu.txt"
)
ABEL_FIDELITY_FIXTURE = (
    REPO_ROOT / "tests" / "fixtures" / "hastings" / "abel_ocr_fidelity.json"
)

# Vols 1-4 parsed; Vol 5 (British Library scan) skipped — OCR uses Greek Unicode homoglyphs
# for Latin characters throughout, making it unreadable to the standard heading detector.
# Count was 2705 before the 2026-04-30 heading-detection fix; the fix removed bogus body
# labels, ALL-CAPS body sentences, and OCR running-header variants.
_EXPECTED_TOTAL_COUNT = 2512


def _import_parser():
    sys.path.insert(0, str(PARSER_DIR))
    try:
        return importlib.import_module("ia_hastings_dictionary")
    finally:
        sys.path.remove(str(PARSER_DIR))


def test_tradition_values_are_schema_valid():
    assert "ecumenical" in REFERENCE_ENTRY__META__TRADITION
    assert "evangelical" in REFERENCE_ENTRY__META__TRADITION


def test_completeness_values_are_schema_valid():
    assert "full" in REFERENCE_ENTRY__META__COMPLETENESS
    assert "partial" in REFERENCE_ENTRY__META__COMPLETENESS


def test_processing_method_is_schema_valid():
    assert "automated" in REFERENCE_ENTRY__META__PROVENANCE__PROCESSING_METHOD


def test_module_level_assertions_pass():
    _import_parser()


def test_dictionary_id():
    parser = _import_parser()
    assert parser.DICTIONARY_ID == "hastings-dictionary-of-the-bible"


def test_all_volume_keys_are_configured():
    parser = _import_parser()
    assert sorted(parser.IA_VOLUMES.keys()) == [1, 2, 3, 4, 5]


@pytest.mark.raw_required(OUTPUT_FILE)
def test_expected_total_entry_count():
    with OUTPUT_FILE.open(encoding="utf-8") as f:
        output = json.load(f)

    matching_entries = [
        entry
        for entry in output.get("data", [])
        if entry.get("entry_id", "").startswith("hastings.")
    ]
    assert len(matching_entries) == _EXPECTED_TOTAL_COUNT


@pytest.mark.raw_required(OUTPUT_FILE)
def test_output_populates_related_terms_for_see_stub():
    with OUTPUT_FILE.open(encoding="utf-8") as f:
        output = json.load(f)

    entry = next(
        e
        for e in output.get("data", [])
        if e.get("entry_id") == "hastings.sea-of-chirneseth-sea-of-oaulbe"
    )

    assert entry["related_terms"] == ["Gauleb", "Sea of"]


@pytest.mark.raw_required(ABEL_SOURCE_FILE)
def test_abel_retained_ocr_blocks_and_markers_are_exactly_preserved():
    """Pin the source facts that the retired broad-pass lane uniquely carried."""
    expected = json.loads(ABEL_FIDELITY_FIXTURE.read_text(encoding="utf-8"))
    assert expected["source_path"] == ABEL_SOURCE_FILE.relative_to(REPO_ROOT).as_posix()
    source_lines = ABEL_SOURCE_FILE.read_text(encoding="utf-8").splitlines()
    entry_start = expected["entry_line_start"]
    entry_end = expected["entry_line_end"]

    assert source_lines[entry_start - 1].strip() == "ABEL"
    assert source_lines[expected["next_entry_line"] - 1].strip().startswith("ABEL  (")

    selected_lf_slice = "\n".join(source_lines[entry_start - 1 : entry_end]) + "\n"
    assert hashlib.sha256(selected_lf_slice.encode("utf-8")).hexdigest() == expected[
        "selected_lf_slice_sha256"
    ]

    actual_blocks = []
    block_start = None
    block_lines = []
    for line_number, line in enumerate(
        source_lines[entry_start:entry_end], start=entry_start + 1
    ):
        if line.strip():
            block_start = block_start or line_number
            block_lines.append(line)
        elif block_lines:
            actual_blocks.append(
                {
                    "line_start": block_start,
                    "line_end": line_number - 1,
                    "text": " ".join(" ".join(block_lines).split()),
                }
            )
            block_start = None
            block_lines = []
    if block_lines:
        actual_blocks.append(
            {
                "line_start": block_start,
                "line_end": entry_end,
                "text": " ".join(" ".join(block_lines).split()),
            }
        )

    expected_blocks = [
        {key: block[key] for key in ("line_start", "line_end", "text")}
        for block in expected["blocks"]
    ]
    assert actual_blocks == expected_blocks
    assert [block["role"] for block in expected["blocks"]] == [
        "opening_ocr",
        "definition_ocr",
        "source_marker",
        "contributor_marker",
    ]
    uncertainty = expected["uncertainty_treatment"]
    assert uncertainty == {
        "status": "scan-backed correction unresolved",
        "projection_policy": "OCR retained verbatim after whitespace-only joining",
        "silent_correction": False,
        "visible_errors": ["8eeCAIN", "nock"],
    }
    definition_ocr = expected["blocks"][1]["text"]
    assert all(error in definition_ocr for error in uncertainty["visible_errors"])


@pytest.mark.raw_required(OUTPUT_FILE)
def test_abel_ordinary_output_still_has_known_block_and_boundary_loss():
    """Characterize current loss without treating the ordinary JSON as faithful TEI."""
    expected = json.loads(ABEL_FIDELITY_FIXTURE.read_text(encoding="utf-8"))
    output = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
    matches = [
        entry
        for entry in output["data"]
        if entry.get("entry_id") == "hastings.abel"
    ]
    assert len(matches) == 1

    actual_blocks = matches[0]["definition_blocks"]
    expected_blocks = [block["text"] for block in expected["blocks"]]
    assert actual_blocks != expected_blocks
    assert actual_blocks[:4] != expected_blocks

    source_definition = expected_blocks[1]
    ordinary_text = " ".join(actual_blocks)
    lost_clauses = (
        "the idea of the short-lived or possibly the shepherd",
        "the spirit of true piety which was expressed in his",
        "the Jewish consciousness of the enduring division of mankind",
    )
    assert all(clause in source_definition for clause in lost_clauses)
    assert all(clause not in ordinary_text for clause in lost_clauses)

    # The next, distinct ABEL place entry is currently swallowed into the
    # person entry instead of remaining outside its source boundary.
    assert any(block.startswith("ABEL (^sy), ' meadow.'") for block in actual_blocks)


# ---------------------------------------------------------------------------
# Regression fixtures (T6-7 fix: 2026-04-30)
# Each test pins one of the bug classes flagged by the Opus + Codex review.
# Strings are real OCR-shaped lines from the Hastings vols 1-4 _djvu.txt files.
# ---------------------------------------------------------------------------


def test_form_1_body_labels_rejected():
    """LXX:, RV:, NOTE:, Cf.: are body annotations inside other articles.
    They share Form-1 shape (CAPS_TERM: body) but must NOT trigger a heading.
    Pre-fix: each became a separate junk entry (e.g. hastings.lxx, 450 words)."""
    parser = _import_parser()
    cases = [
        "LXX: The Septuagint reading is...",
        "RV: Revised Version rendering.",
        "NOTE: see further...",
        "Cf.: parallel passage...",
        "AV: authorised version note",
        "MT: Masoretic text",
    ]
    for line in cases:
        assert parser.is_article_heading(line) is False, (
            f"body label {line!r} must not be detected as heading"
        )


def test_form_3_long_caps_rejected():
    """ALL-CAPS body sentences > 6 tokens are not real Form-3 article terms.
    Pre-fix: 'BIRTH TO AND CONTROLLED THE EVOLUTION OI' (7 tokens) became
    a junk entry hastings.birth-to-and-controlled-the-evolution-oi."""
    parser = _import_parser()
    long_caps = "BIRTH TO AND CONTROLLED THE EVOLUTION OI"
    assert parser.is_article_heading(long_caps) is False
    # Real Form-3 terms (<= 6 tokens) must still pass.
    assert parser.is_article_heading("ACTS OF THE APOSTLES") is True
    assert parser.is_article_heading("SONG OF SOLOMON") is True


def test_running_header_ocr_variants_rejected():
    """OCR commonly garbles 'THE' as 'THB', 'THK', 'TIIE'. Page-running headers
    that begin with any of these variants must be skipped — pre-fix,
    'THB HOABTTE STONE' became a junk entry hastings.thb-hoabtte-stone."""
    parser = _import_parser()
    variants = [
        "THB HOABTTE STONE",
        "THE MOABITE STONE",
        "THK FIRST OF SAMUEL",
        "TIIE BOOK OF JUDGES",
    ]
    for line in variants:
        assert parser.is_running_header(line) is True, (
            f"running-header variant {line!r} must be detected"
        )
    # Real article terms starting with 'TH' (no whitespace before next char)
    # must still NOT be classified as running headers.
    assert parser.is_running_header("THEBES (8'fa)") is False
    assert parser.is_running_header("THESSALONIANS, FIRST EPISTLE") is False


def test_volume_specific_front_matter_skip():
    """Front-matter skip is volume-keyed: only Vol 4 has the title-page false
    match at line 128 that requires skipping lines < 400. Vol 1's earliest
    marker (synthesised at line 100 here) must be honoured, not skipped."""
    parser = _import_parser()
    # Synthesise Vol 1 with marker at line 100 (must be picked).
    vol1_lines = ["pad"] * 100 + [
        "DICTIONARY  OF  THE  BIBLE",
    ] + ["pad"] * 100
    # First article heading after the marker, so parse_volume_text returns
    # without erroring out before the marker is recorded.
    vol1_lines += [""] + ["AARON"] + [""] + ["body line for aaron"]
    # Need >= 1 article so we don't return [].
    arts1 = parser.parse_volume_text("\n".join(vol1_lines), 1)
    # We can't directly assert the marker line; instead assert that body was
    # discoverable AFTER the marker (i.e. the marker did not get masked).
    # If the front-matter skip were global at 400, the parser would fall
    # through to the abbreviations fallback or fail entirely.
    assert any(a["term"] == "AARON" for a in arts1), (
        "Vol 1 marker at line 100 was masked — front-matter skip not volume-keyed"
    )

    # Synthesise Vol 4 with false match at line 128 (must be skipped) and
    # real marker at line 1049.
    vol4_lines = ["pad"] * 128 + ["DICTIONARY  OF  THE  BIBLE"] + ["pad"] * (1049 - 129)
    vol4_lines += ["DICTIONARY  OF  THE  BIBLE"] + ["pad"] * 50
    vol4_lines += [""] + ["ABEL"] + [""] + ["body line for abel"]
    arts4 = parser.parse_volume_text("\n".join(vol4_lines), 4)
    assert any(a["term"] == "ABEL" for a in arts4), (
        "Vol 4 real marker at 1049 not used — line-128 false match was honoured"
    )


def test_rerun_dedup_does_not_lose_within_run_dups():
    """Pre-fix: when two within-run articles slugify to the same base_id and
    that base_id pre-existed on disk, both collapsed into one entry — silent
    data loss. After fix: only the FIRST occurrence reuses the pre-existing
    base_id; subsequent occurrences take the -2/-3 suffix."""
    parser = _import_parser()

    pre_existing_ids = {"hastings.assyria"}
    consumed_pre_existing = set()
    seen_ids = set(pre_existing_ids)
    new_entries = []

    raw_articles = [
        {"term": "ASSYRIA", "definition_blocks": ["first body"], "vol_num": 1},
        {"term": "ASSYRIA", "definition_blocks": ["second body"], "vol_num": 1},
        {"term": "ASSYRIA", "definition_blocks": ["third body"], "vol_num": 1},
    ]

    for raw_article in raw_articles:
        base_id = f"hastings.{parser.slugify(raw_article['term'])}"
        if base_id in pre_existing_ids and base_id not in consumed_pre_existing:
            seen_ids.discard(base_id)
            consumed_pre_existing.add(base_id)
        entry = parser.build_entry(raw_article, seen_ids)
        new_entries.append(entry)

    ids = [e["entry_id"] for e in new_entries]
    assert ids == [
        "hastings.assyria",
        "hastings.assyria-2",
        "hastings.assyria-3",
    ], f"within-run dedup lost data: {ids}"


def test_extract_related_terms_from_see_stub():
    parser = _import_parser()

    assert parser.extract_related_terms(["BAPTIST. — See John the Baptist."]) == [
        "John the Baptist"
    ]


def test_extract_related_terms_from_see_also_list_with_refs():
    parser = _import_parser()

    terms = parser.extract_related_terms(
        ["BAND. See also Headband (Is 3 only), and Swaddlingband (Job 38 only)."]
    )

    assert terms == ["Headband", "Swaddlingband"]


def test_build_entry_populates_related_terms_from_cross_reference_apparatus():
    parser = _import_parser()
    raw_article = {
        "term": "BAPTIST",
        "definition_blocks": ["BAPTIST. — See John the Baptist."],
        "vol_num": 1,
    }

    entry = parser.build_entry(raw_article, set())

    assert entry["related_terms"] == ["John the Baptist"]


def test_clean_term_fallback_does_not_return_full_prose():
    """Pre-fix: clean_term fell back to returning the entire raw heading line
    when no upper-cased comma-segments survived. Post-fix: returns the longest
    leading run of ALL-CAPS tokens, or '' if none."""
    parser = _import_parser()
    junky = "IMNA (yj?:).— An Asherite chief, 1 Ch 7\". See"
    result = parser.clean_term(junky)
    assert result in ("IMNA", ""), (
        f"clean_term must return 'IMNA' or '' for junk heading, got {result!r}"
    )
    # All-lowercase prose returns "" (caller skips article).
    assert parser.clean_term("all lowercase prose nothing here") == ""
    # Sanity: real headings still work.
    assert parser.clean_term("AARON") == "AARON"
    assert parser.clean_term("CHAMIER, ahd/mye, DANIEL") == "CHAMIER, DANIEL"


# ---------------------------------------------------------------------------
# Per-volume regression counts (by alphabetical range)
# ---------------------------------------------------------------------------
# vol_num is not stored in output entries; volumes are identified by first-letter
# range (Hastings is alphabetically arranged: vol1=A-D, vol2=E-J, vol3=K-P, vol4=Q-Z).
# Counts established from committed output after the 2026-04-30 heading-detection fix.
# A delta on any range means content was silently added or removed from that volume.
_EXPECTED_VOL_RANGE_COUNTS = [
    ("vol1", "A", "D", 503),
    ("vol2", "E", "J", 675),
    ("vol3", "K", "P", 767),
    ("vol4", "Q", "Z", 567),
]


@pytest.mark.raw_required(OUTPUT_FILE)
@pytest.mark.parametrize("vol_label,lo,hi,expected", _EXPECTED_VOL_RANGE_COUNTS)
def test_entry_counts_by_volume_range(vol_label, lo, hi, expected):
    with OUTPUT_FILE.open(encoding="utf-8") as f:
        output = json.load(f)
    entries = output.get("data", [])
    in_range = []
    for e in entries:
        parts = e.get("entry_id", "").split(".", 1)
        if len(parts) > 1 and parts[1] and lo <= parts[1][0].upper() <= hi:
            in_range.append(e)
    assert len(in_range) == expected, (
        f"{vol_label} ({lo}-{hi}): expected {expected} entries, got {len(in_range)}"
    )


# ---------------------------------------------------------------------------
# Non-ASCII guard regression test
# ---------------------------------------------------------------------------


def test_non_ascii_guard_raises_homoglyph_skip_for_known_bad_vol():
    """HomoglyphSkip must be raised for _HOMOGLYPH_KNOWN_BAD_VOLS (vol 5) and
    RuntimeError for any unknown vol. Without this test, a broken threshold
    would only surface at parse time when vol 5 errors unexpectedly."""
    parser = _import_parser()
    # Greek Unicode text: >40% non-ASCII, simulates the British Library OCR pattern.
    greek_line = "Αβγδεζηθικλμνξοπρστυφχψω " * 3
    junk_text = "\n".join([greek_line] * 200)

    with pytest.raises(parser.HomoglyphSkip):
        parser.parse_volume_text(junk_text, 5)

    with pytest.raises(RuntimeError):
        parser.parse_volume_text(junk_text, 1)
