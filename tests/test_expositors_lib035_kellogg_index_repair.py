"""Exact source and accepted-master semantics for Kellogg's index repair."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import shutil

from lxml import etree
import pytest

from build.tei.expositors_bible_lib035_readable_kellogg_index_v2_oracle import check
from build.tools.stage_expositors_lib035_kellogg_index_repair import OLD_MASTER_SHA, _source_only_delta
from ocd_kernel.tei.install_accepted import _files, _io_path


MEMBER = "kellogg-expositor3"
CANDIDATE = Path(
    "D:/Library/Open Christian Data/candidate-reviews/"
    "expositors-lib035-kellogg-index-v2-candidate-20260928-v1/kellogg-expositor3"
)
STAGE = Path(
    "D:/Library/Open Christian Data/candidate-reviews/"
    "expositors-lib035-kellogg-index-repair-stage-20260928-v1"
)
WORK = Path("library/works/expositors-bible--samuel-h-kellogg")
NS = "{http://www.tei-c.org/ns/1.0}"

# Exact receipt-bound inverse; the retained accepted payload stays local.
STAGED_MASTER_SHA = '18bb9fb896076b597bfdef07768fa2609198bd4c4fab41c4d40d1b4e9b559997'
ORIGINAL_MASTER_INVERSE = (
    (39, b'<TEI xmlns="http://www.tei-c.org/ns/1.0" xml:id="kellogg-expositor3"><teiHeader><fileDesc><titleStmt><title>The Expositor\'s Bible: The Book of Leviticus</title></titleStmt><publicationStmt><p>Christian Classics Ethereal Library electronic witness; rights and publication require separate review.</p></publicationStmt><sourceDesc><bibl><title>Retained CCEL ThML electronic witness by S. H. Kellogg; SHA-256 bab7fb79a99d3e07a81ccd4bac77ad6d9274884378e179d71ce4db36ef315284</title></bibl><bibl xmlns="http://www.tei-c.org/ns/1.0"><ptr target="https://www.ccel.org/ccel/kellogg/expositor3.html"/><idno type="acquisition_id">expositors-bible--samuel-h-kellogg--kellogg-expositor3--acquired</idno><idno type="edition_id">expositors-bible--samuel-h-kellogg--kellogg-expositor3--ccel-electronic</idno><idno type="textual_form_id">expositors-bible--samuel-h-kellogg--kellogg-expositor3--retained-en</idno><idno type="work_id">expositors-bible--samuel-h-kellogg</idno><idno type="source_sha256">bab7fb79a99d3e07a81ccd4bac77ad6d9274884378e179d71ce4db36ef315284</idno><idno type="source_bytes">1241956</idno><idno type="representation_revision">kellogg-expositor3-ccel-electronic-index-v2</idno><idno type="sha256">bab7fb79a99d3e07a81ccd4bac77ad6d9274884378e179d71ce4db36ef315284</idno><note type="source-location">raw/ccel/expositors-bible/kellogg_expositor3.xml</note><note type="source-scope">Complete retained CCEL ThML XML file for The Expositor\'s Bible: The Book of Leviticus. This author-cohort catalog ID does not resolve independent work or print-edition identity; source accounting only.</note></bibl></sourceDesc></fileDesc><revisionDesc xmlns="http://www.tei-c.org/ns/1.0"><change xmlns="http://www.tei-c.org/ns/1.0" xml:id="kellogg-expositor3-ccel-electronic-index-v2" when="2026-09-27">Correct six source Index containers from quotation to index divisions; retain the complete electronic text and edition identity.</change></revisionDesc></teiHeader><text xml:lang="en"><front xml:id="kellogg-expositor3-front">\n', b'<TEI xmlns="http://www.tei-c.org/ns/1.0" xml:id="kellogg-expositor3"><teiHeader><fileDesc><titleStmt><title>The Expositor\'s Bible: The Book of Leviticus</title></titleStmt><publicationStmt><p>Christian Classics Ethereal Library electronic witness; rights and publication require separate review.</p></publicationStmt><sourceDesc><bibl><title>Retained CCEL ThML electronic witness by S. H. Kellogg; SHA-256 bab7fb79a99d3e07a81ccd4bac77ad6d9274884378e179d71ce4db36ef315284</title></bibl><bibl xmlns="http://www.tei-c.org/ns/1.0"><ptr target="https://www.ccel.org/ccel/kellogg/expositor3.html"/><idno type="work_id">expositors-bible--samuel-h-kellogg</idno><idno type="textual_form_id">expositors-bible--samuel-h-kellogg--kellogg-expositor3--retained-en</idno><idno type="edition_id">expositors-bible--samuel-h-kellogg--kellogg-expositor3--ccel-electronic</idno><idno type="acquisition_id">expositors-bible--samuel-h-kellogg--kellogg-expositor3--acquired</idno><idno type="source_sha256">bab7fb79a99d3e07a81ccd4bac77ad6d9274884378e179d71ce4db36ef315284</idno><idno type="source_bytes">1241956</idno><idno type="representation_revision">kellogg-expositor3-ccel-electronic-v1</idno><idno type="sha256">bab7fb79a99d3e07a81ccd4bac77ad6d9274884378e179d71ce4db36ef315284</idno><note type="source-location">raw/ccel/expositors-bible/kellogg_expositor3.xml</note><note type="source-scope">Complete retained CCEL ThML XML file for The Expositor\'s Bible: The Book of Leviticus. This author-cohort catalog ID does not resolve independent work or print-edition identity; source accounting only.</note></bibl></sourceDesc></fileDesc><revisionDesc xmlns="http://www.tei-c.org/ns/1.0"><change xmlns="http://www.tei-c.org/ns/1.0" xml:id="kellogg-expositor3-ccel-electronic-v1" when="2026-09-27">Accept the complete retained CCEL electronic edition as readable TEI with title, three source parts, and indexes.</change></revisionDesc></teiHeader><text xml:lang="en"><front xml:id="kellogg-expositor3-front">\n'),
    (1148295, b'<div xml:id="kellogg-expositor3-feature-002825" type="source-index">\n', b'<quote xml:id="kellogg-expositor3-feature-002825" type="source-div">\n'),
    (1215613, b'</div>\n', b'</quote>\n'),
    (1215905, b'<div xml:id="kellogg-expositor3-feature-003405" type="source-index">\n', b'<quote xml:id="kellogg-expositor3-feature-003405" type="source-div">\n'),
    (1221330, b'</div>\n', b'</quote>\n'),
    (1221603, b'<div xml:id="kellogg-expositor3-feature-003453" type="source-index">\n', b'<quote xml:id="kellogg-expositor3-feature-003453" type="source-div">\n'),
    (1222623, b'</div>\n', b'</quote>\n'),
    (1222912, b'<div xml:id="kellogg-expositor3-feature-003468" type="source-index">\n', b'<quote xml:id="kellogg-expositor3-feature-003468" type="source-div">\n'),
    (1223648, b'</div>\n', b'</quote>\n'),
    (1223936, b'<div xml:id="kellogg-expositor3-feature-003480" type="source-index">\n', b'<quote xml:id="kellogg-expositor3-feature-003480" type="source-div">\n'),
    (1224840, b'</div>\n', b'</quote>\n'),
    (1225144, b'<div xml:id="kellogg-expositor3-feature-003494" type="source-index">\n', b'<quote xml:id="kellogg-expositor3-feature-003494" type="source-div">\n'),
    (1283308, b'</div>\n', b'</quote>\n'),
)


def test_source_oracle_and_two_node_delta() -> None:
    result = check(MEMBER, CANDIDATE, formal=True)
    assert (result["source_elements"], result["source_comments"], result["native_rows"]) == (4051, 26, 5)
    old = _io_path(
        WORK / "integration/kellogg-expositor3-readable-electronic-v1/inputs/package/content.tei.xml"
    ).read_bytes()
    new = (CANDIDATE / "content.tei.xml").read_bytes()
    delta = _source_only_delta(old, new)
    assert {item["tei_id"] for item in delta} == {
        "kellogg-expositor3-feature-002825",
        "kellogg-expositor3-feature-003405",
        "kellogg-expositor3-feature-003453",
        "kellogg-expositor3-feature-003468",
        "kellogg-expositor3-feature-003480",
        "kellogg-expositor3-feature-003494",
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
    assert len(delta) == 6
