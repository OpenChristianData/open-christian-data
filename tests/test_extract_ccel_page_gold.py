"""Tests for the CCEL page-gold *proposal* extractor.

Two layers:
  * Unit tests on a small synthetic ThML snippet that mirrors the REAL structure
    observed in encyc01.xml -- ``<pb n>`` is an empty milestone embedded inside a
    ``<p>``, with page content flowing as element tail text.
  * Integration assertions against the real (gitignored) CCEL XML + committed IA
    manifest, derived from content verified word-for-word against the scans at
    pages 1 and 100. These skip when the gitignored CCEL cache is absent (CI).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from build.tools.ocr_pipeline import extract_ccel_page_gold as mod

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_XML = REPO_ROOT / "raw" / "ccel" / "schaff" / "encyc01.xml"
REAL_MANIFEST = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages" / "vol_01.manifest.json"

# Mirrors real encyc01.xml structure: pb milestones inside a <p>, content as tail.
SYNTHETIC_THML = """<?xml version="1.0" encoding="UTF-8"?>
<ThML>
<ThML.body>
<div1>
<p>front<pb n="i" />roman front matter text<pb n="1" />Page one body
<span class="sc">WORD</span> continues here.<pb n="2" />Page two starts
<i>italic</i> and ends.<pb n="3" />Page three only.</p>
</div1>
</ThML.body>
</ThML>
"""


@pytest.fixture()
def synthetic_xml(tmp_path: Path) -> Path:
    p = tmp_path / "encyc99.xml"
    p.write_text(SYNTHETIC_THML, encoding="utf-8")
    return p


def test_extract_page_texts_segments_on_pb(synthetic_xml: Path):
    pages = mod.extract_page_texts(synthetic_xml)
    # roman page "i" must be dropped (only arabic body pages kept)
    assert set(pages) == {1, 2, 3}
    assert pages[1] == "Page one body WORD continues here."
    assert pages[2] == "Page two starts italic and ends."
    assert pages[3] == "Page three only."


def test_extract_page_texts_excludes_roman_front_matter(synthetic_xml: Path):
    pages = mod.extract_page_texts(synthetic_xml)
    assert all(isinstance(k, int) for k in pages)
    assert "roman front matter" not in " ".join(pages.values())


def test_strip_tag_drops_namespace():
    assert mod._strip_tag("{http://www.ccel.org/ns/ThML/1.0}pb") == "pb"
    assert mod._strip_tag("pb") == "pb"


def test_build_proposal_status_is_not_gold(synthetic_xml: Path, tmp_path: Path):
    # minimal manifest so scan_map yields page->scan for page 1.
    # local_path is manifest-relative; scan_map resolves it against the manifest dir.
    scan = tmp_path / "vol_99" / "page_0001.jpg"
    scan.parent.mkdir(parents=True)
    scan.write_bytes(b"\xff\xd8\xff")  # tiny JPEG header stand-in
    manifest = tmp_path / "vol_99.manifest.json"
    manifest.write_text(
        json.dumps({"pages": [{"page_num": 1, "local_path": "vol_99/page_0001.jpg"}]}),
        encoding="utf-8",
    )

    proposal = mod.build_proposal(
        volume=99, xml_path=synthetic_xml, manifest_path=manifest, generated_at="2026-01-01T00:00:00Z"
    )
    assert proposal["artifact_kind"] == "ccel-page-gold-proposal"
    assert proposal["status"] == "PROPOSAL_NOT_GOLD"
    # never asserts gold fields
    assert "schema_version" not in proposal
    assert all("verification" not in r and "ground_truth_text" not in r for r in proposal["pages"])
    assert any("NOT a gold-record-v1" in c for c in proposal["caveats"])
    assert proposal["coverage"]["pages_proposed"] == 1


def test_parse_pages_ranges_and_singletons():
    assert mod._parse_pages([]) is None
    assert mod._parse_pages(["10-12"]) == [10, 11, 12]
    assert mod._parse_pages(["3", "1", "1"]) == [1, 3]


def test_script_mode_bootstrap_resolves_repo_root():
    """The sys.path bootstrap must reach the repo root, not build/.

    Regression: the file lives in build/tools/ocr_pipeline/, so the bootstrap
    needs parents[3] (not parents[2], which lands at build/ and makes
    `from build.lib...` fail with ModuleNotFoundError when run as a script).
    Unit tests miss this because pytest already has the repo root on sys.path.
    """
    module_file = Path(mod.__file__).resolve()
    # parents[3] of build/tools/ocr_pipeline/extract_ccel_page_gold.py is the repo root
    repo_root = module_file.parents[3]
    assert (repo_root / "build" / "lib" / "paths.py").exists()
    assert mod._BOOTSTRAP_ROOT == repo_root


# --- Integration against verified real data (skips without the gitignored cache) ---

requires_real = pytest.mark.skipif(
    not (REAL_XML.exists() and REAL_MANIFEST.exists()),
    reason="real CCEL encyc01.xml (gitignored) or vol_01 manifest absent",
)


@requires_real
def test_real_vol01_has_500_arabic_pages():
    pages = mod.extract_page_texts(REAL_XML)
    assert len(pages) == 500
    assert min(pages) == 1 and max(pages) == 500


@requires_real
def test_real_page1_matches_scan_content():
    # verified word-for-word against leaf_0037.jpg (the printed page 1 scan)
    pages = mod.extract_page_texts(REAL_XML)
    p1 = pages[1]
    assert "THE NEW SCHAFF-HERZOG" in p1
    assert "AACHEN" in p1
    assert "SYNODS OF" in p1
    assert "AARON" in p1  # page 1 runs into the start of the AARON article


@requires_real
def test_real_page100_matches_scan_content():
    pages = mod.extract_page_texts(REAL_XML)
    p100 = pages[100]
    assert "Clement VII" in p100
    assert "Ailly" in p100


@requires_real
def test_real_scan_map_page1_is_leaf_0037():
    scans = mod.scan_map(REAL_MANIFEST)
    assert scans[1]["page_native_id"] == "page_0001"
    # Model-B rebuild: page 100 == page_0100 (the old +2 squeeze offset that
    # produced page_0102 is gone; local_path now resolves to the live vol_01 dir).
    assert scans[100]["page_native_id"] == "page_0100"


@requires_real
def test_real_proposal_pages_have_text_and_scan():
    proposal = mod.build_proposal(
        volume=1, xml_path=REAL_XML, manifest_path=REAL_MANIFEST, pages=[1, 100], generated_at="2026-01-01T00:00:00Z"
    )
    assert proposal["coverage"]["pages_proposed"] == 2
    for rec in proposal["pages"]:
        assert rec["char_count"] > 100
        assert rec["scan_path"].startswith("raw/internet-archive/")
        assert rec["ccel_page_text"]


def test_build_proposal_page_carries_body_edition_page_key(synthetic_xml: Path, tmp_path: Path):
    scan = tmp_path / "vol_99" / "page_0002.jpg"
    scan.parent.mkdir(parents=True)
    scan.write_bytes(b"\xff\xd8\xff")
    manifest = tmp_path / "vol_99.manifest.json"
    manifest.write_text(
        json.dumps({"pages": [{"page_num": 2, "local_path": "vol_99/page_0002.jpg"}]}),
        encoding="utf-8",
    )

    proposal = mod.build_proposal(
        volume=99,
        xml_path=synthetic_xml,
        manifest_path=manifest,
        pages=[2],
        generated_at="2026-01-01T00:00:00Z",
    )

    assert proposal["pages"][0]["edition_page_key"] == {"section": "body", "anchor": 2, "ordinal": 0}
