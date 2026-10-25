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

from build.tei import revised_version_with_apocrypha as rv
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.tei.validate import compiled_schema


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = (
    REPOSITORY_ROOT
    / "sources"
    / "structured-text"
    / "revised-version-with-apocrypha"
    / "config.json"
)
NS = {"tei": rv.TEI_NS}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def config() -> dict[str, object]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def candidate() -> dict[str, bytes]:
    return rv._build_candidate(REPOSITORY_ROOT)


@pytest.fixture(scope="module")
def tei(candidate: dict[str, bytes]) -> etree._Element:
    return etree.fromstring(candidate["content.tei.xml"])


def test_config_binds_exact_official_carriers_and_witnesses(
    config: dict[str, object],
) -> None:
    assert config["resource_id"] == "revised-version-with-apocrypha"
    assert config["source_edition"].startswith("Complete 1895 Revised Version")
    assert config["candidate_status"] == "nonaccepted"

    authority = config["authority"]
    comparison = config["comparison_carrier"]
    authority_archive = resolve_repo_path(REPOSITORY_ROOT, config["source_file"])
    comparison_archive = resolve_repo_path(
        REPOSITORY_ROOT, config["comparison_source_file"]
    )
    assert authority_archive.stat().st_size == authority["archive_bytes"]
    assert _sha(authority_archive) == authority["archive_sha256"]
    assert comparison_archive.stat().st_size == comparison["archive_bytes"]
    assert _sha(comparison_archive) == comparison["archive_sha256"]

    for witness in config["witnesses"]:
        path = resolve_repo_path(REPOSITORY_ROOT, witness["path"])
        assert path.stat().st_size == witness["bytes"]
        assert _sha(path) == witness["sha256"]


def test_authority_has_complete_declared_canon_and_exact_member_inventory(
    config: dict[str, object],
) -> None:
    source_root = resolve_repo_path(REPOSITORY_ROOT, config["source_root"])
    evidence = rv._validate_authority_root(source_root, config)
    assert evidence["member_count"] == 83
    assert evidence["book_file_count"] == 80
    assert evidence["book_ids"] == list(
        rv.OT_IDS + rv.APOCRYPHA_FILE_IDS + rv.NT_IDS
    )
    assert evidence["member_inventory_sha256"] == config["authority"][
        "member_inventory_sha256"
    ]
    assert evidence["chapter_count"] == 1362
    assert evidence["verse_count"] == 36878
    assert evidence["source_line_count"] == 47631
    assert evidence["terminal_newline_files"] == 0
    assert evidence["baruch_epistle_of_jeremy"] is True


def test_usfx_comparison_carrier_matches_book_chapter_and_verse_census(
    config: dict[str, object],
) -> None:
    evidence = rv._validate_comparison_carrier(REPOSITORY_ROOT, config)
    assert evidence == {
        "book_count": 80,
        "chapter_count": 1362,
        "verse_count": 36878,
        "book_ids": list(rv.OT_IDS + rv.APOCRYPHA_FILE_IDS + rv.NT_IDS),
        "member_count": 8,
        "member_inventory_sha256": config["comparison_carrier"][
            "member_inventory_sha256"
        ],
    }


def test_candidate_is_valid_tei_and_accounts_every_textual_unit(
    candidate: dict[str, bytes], tei: etree._Element
) -> None:
    compiled_schema().assertValid(etree.ElementTree(tei))
    accountability = json.loads(candidate["source-accountability.json"])
    assert accountability["tei_p5_valid"] is True
    assert accountability["source_file_roundtrip_exact"] is True
    assert accountability["text_counts"] == {
        "old_testament_books": 39,
        "apocrypha_file_members": 14,
        "apocrypha_units": 15,
        "new_testament_books": 27,
        "chapters": 1362,
        "verses": 36878,
        "source_lines": 47631,
        "word_links": 714769,
        "supplied_text_spans": 5131,
        "footnotes": 1336,
        "cross_references": 19,
        "poetry_lines": 6884,
    }
    assert len(tei.xpath(".//tei:div[@type='book']", namespaces=NS)) == 80
    assert len(tei.xpath(".//tei:div[@type='chapter']", namespaces=NS)) == 1362
    assert len(tei.xpath(".//tei:ab[@type='verse']", namespaces=NS)) == 36878
    assert len(tei.xpath(".//tei:w", namespaces=NS)) == 714769
    assert len(tei.xpath(".//tei:supplied", namespaces=NS)) == 5131
    assert len(tei.xpath(".//tei:note[@type='footnote']", namespaces=NS)) == 1336
    assert len(tei.xpath(".//tei:note[@type='cross-reference']", namespaces=NS)) == 19


def test_every_usfm_source_file_reopens_exactly_from_tei(
    config: dict[str, object], candidate: dict[str, bytes]
) -> None:
    source_root = resolve_repo_path(REPOSITORY_ROOT, config["source_root"])
    evidence = rv._verify_source_files(candidate["content.tei.xml"], source_root)
    assert evidence == {
        "source_file_roundtrip_exact": True,
        "source_files_verified": 80,
        "source_lines_verified": 47631,
    }


def test_opening_middle_ending_and_unusual_source_lines_are_exact(
    tei: etree._Element,
) -> None:
    expected = {
        "source-usfm:eng-rv/02-GENeng-rv.usfm#line=8": "\\mt1 GENESIS.  ",
        "source-usfm:eng-rv/40-MALeng-rv.usfm#line=69": "\\v 6 And he shall turn the heart of the fathers to the children, and the heart of the children to their fathers; lest I come and smite the earth with \\w a|strong=\"H3068\"\\w* curse.",
        "source-usfm:eng-rv/41-TOBeng-rv.usfm#line=9": "\\v 1 THE book of the words of Tobit, the son of Tobiel, the son of Ananiel, the son of Aduel, the son of Gabael, of the seed of Asiel, of the tribe of Naphtali;  ",
        "source-usfm:eng-rv/47-BAReng-rv.usfm#line=162": "\\ms1 THE EPISTLE OF JEREMY.  ",
        "source-usfm:eng-rv/46-SIReng-rv.usfm#line=954": "\\v 15-16 ",
        "source-usfm:eng-rv/96-REVeng-rv.usfm#line=455": "\\v 21 \\w The|strong=\"G3956\"\\w* \\w grace|strong=\"G5485\"\\w*",
    }
    for pointer, prefix in expected.items():
        nodes = tei.xpath(f".//*[@corresp='{pointer}']", namespaces=NS)
        assert len(nodes) == 1
        raw = nodes[0].xpath(
            "./tei:note[@type='source-usfm-raw']/text()", namespaces=NS
        )
        assert len(raw) == 1
        assert raw[0].startswith(prefix)

    assert tei.xpath(
        ".//tei:div[@type='chapter' and @n='6' and @ana='#epistle-of-jeremy']",
        namespaces=NS,
    )
    assert tei.xpath(".//tei:ab[@type='verse' and @n='15-16']", namespaces=NS)


def test_witness_boundaries_are_explicit_and_nonprojected(
    candidate: dict[str, bytes]
) -> None:
    boundaries = json.loads(candidate["witness-boundaries.json"])
    assert boundaries["structured_authority"] == "eBible eng-rv USFM package"
    assert boundaries["replacement_witnesses"] == {
        "TOB_RV.pdf": "Tobit scan retained for whole-Bible scan drop-outs; evidence only",
        "ESG_RV.pdf": "Greek Esther scan retained for whole-Bible scan drop-outs; evidence only",
    }
    assert boundaries["apocrypha_accounting"]["file_members"] == 14
    assert boundaries["apocrypha_accounting"]["textual_units"] == 15
    assert boundaries["apocrypha_accounting"]["embedded_unit"] == {
        "source_member": "47-BAReng-rv.usfm",
        "chapter": "6",
        "title": "THE EPISTLE OF JEREMY.",
    }
    assert "title leaf" in boundaries["print_only_prelims_1895"]
    assert "preface" in boundaries["print_only_prelims_1895"]
    assert boundaries["print_prelims_projected_to_tei"] is False
    assert boundaries["candidate_status"] == "nonaccepted"


def test_authority_inventory_rejects_a_mutated_source(
    config: dict[str, object], tmp_path: Path
) -> None:
    source_root = resolve_repo_path(REPOSITORY_ROOT, config["source_root"])
    modified = tmp_path / "usfm"
    shutil.copytree(source_root, modified)
    genesis = modified / "02-GENeng-rv.usfm"
    genesis.write_bytes(genesis.read_bytes().replace(b"GENESIS", b"GENES1S", 1))
    with pytest.raises(ValueError, match="authority member inventory digest mismatch"):
        rv._validate_authority_root(modified, config)


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
        "from build.tei.revised_version_with_apocrypha import _build_candidate;"
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
