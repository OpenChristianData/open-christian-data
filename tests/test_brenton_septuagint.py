from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from lxml import etree
import pytest

from build.tei import brenton_septuagint as brenton
from build.tei.brenton_septuagint_oracle import verify as verify_readable_tei
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.tei.validate import compiled_schema


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
NS = {"tei": brenton.TEI_NS}


@pytest.fixture(scope="module")
def config() -> dict[str, object]:
    return brenton._load_config(REPOSITORY_ROOT)


@pytest.fixture(scope="module")
def candidate() -> dict[str, bytes]:
    return brenton._build_candidate(REPOSITORY_ROOT)


@pytest.fixture(scope="module")
def tei(candidate: dict[str, bytes]) -> etree._Element:
    return etree.fromstring(
        candidate["content.tei.xml"],
        parser=etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True),
    )


def test_config_binds_the_exact_corrected_eng_brenton_expression(
    config: dict[str, object],
) -> None:
    assert config["resource_id"] == "brenton-septuagint"
    assert config["source_files_dated"] == "2025-12-12"
    assert config["authority"] == {
        "archive_bytes": 1438240,
        "archive_sha256": "93496ef23f7ff2427c32f5d353089dee73e82975ab92c80a00663fb333c57e32",
        "member_count": 63,
        "member_inventory_sha256": "2a8580e1772b746c3c25b1291db9aaf706accba1523313c5d84f1a1477ff6ca7",
        "usfm_file_count": 60,
        "textual_book_count": 53,
        "paratext_file_count": 7,
    }
    assert config["candidate_status"] == "nonaccepted"


def test_authority_and_comparison_censuses_are_complete(
    config: dict[str, object],
) -> None:
    authority_root = resolve_repo_path(REPOSITORY_ROOT, config["source_root"])
    authority = brenton._validate_authority_root(authority_root, config)
    comparison = brenton._validate_comparison_carrier(REPOSITORY_ROOT, config)
    assert authority["member_ids"] == list(brenton.MEMBER_IDS)
    assert comparison["member_ids"] == list(brenton.MEMBER_IDS)
    assert authority["usfm_file_count"] == comparison["member_count"] == 60
    assert authority["chapter_count"] == comparison["chapter_count"] == 1118
    assert authority["verse_count"] == comparison["verse_count"] == 29005
    assert authority["source_line_count"] == 38382
    assert authority["line_marker_counts"]["tr"] == 51
    assert authority["line_marker_counts"]["tc1"] == 51
    assert authority["line_marker_counts"]["tc2"] == 51
    assert authority["inline_marker_counts"]["f"] == 2600
    assert authority["inline_marker_counts"]["x"] == 150
    assert authority["inline_marker_counts"]["add"] == 9086
    assert authority["inline_marker_counts"]["vp"] == 73


def test_candidate_is_valid_and_accounts_for_canon_and_paratext(
    candidate: dict[str, bytes], tei: etree._Element
) -> None:
    compiled_schema().assertValid(etree.ElementTree(tei))
    accountability = json.loads(candidate["source-accountability.json"])
    assert accountability["source_file_roundtrip_exact"] is True
    assert accountability["source_files_verified"] == 60
    assert accountability["text_counts"] == {
        "textual_books": 53,
        "paratext_members": 7,
        "chapters": 1118,
        "verse_records": 29005,
        "source_lines": 38382,
        "footnotes": 2600,
        "cross_references": 150,
        "supplied_text_spans": 9086,
        "small_caps_spans": 202,
        "italic_spans": 142,
        "verse_number_spans": 73,
        "table_rows": 51,
        "table_cells": 102,
    }
    assert len(tei.xpath("./tei:text/tei:body/tei:div", namespaces=NS)) == 60
    assert len(tei.xpath(".//tei:div[@type='book']", namespaces=NS)) == 53
    assert len(tei.xpath(".//tei:div[@type='paratext']", namespaces=NS)) == 7
    assert len(tei.xpath(".//tei:ab[@type='verse']", namespaces=NS)) == 29005
    assert len(tei.xpath(".//tei:note[@type='footnote']", namespaces=NS)) == 2600
    assert len(tei.xpath(".//tei:note[@type='cross-reference']", namespaces=NS)) == 150
    assert len(tei.xpath(".//tei:supplied", namespaces=NS)) == 9086
    assert len(tei.xpath(".//tei:table/tei:row", namespaces=NS)) == 51


def test_every_usfm_member_reopens_exactly_from_tei(
    config: dict[str, object], candidate: dict[str, bytes]
) -> None:
    source_root = resolve_repo_path(REPOSITORY_ROOT, config["source_root"])
    assert brenton._verify_source_files(candidate["content.tei.xml"], source_root) == {
        "source_file_roundtrip_exact": True,
        "source_files_verified": 60,
        "source_lines_verified": 38382,
    }


def test_opening_canon_terminal_paratext_and_ending_are_exact(
    tei: etree._Element,
) -> None:
    expected = {
        "source-usfm:eng-Brenton/00-FRTeng-Brenton.usfm#line=6": "\\mt1 ABBREVIATIONS",
        "source-usfm:eng-Brenton/01-INTeng-Brenton.usfm#line=6": "\\mt1 INTRODUCTION [1870]",
        "source-usfm:eng-Brenton/02-GENeng-Brenton.usfm#line=9": "\\v 1 \\sc In\\sc* the beginning",
        "source-usfm:eng-Brenton/57-3MAeng-Brenton.usfm#line=9": "\\v 1 \\sc Now\\sc* Philopater",
        "source-usfm:eng-Brenton/59-4MAeng-Brenton.usfm#line=647": "\\v 24 To whom be glory",
        "source-usfm:eng-Brenton/97-BAKeng-Brenton.usfm#line=8": "\\ip 2 Kings (2 Sam.) 5. 18.",
        "source-usfm:eng-Brenton/98-OTHeng-Brenton.usfm#line=6": "\\mt1 THE BOOKS OF THE APOCRYPHA",
        "source-usfm:eng-Brenton/99-XXAeng-Brenton.usfm#line=8": "\\tr",
        "source-usfm:eng-Brenton/100-XXBeng-Brenton.usfm#line=6": "\\mt1 PREFACE [1844]",
        "source-usfm:eng-Brenton/101-XXCeng-Brenton.usfm#line=326": "\\im 1870. period included",
    }
    for pointer, prefix in expected.items():
        nodes = tei.xpath("//*[@corresp=$pointer]", pointer=pointer)
        assert len(nodes) == 1
        raw = nodes[0].xpath(
            "./tei:note[@type='source-usfm-raw']/text()", namespaces=NS
        )
        assert len(raw) == 1
        assert raw[0].startswith(prefix)


def test_unusual_features_and_electronic_corrections_are_explicit(
    candidate: dict[str, bytes], tei: etree._Element
) -> None:
    assert tei.xpath(".//tei:hi[@rend='small-caps']", namespaces=NS)
    assert tei.xpath(".//tei:hi[@rend='italic']", namespaces=NS)
    assert tei.xpath(".//tei:seg[@type='source-verse-number']", namespaces=NS)
    assert tei.xpath(".//tei:table[@type='source-table']", namespaces=NS)
    boundaries = json.loads(candidate["witness-boundaries.json"])
    assert boundaries["electronic_corrections"]["documented_by"] == "101-XXCeng-Brenton.usfm"
    assert boundaries["print_only_content_claimed"] is False
    assert boundaries["structured_and_pdf_terminal_order_differs"] is True
    assert boundaries["candidate_status"] == "nonaccepted"


def test_authority_inventory_rejects_a_mutated_source(
    config: dict[str, object], tmp_path: Path
) -> None:
    source_root = resolve_repo_path(REPOSITORY_ROOT, config["source_root"])
    modified = tmp_path / "usfm"
    shutil.copytree(source_root, modified)
    genesis = modified / "02-GENeng-Brenton.usfm"
    genesis.write_bytes(genesis.read_bytes().replace(b"GENESIS", b"GENES1S", 1))
    with pytest.raises(ValueError, match="authority member inventory digest mismatch"):
        brenton._validate_authority_root(modified, config)


def test_fresh_process_different_cwd_is_byte_identical(
    candidate: dict[str, bytes], tmp_path: Path
) -> None:
    expected = {
        name: hashlib.sha256(content).hexdigest()
        for name, content in sorted(candidate.items())
    }
    code = (
        "import hashlib,json,sys;"
        f"sys.path.insert(0,{str(REPOSITORY_ROOT)!r});"
        "from pathlib import Path;"
        "from build.tei.brenton_septuagint import _build_candidate;"
        f"o=_build_candidate(Path({str(REPOSITORY_ROOT)!r}));"
        "print(json.dumps({k:hashlib.sha256(v).hexdigest() for k,v in sorted(o.items())},sort_keys=True))"
    )
    environment = dict(os.environ)
    environment["PYTHONPYCACHEPREFIX"] = str(tmp_path / "pycache")
    completed = subprocess.run(
        [sys.executable, "-B", "-c", code],
        cwd=tmp_path,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(completed.stdout) == expected


def test_independent_readable_oracle_covers_retained_member_set() -> None:
    path = REPOSITORY_ROOT / brenton.DEFAULT_OUTPUT / "content.tei.xml"
    assert verify_readable_tei(REPOSITORY_ROOT, path) == {
        "member_count": 60,
        "source_pointers": 38382,
        "source_lines": 37204,
        "table_rows": 51,
        "table_cells": 102,
        "chapters": 1118,
        "verses": 29005,
    }


@pytest.mark.parametrize("damage", ["readable-text", "verse-attachment", "inline-role"])
def test_independent_oracle_rejects_readable_corruption(
    damage: str, tmp_path: Path
) -> None:
    source = REPOSITORY_ROOT / brenton.DEFAULT_OUTPUT / "content.tei.xml"
    xml = etree.parse(str(source), parser=etree.XMLParser(huge_tree=True))
    verse = xml.xpath(
        "//*[@corresp='source-usfm:eng-Brenton/02-GENeng-Brenton.usfm#line=9']"
    )[0]
    if damage == "readable-text":
        verse[-1].tail = (verse[-1].tail or "") + " invented"
        message = "readable text differs"
    elif damage == "verse-attachment":
        verse.set("n", "2")
        message = "verse role or number differs"
    else:
        verse.xpath("./tei:hi[@rend='small-caps']", namespaces=NS)[0].set("rend", "italic")
        message = "inline roles differ"
    candidate = tmp_path / "damaged.xml"
    candidate.write_bytes(etree.tostring(xml, encoding="UTF-8", xml_declaration=True))
    with pytest.raises(ValueError, match=message):
        verify_readable_tei(REPOSITORY_ROOT, candidate)
