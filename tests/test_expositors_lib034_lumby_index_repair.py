"""Exact source and accepted-master semantics for Lumby's index repair."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import shutil

from lxml import etree
import pytest

from build.tei.expositors_bible_lib034_readable_lumby_index_v2_oracle import check
from build.tools.stage_expositors_lib034_lumby_index_repair import OLD_MASTER_SHA, _source_only_delta
from ocd_kernel.tei.install_accepted import _files, _io_path


MEMBER = "lumby-expositorpeter"
CANDIDATE = Path(
    "D:/Library/Open Christian Data/candidate-reviews/"
    "expositors-lib034-lumby-index-v2-candidate-20260928-v1/lumby-expositorpeter"
)
STAGE = Path(
    "D:/Library/Open Christian Data/candidate-reviews/"
    "expositors-lib034-lumby-index-repair-stage-20260928-v1"
)
WORK = Path("library/works/expositors-bible--j-rawson-lumby")
NS = "{http://www.tei-c.org/ns/1.0}"

# Exact receipt-bound inverse; the retained accepted payload stays local.
STAGED_MASTER_SHA = '2cbb1dee885daf530f81d30b77ffdfaeb8e02302449aa45c6ec1ec385b230bc3'
ORIGINAL_MASTER_INVERSE = (
    (39, b'<TEI xmlns="http://www.tei-c.org/ns/1.0" xml:id="lumby-expositorpeter"><teiHeader><fileDesc><titleStmt><title>The Expositor\'s Bible: The Epistles of St. Peter</title></titleStmt><publicationStmt><p>Christian Classics Ethereal Library electronic witness; rights and publication require separate review.</p></publicationStmt><sourceDesc><bibl><title>Retained CCEL ThML electronic witness by J. Rawson Lumby; SHA-256 a41460490dcf5aaf4b46b987dc82f097c557c5cbc8f9e9c9ff848c7563309abc</title></bibl><bibl xmlns="http://www.tei-c.org/ns/1.0"><ptr target="https://www.ccel.org/ccel/lumby/expositorpeter.html"/><idno type="acquisition_id">expositors-bible--j-rawson-lumby--lumby-expositorpeter--acquired</idno><idno type="edition_id">expositors-bible--j-rawson-lumby--lumby-expositorpeter--ccel-electronic</idno><idno type="textual_form_id">expositors-bible--j-rawson-lumby--lumby-expositorpeter--retained-en</idno><idno type="work_id">expositors-bible--j-rawson-lumby</idno><idno type="source_sha256">a41460490dcf5aaf4b46b987dc82f097c557c5cbc8f9e9c9ff848c7563309abc</idno><idno type="source_bytes">678452</idno><idno type="representation_revision">lumby-expositorpeter-ccel-electronic-index-v2</idno><idno type="sha256">a41460490dcf5aaf4b46b987dc82f097c557c5cbc8f9e9c9ff848c7563309abc</idno><note type="source-location">raw/ccel/expositors-bible/lumby_expositorpeter.xml</note><note type="source-scope">Complete retained CCEL ThML XML file for The Expositor\'s Bible: The Epistles of St. Peter. This author-cohort catalog ID does not resolve independent work or print-edition identity; source accounting only.</note></bibl></sourceDesc></fileDesc><revisionDesc xmlns="http://www.tei-c.org/ns/1.0"><change xmlns="http://www.tei-c.org/ns/1.0" xml:id="lumby-expositorpeter-ccel-electronic-index-v2" when="2026-09-27">Correct four source Index containers from quotation to index divisions; retain the complete electronic text and edition identity.</change></revisionDesc></teiHeader><text xml:lang="en"><front xml:id="lumby-expositorpeter-front">\n', b'<TEI xmlns="http://www.tei-c.org/ns/1.0" xml:id="lumby-expositorpeter"><teiHeader><fileDesc><titleStmt><title>The Expositor\'s Bible: The Epistles of St. Peter</title></titleStmt><publicationStmt><p>Christian Classics Ethereal Library electronic witness; rights and publication require separate review.</p></publicationStmt><sourceDesc><bibl><title>Retained CCEL ThML electronic witness by J. Rawson Lumby; SHA-256 a41460490dcf5aaf4b46b987dc82f097c557c5cbc8f9e9c9ff848c7563309abc</title></bibl><bibl xmlns="http://www.tei-c.org/ns/1.0"><ptr target="https://www.ccel.org/ccel/lumby/expositorpeter.html"/><idno type="work_id">expositors-bible--j-rawson-lumby</idno><idno type="textual_form_id">expositors-bible--j-rawson-lumby--lumby-expositorpeter--retained-en</idno><idno type="edition_id">expositors-bible--j-rawson-lumby--lumby-expositorpeter--ccel-electronic</idno><idno type="acquisition_id">expositors-bible--j-rawson-lumby--lumby-expositorpeter--acquired</idno><idno type="source_sha256">a41460490dcf5aaf4b46b987dc82f097c557c5cbc8f9e9c9ff848c7563309abc</idno><idno type="source_bytes">678452</idno><idno type="representation_revision">lumby-expositorpeter-ccel-electronic-v1</idno><idno type="sha256">a41460490dcf5aaf4b46b987dc82f097c557c5cbc8f9e9c9ff848c7563309abc</idno><note type="source-location">raw/ccel/expositors-bible/lumby_expositorpeter.xml</note><note type="source-scope">Complete retained CCEL ThML XML file for The Expositor\'s Bible: The Epistles of St. Peter. This author-cohort catalog ID does not resolve independent work or print-edition identity; source accounting only.</note></bibl></sourceDesc></fileDesc><revisionDesc xmlns="http://www.tei-c.org/ns/1.0"><change xmlns="http://www.tei-c.org/ns/1.0" xml:id="lumby-expositorpeter-ccel-electronic-v1" when="2026-09-27">Accept the complete retained CCEL electronic edition as readable TEI with title, preface or epigraph, commentary, and indexes.</change></revisionDesc></teiHeader><text xml:lang="en"><front xml:id="lumby-expositorpeter-front">\n'),
    (666679, b'<div xml:id="lumby-expositorpeter-feature-002045" type="source-index">\n', b'<quote xml:id="lumby-expositorpeter-feature-002045" type="source-div">\n'),
    (670996, b'</div>\n', b'</quote>\n'),
    (671272, b'<div xml:id="lumby-expositorpeter-feature-002084" type="source-index">\n', b'<quote xml:id="lumby-expositorpeter-feature-002084" type="source-div">\n'),
    (672105, b'</div>\n', b'</quote>\n'),
    (672403, b'<div xml:id="lumby-expositorpeter-feature-002097" type="source-index">\n', b'<quote xml:id="lumby-expositorpeter-feature-002097" type="source-div">\n'),
    (673088, b'</div>\n', b'</quote>\n'),
    (673398, b'<div xml:id="lumby-expositorpeter-feature-002108" type="source-index">\n', b'<quote xml:id="lumby-expositorpeter-feature-002108" type="source-div">\n'),
    (708085, b'</div>\n', b'</quote>\n'),
)


def test_source_oracle_and_two_node_delta() -> None:
    result = check(MEMBER, CANDIDATE, formal=True)
    assert (result["source_elements"], result["source_comments"], result["native_rows"]) == (2428, 18, 5)
    old = _io_path(
        WORK / "integration/lumby-expositorpeter-readable-electronic-v1/inputs/package/content.tei.xml"
    ).read_bytes()
    new = (CANDIDATE / "content.tei.xml").read_bytes()
    delta = _source_only_delta(old, new)
    assert {item["tei_id"] for item in delta} == {
        "lumby-expositorpeter-feature-002045",
        "lumby-expositorpeter-feature-002084",
        "lumby-expositorpeter-feature-002097",
        "lumby-expositorpeter-feature-002108",
    }


def test_source_oracle_rejects_index_as_quote(tmp_path: Path) -> None:
    for name in ("content.tei.xml", "source-accountability.json"):
        shutil.copy2(CANDIDATE / name, tmp_path / name)
    path = tmp_path / "content.tei.xml"
    tree = etree.parse(str(path))
    index = tree.find(f".//{NS}div[@type='source-index']")
    assert index is not None
    index.tag = NS + "quote"
    index.set("type", "source-div")
    tree.write(str(path), encoding="UTF-8", xml_declaration=True)
    with pytest.raises(ValueError, match="TEI tag differs"):
        check(MEMBER, tmp_path, formal=True)


def test_staged_accepted_text_changes_only_at_indexes() -> None:
    relative = next(path for path in _files(WORK) if path.endswith("/master.tei.xml"))
    new_master = STAGE / WORK / relative
    new_bytes = _io_path(new_master).read_bytes()
    assert sha256(new_bytes).hexdigest() == STAGED_MASTER_SHA
    old_bytes = new_bytes
    for offset, staged_fragment, original_fragment in reversed(ORIGINAL_MASTER_INVERSE):
        assert old_bytes[offset:offset + len(staged_fragment)] == staged_fragment
        old_bytes = old_bytes[:offset] + original_fragment + old_bytes[offset + len(staged_fragment):]
    assert sha256(old_bytes).hexdigest() == OLD_MASTER_SHA
    delta = _source_only_delta(old_bytes, new_bytes)
    assert len(delta) == 4
