from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "fisher_marrow" / "retained_source_landmarks.json"
CONFIG_PATH = REPO_ROOT / "sources" / "structured-text" / "fisher-marrow-of-modern-divinity" / "config.json"
PAGE_MARKER_RE = re.compile(r"^(?:\d+|[IVXLCDM]+)$", re.IGNORECASE)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

EXPECTED_FALSE_HEADER_TEXT = {
    1656: "part of the law of works ; howbeit, as they are the matterof^ or stand in, ",
    3155: "chap. 7f art. 3> When that promiae or cqrenAnt^ in which the persons it ",
    4579: "chap. ixjv. 'A — 8. See pasje 4Sf note ",
    7146: "part of the co^'etu^nt **f work& is, pnrticulEirly to move them to grow up ",
    7602: "chap. 18, art. 1^3 ; but iin Hssurance which is in fajtli, in tiie direct acts ",
    13507: "part}) and powers of the hduI aod body. Which bcgua sanctitication and ",
    14521: "chap. liii. and xv. Fn the inner main, by virtue of the same penaltyj ",
    15798: "part of man*a life, and in many their whole life, is spent in ",
    17422: 'part of this commandment, in tlicse words, " Thou shalt not ',
    17645: 'part, included in these words, " But thou shalt sanctiSy my ',
    17725: "part, used after an holy and spiritual manner, and that is, ",
    18094: "part, I can scarce clear myself from any of these. ",
    18676: "part it has been in a passion, and not with the spirit of meeknesp^ ",
    19162: "part of this commandment, and tell us what the Lord therein ",
    21145: "part rect^ive and apply to themselves the terrible voice and ",
    21276: 'the condemnatory act, hut for "The Marrow of Modern Divinity," the ',
}


def _load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _line_records(fixture: dict[str, Any]) -> Iterable[dict[str, Any]]:
    yield from fixture["title_imprint_lines"]
    yield from fixture["front_heading_candidates"]
    yield from fixture["part_two_landmarks"]
    yield fixture["appendix_boundary"]
    yield from fixture["known_substantive_false_running_headers"]["items"]
    yield from fixture["representative_ocr_and_inline_mark_lines"]


def test_portable_fixture_preserves_reviewed_fisher_evidence() -> None:
    fixture = _load_fixture()
    source = fixture["source"]

    assert fixture["schema"] == "ocd-fisher-retained-source-landmarks-v1"
    assert "neither reconstructs TEI nor decides witness identity" in fixture["purpose"]
    assert source == {
        "logical_path": "raw/internet-archive/fisher-marrow/marrowmoderndiv00bostgoog_djvu.txt",
        "sha256": "14b46f1a400f8e2c8ec7612019a7769dac46daf31e10f7d6b68212351ff46dd3",
        "byte_length": 1087403,
        "encoding": "utf-8",
        "line_separator": "LF",
        "newline_count": 22945,
        "logical_line_count": 22946,
    }

    conflict = fixture["identity_conflict"]
    assert conflict["status"] == "unresolved-maintainer-authority-required"
    assert conflict["retained_title_page_claim"] == (
        "A NEW EDITION; LONDON; printed for Thomas Tegg and Son; 1837."
    )
    assert conflict["legacy_metadata_claim"] == (
        "Edinburgh: J. and D. Collie, 1828; Thomas Boston annotated edition."
    )
    assert "does not select" in conflict["disposition"]

    spans = fixture["spans"]
    assert (spans["title_page"]["start_line"], spans["title_page"]["end_line"]) == (63, 94)
    recommendations = spans["recommendations"]
    assert (
        recommendations["start_line"],
        recommendations["end_line"],
        recommendations["line_count"],
        recommendations["nonblank_line_count"],
        recommendations["stripped_character_count"],
    ) == (242, 538, 297, 228, 14627)
    assert (
        spans["part_two_title"]["start_line"],
        spans["part_two_title"]["end_line"],
    ) == (16577, 16585)
    assert (
        spans["part_two_editorial_front_matter"]["start_line"],
        spans["part_two_editorial_front_matter"]["end_line"],
    ) == (16577, 16775)
    assert all(SHA256_RE.fullmatch(span["raw_span_sha256"]) for span in spans.values())

    assert {item["line"]: item["text"] for item in fixture["title_imprint_lines"]} == {
        87: "A NBW EDITION. ",
        88: "LONDON: ",
        90: "tINTED FOR THOMAS TE66 AND SON, 73, CHEAPSIDE; ",
        91: "R. GRIFFIN tt CO., GLASGOW; T. T. ft H. TEGG, DUBLIN; ",
        92: "AND 3. WHETHAH, PHILADELPHIA ",
        94: "1837. ",
    }
    assert [item["line"] for item in fixture["front_heading_candidates"]] == [
        242,
        309,
        372,
        446,
        539,
        592,
        636,
        721,
        829,
        889,
        958,
        1015,
    ]
    assert {item["line"]: item["text"] for item in fixture["front_heading_candidates"]} == {
        242: "RECOMMENDATIONS. ",
        309: "RECOMMENDATIONS. ",
        372: "RECOMMENDATIONS, ",
        446: "RECOMMENDATIONS. ",
        539: "X PREFACE. ",
        592: "PREFACE. jii ",
        636: "PREFACE. ",
        721: "DEDICATION. ",
        829: "TO THE READER. ",
        889: "TO THE READER. ",
        958: "TO THE READER, ",
        1015: "TO THE READER. ",
    }
    assert {item["role"]: item["line"] for item in fixture["part_two_landmarks"]} == {
        "part-two-title-start": 16577,
        "part-two-title-label": 16585,
        "part-two-dedication-start": 16591,
        "part-two-reader-address": 16679,
        "part-two-dialogue-boundary": 16776,
    }
    assert {item["line"]: item["text"] for item in fixture["part_two_landmarks"]} == {
        16577: "THE ",
        16585: "FART SECOND. ",
        16591: "TO ",
        16679: "THE AUTHOR TO THE WELL-AFFECTED READER. ",
        16776: "PART SECOND, ",
    }
    assert fixture["appendix_boundary"]["line"] == 21186
    assert fixture["appendix_boundary"]["text"] == "APPENDIX. "

    page_candidates = fixture["page_marker_candidates"]
    candidate_lines = page_candidates["lines"]
    assert page_candidates["count"] == len(candidate_lines) == 170
    assert page_candidates["roman_letter_candidate_count"] == 23
    assert candidate_lines == sorted(set(candidate_lines))
    candidate_line_numbers_sha256 = _sha256(
        json.dumps(candidate_lines, separators=(",", ":")).encode("utf-8")
    )
    assert candidate_line_numbers_sha256 == page_candidates["candidate_line_numbers_sha256"]
    assert candidate_line_numbers_sha256 == (
        "e2478a85557a1bda1e6286a81afdfe58b4f9860929ab93167cc54eb1831b0472"
    )
    assert page_candidates["candidate_list_sha256"] == (
        "e43d89174e96798b7d826db3e751287d516b118d691ec9c6545efc78705c15c0"
    )

    false_headers = fixture["known_substantive_false_running_headers"]
    assert false_headers["count"] == 16
    assert {item["line"]: item["text"] for item in false_headers["items"]} == EXPECTED_FALSE_HEADER_TEXT
    assert fixture["character_census"] == {
        "asterisk": 2039,
        "section_sign": 44,
        "dagger": 0,
        "double_dagger": 0,
    }
    representative = fixture["representative_ocr_and_inline_mark_lines"]
    assert {item["line"]: item["evidence"] for item in representative} == {
        883: "inline-section-sign",
        2304: "inline-section-sign",
        2503: "damaged-chapter-heading",
        15573: "damaged-chapter-heading",
        16727: "standalone-asterisk-near-part-two-front-matter",
        19090: "damaged-commandment-heading",
    }
    assert {item["line"]: item["text"] for item in representative} == {
        883: "§ This sentence, taken frotn the English serrice-honk) is in the Prac- ",
        2304: "§ The covenaat of works could by no means be renc<iPeil by faUeu ",
        2503: "CHAPTER TL ",
        15573: "CHAP. LV. ",
        16727: "* ",
        19090: "COMMANDMENT VHI. ",
    }
    assert all(SHA256_RE.fullmatch(item["raw_line_sha256"]) for item in _line_records(fixture))
    assert fixture["non_authority_notice"]["current_tei"].startswith("Comparator only")
    assert fixture["non_authority_notice"]["human_decision"] == (
        "Candidate generation remains separate from maintainer acceptance."
    )


def test_retained_raw_bytes_match_every_fixture_span_and_landmark() -> None:
    fixture = _load_fixture()
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    source = fixture["source"]
    assert config["source_file"] == source["logical_path"]

    raw_path = REPO_ROOT / source["logical_path"]
    if not raw_path.is_file():
        pytest.skip("retained Fisher OCR is unavailable in this checkout")

    raw = raw_path.read_bytes()
    assert len(raw) == source["byte_length"]
    assert _sha256(raw) == source["sha256"]
    assert raw.count(b"\n") == source["newline_count"]
    parts = raw.split(b"\n")
    assert len(parts) == source["logical_line_count"]

    for span in fixture["spans"].values():
        start = span["start_line"]
        end = span["end_line"]
        payload = b"\n".join(parts[start - 1 : end])
        decoded = [part.decode(source["encoding"]) for part in parts[start - 1 : end]]
        assert end - start + 1 == span["line_count"]
        assert len(payload) == span["raw_byte_length"]
        assert _sha256(payload) == span["raw_span_sha256"]
        assert sum(bool(line.strip()) for line in decoded) == span["nonblank_line_count"]
        assert sum(len(line.strip()) for line in decoded if line.strip()) == span["stripped_character_count"]

    for record in _line_records(fixture):
        payload = parts[record["line"] - 1]
        assert payload.decode(source["encoding"]) == record["text"]
        assert len(payload) == record["raw_byte_length"]
        assert _sha256(payload) == record["raw_line_sha256"]

    derived_page_candidates = []
    roman_letter_candidates = 0
    for number, payload in enumerate(parts, start=1):
        if number < fixture["page_marker_candidates"]["scope_start_line"]:
            continue
        text = payload.decode(source["encoding"])
        stripped = text.strip()
        if PAGE_MARKER_RE.fullmatch(stripped):
            derived_page_candidates.append(
                {"line": number, "text": text, "raw_line_sha256": _sha256(payload)}
            )
            roman_letter_candidates += not stripped.isdigit()

    page_candidates = fixture["page_marker_candidates"]
    assert [item["line"] for item in derived_page_candidates] == page_candidates["lines"]
    assert len(derived_page_candidates) == page_candidates["count"]
    assert roman_letter_candidates == page_candidates["roman_letter_candidate_count"]
    serialized_candidates = json.dumps(
        derived_page_candidates,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    assert _sha256(serialized_candidates) == page_candidates["candidate_list_sha256"]

    text = raw.decode(source["encoding"])
    assert {
        "asterisk": text.count("*"),
        "section_sign": text.count("§"),
        "dagger": text.count("†"),
        "double_dagger": text.count("‡"),
    } == fixture["character_census"]
