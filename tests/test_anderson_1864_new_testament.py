from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from lxml import etree

from build.tei import anderson_1864_new_testament as anderson
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.tei.validate import compiled_schema


ROOT = Path(__file__).resolve().parents[1]


def test_pinned_authority_and_complete_census() -> None:
    config = anderson._load_config(ROOT)
    assert config["source_commit"] == "abfccf6965b4c47781843930907b1ac180e9b4a3"
    source = resolve_repo_path(ROOT, config["source_root"])
    evidence = anderson._validate_authority_root(source, config)
    assert evidence["member_ids"] == list(anderson.MEMBER_IDS)
    assert (evidence["book_count"], evidence["paratext_count"]) == (27, 3)
    assert (evidence["chapter_count"], evidence["verse_count"]) == (260, 7946)
    assert evidence["inline_marker_counts"]["add"] == 98
    assert evidence["inline_marker_counts"]["w"] == 23


def test_candidate_valid_roundtrips_and_accounts() -> None:
    outputs = anderson._build_candidate(ROOT)
    tei = etree.fromstring(outputs["content.tei.xml"], parser=etree.XMLParser(huge_tree=True))
    compiled_schema().assertValid(etree.ElementTree(tei))
    account = json.loads(outputs["source-accountability.json"])
    assert account["source_file_roundtrip_exact"] is True
    assert account["source_files_verified"] == 30
    assert account["text_counts"]["books"] == 27
    assert len(tei.xpath(".//tei:div[@type='book']", namespaces={"tei": anderson.TEI_NS})) == 27
    assert len(tei.xpath(".//tei:ab[@type='verse']", namespaces={"tei": anderson.TEI_NS})) == 7946


def test_front_matter_glossary_and_year_discrepancy_are_explicit() -> None:
    outputs = anderson._build_candidate(ROOT)
    tei = etree.fromstring(outputs["content.tei.xml"], parser=etree.XMLParser(huge_tree=True))
    assert tei.xpath(".//tei:div[@n='FRT' and @type='paratext']", namespaces={"tei": anderson.TEI_NS})
    assert tei.xpath(".//tei:div[@n='GLO' and @type='paratext']", namespaces={"tei": anderson.TEI_NS})
    assert len(tei.xpath(".//tei:term[@type='glossary-keyword']", namespaces={"tei": anderson.TEI_NS})) == 23
    boundaries = json.loads(outputs["witness-boundaries.json"])
    assert boundaries["print_witness_title_year"] == "1865"
    assert boundaries["print_witness_copyright_year"] == "1864"
    assert boundaries["bibliographic_year_discrepancy_requires_human_review"] is True


def test_opening_middle_ending_exact_source_lines() -> None:
    outputs = anderson._build_candidate(ROOT)
    tei = etree.fromstring(outputs["content.tei.xml"], parser=etree.XMLParser(huge_tree=True))
    samples = (("ENG[B1]Anderson1864[pd]USFM-00.sfm", 6, "\\mt1 New Testament."), ("ENG[B1]Anderson1864[pd]USFM-46.sfm", 1, "\\id ROM"), ("ENG[B1]Anderson1864[pd]USFM-67.sfm", 1, "\\id REV"), ("ENG[B1]Anderson1864[pd]USFM-69.sfm", 13, "\\mte THE END."))
    for name, line, prefix in samples:
        pointer = anderson._pointer(Path(name), line)
        nodes = tei.xpath("//*[@corresp=$pointer]", pointer=pointer)
        assert len(nodes) == 1
        raw = nodes[0].xpath("./tei:note[@type='source-usfm-raw']/text()", namespaces={"tei": anderson.TEI_NS})
        assert raw[0].startswith(prefix)


def test_fresh_process_different_cwd_is_identical(tmp_path: Path) -> None:
    expected = {k: hashlib.sha256(v).hexdigest() for k, v in anderson._build_candidate(ROOT).items()}
    code = "import hashlib,json,sys;sys.path.insert(0," + repr(str(ROOT)) + ");from pathlib import Path;from build.tei.anderson_1864_new_testament import _build_candidate;o=_build_candidate(Path(" + repr(str(ROOT)) + "));print(json.dumps({k:hashlib.sha256(v).hexdigest() for k,v in o.items()},sort_keys=True))"
    env = dict(os.environ); env["PYTHONPYCACHEPREFIX"] = str(tmp_path / "pycache")
    result = subprocess.run([sys.executable, "-B", "-c", code], cwd=tmp_path, env=env, check=True, capture_output=True, text=True)
    assert json.loads(result.stdout) == expected
