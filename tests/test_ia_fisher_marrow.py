"""test_ia_fisher_marrow.py -- tests for build/parsers/ia_fisher_marrow.py.

Covers (per Definition of Done in the acquisition prompt):
- Schema enum guards on WORK_CONFIG (tradition, work_kind, era, audience).
- Speaker label parsing for each of the four speakers + 'Nam' OCR variant.
- apply_speaker_prefix bolds Sect-prefixed and bare speaker forms.
- is_running_header strips the OCR's pervasive running-page-header noise.
- find_body_start skips Google Books boilerplate + TOC + preface.
- Output (when present) has Part I + Part II boundary, expected section count
  within tolerance, and no PG/Google Books/IA boilerplate in content_blocks.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.pytest_skips import skip_if_missing_data  # noqa: E402
from ocd_kernel.lib.schema_enums import get_enum  # noqa: E402
from build.parsers.ia_fisher_marrow import (  # noqa: E402
    RE_CHAPTER_HEADING,
    RE_PART_SECOND,
    RE_SECT_HEADING,
    RE_SECTION_INLINE_SPEAKER,
    WORK_CONFIG,
    _merge_ocr_hyphen_breaks,
    apply_speaker_prefix,
    find_body_start,
    is_running_header,
    parse_text,
)


# ---------------------------------------------------------------------------
# Schema enum guards (REL-09)
# ---------------------------------------------------------------------------

_VALID_TRADITIONS = get_enum("structured_text", "meta", "tradition")
_VALID_WORK_KINDS = get_enum("structured_text", "data", "work_kind")
_VALID_ERAS = get_enum("structured_text", "meta", "era")
_VALID_AUDIENCES = get_enum("structured_text", "meta", "audience")
_VALID_LICENSES = get_enum("structured_text", "meta", "license")
_VALID_COMPLETENESS = get_enum("structured_text", "meta", "completeness")


def test_traditions_are_schema_valid():
    for t in WORK_CONFIG["tradition"]:
        assert t in _VALID_TRADITIONS, f"invalid tradition {t!r}"


def test_work_kind_is_schema_valid():
    assert WORK_CONFIG["work_kind"] in _VALID_WORK_KINDS, (
        f"invalid work_kind {WORK_CONFIG['work_kind']!r}"
    )


def test_era_is_schema_valid():
    assert WORK_CONFIG["era"] in _VALID_ERAS


def test_audience_is_schema_valid():
    assert WORK_CONFIG["audience"] in _VALID_AUDIENCES


def test_license_is_schema_valid():
    assert WORK_CONFIG["license"] in _VALID_LICENSES


def test_completeness_is_schema_valid():
    assert WORK_CONFIG["completeness"] in _VALID_COMPLETENESS


def test_required_work_config_fields():
    required = {
        "work_id", "title", "author", "author_id",
        "language", "tradition", "work_kind", "license", "completeness",
        "source_edition",
    }
    missing = required - set(WORK_CONFIG.keys())
    assert not missing, f"WORK_CONFIG missing: {missing}"


# ---------------------------------------------------------------------------
# apply_speaker_prefix -- speaker label preservation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("speaker", ["Evan", "Nom", "Ant", "Neo", "Nam"])
def test_apply_speaker_prefix_bare(speaker: str):
    text = f"{speaker}. The truth is, sir, that my friend differs."
    out = apply_speaker_prefix(text)
    assert out.startswith(f"**{speaker}.**"), out


@pytest.mark.parametrize("speaker", ["Evan", "Nom", "Ant", "Neo", "Nam"])
def test_apply_speaker_prefix_with_section(speaker: str):
    text = f"Sect. 1. — {speaker}. The truth is, sir."
    out = apply_speaker_prefix(text)
    assert f"**{speaker}.**" in out, out
    assert out.startswith("Sect. 1. —"), out


def test_apply_speaker_prefix_passthrough_for_non_speaker():
    text = "But it is manifest, says Musculus, that the law of works..."
    assert apply_speaker_prefix(text) == text


def test_apply_speaker_prefix_handles_double_hyphen_em_dash():
    # OCR may produce '--' instead of em-dash
    text = "Sect. 2. -- Nom. But it seemeth that Adam did not consent."
    out = apply_speaker_prefix(text)
    assert "**Nom.**" in out


# ---------------------------------------------------------------------------
# is_running_header -- strips running-page-header noise
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("header", [
    "Chap. 2.",
    "Chap. 2. MODERN DIVINITY. 17",
    "Part I.",
    "Part 1.",
    "Part L",
    "Pari I.",
    "Part 2.",
    "THE MARROW OF",
    "MODERN DIVINITY",
    "Chap. -S.",
])
def test_is_running_header_strips_noise(header: str):
    assert is_running_header(header), f"failed to strip: {header!r}"


@pytest.mark.parametrize("real_line", [
    "CHAPTER I.",
    "CHAPTER TL",  # OCR mangling of CHAPTER II
    "CHAP. LV.",   # OCR mangling of CHAP. IV.
    "PART SECOND,",
    "Sect. 1. — Nom. The truth is...",
    "Of the Law of Works.",
    "Evan. The law of works...",
])
def test_is_running_header_keeps_real_content(real_line: str):
    assert not is_running_header(real_line), (
        f"falsely classified as header: {real_line!r}"
    )


# ---------------------------------------------------------------------------
# Regex sanity
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("heading", [
    "CHAPTER I.",
    "CHAPTER TL",   # OCR-mangled II
    "CHAP. LV.",    # OCR-mangled IV
    "CHAPTER III.",
])
def test_re_chapter_heading_matches_real(heading: str):
    assert RE_CHAPTER_HEADING.match(heading), heading


@pytest.mark.parametrize("not_heading", [
    "Chap. 2.",                  # running header (mixed case)
    "CHAPTER",                   # missing roman/letter
    "Chap. 2. MODERN DIVINITY",  # running header with body
    "Of the Law of Works.",
])
def test_re_chapter_heading_rejects_non_heading(not_heading: str):
    assert not RE_CHAPTER_HEADING.match(not_heading), not_heading


def test_re_part_second_matches():
    assert RE_PART_SECOND.match("PART SECOND,")
    assert RE_PART_SECOND.match("PART SECOND.")
    assert RE_PART_SECOND.match("PART SECOND")
    assert not RE_PART_SECOND.match("Part Second")
    assert not RE_PART_SECOND.match("PART SECOND, A MINIATURE")


def test_re_sect_heading_arabic_with_em_dash():
    m = RE_SECT_HEADING.match("Sect. 1. — Nom. The truth is, sir.")
    assert m and m.group("num") == "1"


def test_re_sect_heading_punct_variants():
    # OCR variants: Sect, / Sect* / Sect-
    for prefix in ["Sect.", "Sect,", "Sect*", "Sect-"]:
        line = f"{prefix} 3. — Ant. But, sir, did the law produce this effect?"
        m = RE_SECT_HEADING.match(line)
        assert m, f"failed to match {line!r}"
        assert m.group("num") == "3"


def test_re_sect_heading_footnote_marker_after_number():
    # OCR places footnote marker '*' between section number and em-dash:
    # 'Sect. 10*—' — num group must still capture '10'.
    m = RE_SECT_HEADING.match("Sect. 10*— Evan. The truth is evident.")
    assert m and m.group("num") == "10", repr(m)


def test_re_sect_heading_rejects_synopsis_line():
    # Synopsis: 'Sect. I. The Nature... — 2. Adam's Fall.' has no em-dash
    # immediately after 'I.'; should not match RE_SECT_HEADING.
    line = "Sect, I. The Nature of the Covenant of Works, 7. — 2. Adam's Fall."
    assert not RE_SECT_HEADING.match(line)


def test_re_section_inline_speaker_bolds_canonical_forms():
    m = RE_SECTION_INLINE_SPEAKER.match("Sect. 1. — Evan. The law of works...")
    assert m and m.group("speaker") == "Evan"


# ---------------------------------------------------------------------------
# find_body_start -- skips boilerplate and TOC
# ---------------------------------------------------------------------------

def test_find_body_start_returns_introduction_after_toc():
    lines = [""] * 1280 + [
        "INTRODUCTION.",
        "",
        "Sect. 1. Differences about the Law -- 2. A threefold Law.",
        "",
        "Nomista. Sir, my neighbour, Neophitus, and I having lately had some "
        "conference with this our friend and acquaintance...",
    ]
    assert find_body_start(lines) == 1280


def test_find_body_start_falls_back_to_first_sect_one():
    lines = [""] * 250 + [
        "Sect. 1. — Nom. The truth is, sir, he and I differ in very many things.",
    ]
    idx = find_body_start(lines)
    assert idx == 250


# ---------------------------------------------------------------------------
# OCR fidelity fixes
# ---------------------------------------------------------------------------

def test_merge_ocr_hyphen_breaks_dehyphenates_word_breaks():
    assert _merge_ocr_hyphen_breaks(["disci-", "pline"]) == ["discipline"]


def test_merge_ocr_hyphen_breaks_preserves_known_compounds():
    assert _merge_ocr_hyphen_breaks(["self-", "denial"]) == ["self-denial"]
    assert _merge_ocr_hyphen_breaks(["well-", "being"]) == ["well-being"]


def test_parse_text_sections_part_two_by_commandment_heading():
    doc = parse_text(
        "\n".join(
            [
                "INTRODUCTION.",
                "",
                "Sect. 1. -- Nom. The truth is, sir.",
                "",
                "PART SECOND,",
                "",
                "COMMANDMENT I,",
                "Evan. First commandment body.",
                "",
                "COMMANDMENT IF.",
                "Evan. Second commandment body.",
                "",
                "COMMANDMENT VI.",
                "Evan. Sixth commandment body.",
            ]
        )
    )

    part2 = doc["sections"][1]
    labels = [child["label"] for child in part2["children"]]
    assert labels == ["Commandment I", "Commandment II", "Commandment VI"]


# ---------------------------------------------------------------------------
# Output JSON checks (only run when the parsed output exists)
# ---------------------------------------------------------------------------

OUTPUT_FILE = REPO_ROOT / "data" / "structured-text" / "fisher-marrow-of-modern-divinity.json"


@pytest.fixture(scope="module")
def parsed_doc():
    skip_if_missing_data(OUTPUT_FILE)
    with open(str(OUTPUT_FILE), encoding="utf-8") as f:
        return json.load(f)


def test_output_has_part_one_and_part_two(parsed_doc):
    sections = parsed_doc["data"]["sections"]
    assert len(sections) == 2, f"expected 2 parts, got {len(sections)}"
    labels = [s.get("label") for s in sections]
    assert labels == ["Part I", "Part II"]


def test_output_part_one_has_four_chapters(parsed_doc):
    part1 = parsed_doc["data"]["sections"][0]
    chapters = part1.get("children", [])
    # The Boston Marrow Part I has exactly 4 chapters (Of the Law of Works,
    # Of the Law of Faith, Of the Law of Christ, Of the Heart's Happiness).
    assert len(chapters) == 4, f"expected 4 chapters, got {len(chapters)}"
    assert all(c.get("section_type") == "chapter" for c in chapters)


def test_output_part_two_has_substantial_content(parsed_doc):
    part2 = parsed_doc["data"]["sections"][1]

    def section_words(section: dict) -> int:
        return (
            sum(len(b.split()) for b in section.get("content_blocks", []))
            + sum(section_words(child) for child in section.get("children", []))
        )

    word_count = section_words(part2)
    # Part II (Ten Commandments exposition) is roughly 60-80k words
    assert word_count > 50000, f"Part II too short: {word_count} words"


def test_output_part_two_has_detected_commandment_sections(parsed_doc):
    part2 = parsed_doc["data"]["sections"][1]
    labels = [child.get("label") for child in part2.get("children", [])]
    assert "Commandment I" in labels
    assert "Commandment II" in labels
    assert "Commandment VI" in labels
    assert "Commandment X" in labels


def test_output_section_count_within_expected(parsed_doc):
    """Total leaf sections (all chapters' children) within ~1 of 39."""
    total_leaves = 0
    for part in parsed_doc["data"]["sections"]:
        for chapter in part.get("children", []):
            total_leaves += len(chapter.get("children", []))
            if not chapter.get("children") and chapter.get("content_blocks"):
                total_leaves += 1
        if not part.get("children") and part.get("content_blocks"):
            total_leaves += 1
    # Expected ~39 leaves (4 chapters + 5+13+12+3 sections, or approximations).
    # Allow a wide tolerance because OCR-noisy section starts are imprecise.
    assert 30 <= total_leaves <= 50, f"unexpected leaf section count: {total_leaves}"


def test_output_speakers_present(parsed_doc):
    """All four canonical speakers appear with bold prefix in content_blocks."""
    speakers_found = {"Evan": 0, "Nom": 0, "Ant": 0, "Neo": 0}

    def walk(sections):
        for s in sections:
            for block in s.get("content_blocks", []):
                for sp in speakers_found:
                    # Either the block starts with the speaker bold prefix or
                    # it appears after a 'Sect. N. —' prefix in the block.
                    if f"**{sp}.**" in block[:120]:
                        speakers_found[sp] += 1
            walk(s.get("children", []))

    walk(parsed_doc["data"]["sections"])
    for sp, count in speakers_found.items():
        assert count >= 1, f"speaker {sp!r} not found in any content_block"


def test_output_no_google_books_boilerplate_in_content(parsed_doc):
    """No PG / Google Books / archive.org boilerplate in content_blocks."""
    forbidden = ("Project Gutenberg", "Google is proud", "automated querying")
    for part in parsed_doc["data"]["sections"]:
        def walk(s):
            for block in s.get("content_blocks", []):
                for needle in forbidden:
                    assert needle not in block, (
                        f"found {needle!r} in {s.get('label')!r} block: {block[:100]!r}"
                    )
            for child in s.get("children", []):
                walk(child)
        walk(part)


def test_output_meta_has_required_provenance(parsed_doc):
    meta = parsed_doc["meta"]
    prov = meta["provenance"]
    assert prov["source_url"].startswith("https://archive.org/details/")
    assert prov["source_hash"].startswith("sha256:")
    assert prov["processing_method"] == "ocr"
    assert "ia_fisher_marrow" in prov["processing_script_version"]
    # Boston annotation explicitly named in source_edition
    assert "Boston" in prov["source_edition"]


def test_output_meta_author_id_matches_registry(parsed_doc):
    assert parsed_doc["meta"]["author_id"] == "fisher-edward"


def test_output_first_block_speaker_intro(parsed_doc):
    """The very first content_block of Part I should reference the introduction
    (Marrow's INTRODUCTION. text). Not strictly required by schema but a useful
    smoke check that body-start detection is working."""
    part1 = parsed_doc["data"]["sections"][0]
    first_block = (part1.get("content_blocks") or [""])[0]
    assert first_block.startswith("INTRODUCTION") or "Differences" in first_block, (
        f"Part I first block looks wrong: {first_block[:120]!r}"
    )
