"""Exact source and accepted-master semantics for Horton's index repair."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import shutil

from lxml import etree
import pytest

from build.tei.expositors_bible_lib035_readable_horton_index_v2_oracle import check
from build.tools.stage_expositors_lib035_horton_index_repair import OLD_MASTER_SHA, _source_only_delta
from ocd_kernel.tei.install_accepted import _files, _io_path


MEMBER = "horton-expositorprov"
CANDIDATE = Path(
    "D:/Library/Open Christian Data/candidate-reviews/"
    "expositors-lib035-horton-index-v2-candidate-20260928-v2/horton-expositorprov"
)
STAGE = Path(
    "D:/Library/Open Christian Data/candidate-reviews/"
    "expositors-lib035-horton-index-repair-stage-20260928-v1"
)
WORK = Path("library/works/expositors-bible--robert-f-horton")
NS = "{http://www.tei-c.org/ns/1.0}"

# Exact receipt-bound inverse; the retained accepted payload stays local.
STAGED_MASTER_SHA = 'f599e88d4d3e963df76dd3512f01ebbd348e3ed09db0cd62710597880378d9e5'
ORIGINAL_MASTER_INVERSE = (
    (39, b'<TEI xmlns="http://www.tei-c.org/ns/1.0" xml:id="horton-expositorprov"><teiHeader><fileDesc><titleStmt><title>The Expositor\'s Bible: The Book of Proverbs</title></titleStmt><publicationStmt><p>Christian Classics Ethereal Library electronic witness; rights and publication require separate review.</p></publicationStmt><sourceDesc><bibl><title>Retained CCEL ThML electronic witness by R. F. Horton; SHA-256 a7372596c60d053b539e957c01d29a54269da5c25b094cd7b373cb7e834e122d</title></bibl><bibl xmlns="http://www.tei-c.org/ns/1.0"><ptr target="https://www.ccel.org/ccel/horton/expositorprov.html"/><idno type="acquisition_id">expositors-bible--robert-f-horton--horton-expositorprov--acquired</idno><idno type="edition_id">expositors-bible--robert-f-horton--horton-expositorprov--ccel-electronic</idno><idno type="textual_form_id">expositors-bible--robert-f-horton--horton-expositorprov--retained-en</idno><idno type="work_id">expositors-bible--robert-f-horton</idno><idno type="source_sha256">a7372596c60d053b539e957c01d29a54269da5c25b094cd7b373cb7e834e122d</idno><idno type="source_bytes">1144079</idno><idno type="representation_revision">horton-expositorprov-ccel-electronic-index-v2</idno><idno type="sha256">a7372596c60d053b539e957c01d29a54269da5c25b094cd7b373cb7e834e122d</idno><note type="source-location">raw/ccel/expositors-bible/horton_expositorprov.xml</note><note type="source-scope">Complete retained CCEL ThML XML file for The Expositor\'s Bible: The Book of Proverbs. This author-cohort catalog ID does not resolve independent work or print-edition identity; source accounting only.</note></bibl></sourceDesc></fileDesc><revisionDesc xmlns="http://www.tei-c.org/ns/1.0"><change xmlns="http://www.tei-c.org/ns/1.0" xml:id="horton-expositorprov-ccel-electronic-index-v2" when="2026-09-27">Correct two source Index containers from quotation to index divisions; retain the complete electronic text and edition identity.</change></revisionDesc></teiHeader><text xml:lang="en"><front xml:id="horton-expositorprov-front">\n', b'<TEI xmlns="http://www.tei-c.org/ns/1.0" xml:id="horton-expositorprov"><teiHeader><fileDesc><titleStmt><title>The Expositor\'s Bible: The Book of Proverbs</title></titleStmt><publicationStmt><p>Christian Classics Ethereal Library electronic witness; rights and publication require separate review.</p></publicationStmt><sourceDesc><bibl><title>Retained CCEL ThML electronic witness by R. F. Horton; SHA-256 a7372596c60d053b539e957c01d29a54269da5c25b094cd7b373cb7e834e122d</title></bibl><bibl xmlns="http://www.tei-c.org/ns/1.0"><ptr target="https://www.ccel.org/ccel/horton/expositorprov.html"/><idno type="work_id">expositors-bible--robert-f-horton</idno><idno type="textual_form_id">expositors-bible--robert-f-horton--horton-expositorprov--retained-en</idno><idno type="edition_id">expositors-bible--robert-f-horton--horton-expositorprov--ccel-electronic</idno><idno type="acquisition_id">expositors-bible--robert-f-horton--horton-expositorprov--acquired</idno><idno type="source_sha256">a7372596c60d053b539e957c01d29a54269da5c25b094cd7b373cb7e834e122d</idno><idno type="source_bytes">1144079</idno><idno type="representation_revision">horton-expositorprov-ccel-electronic-v1</idno><idno type="sha256">a7372596c60d053b539e957c01d29a54269da5c25b094cd7b373cb7e834e122d</idno><note type="source-location">raw/ccel/expositors-bible/horton_expositorprov.xml</note><note type="source-scope">Complete retained CCEL ThML XML file for The Expositor\'s Bible: The Book of Proverbs. This author-cohort catalog ID does not resolve independent work or print-edition identity; source accounting only.</note></bibl></sourceDesc></fileDesc><revisionDesc xmlns="http://www.tei-c.org/ns/1.0"><change xmlns="http://www.tei-c.org/ns/1.0" xml:id="horton-expositorprov-ccel-electronic-v1" when="2026-09-27">Accept the complete retained CCEL electronic edition as readable TEI with title, introduction, chapters, indexes, table, and referenced image.</change></revisionDesc></teiHeader><text xml:lang="en"><front xml:id="horton-expositorprov-front">\n'),
    (1209917, b'<div xml:id="horton-expositorprov-feature-007861" type="source-index">\n', b'<quote xml:id="horton-expositorprov-feature-007861" type="source-div">\n'),
    (1213867, b'</div>\n', b'</quote>\n'),
    (1214189, b'<div xml:id="horton-expositorprov-feature-007898" type="source-index">\n', b'<quote xml:id="horton-expositorprov-feature-007898" type="source-div">\n'),
    (1258884, b'</div>\n', b'</quote>\n'),
)


def test_source_oracle_and_two_node_delta() -> None:
    result = check(MEMBER, CANDIDATE, formal=True)
    assert (result["source_elements"], result["source_comments"], result["native_rows"]) == (8320, 10, 36)
    old = _io_path(
        WORK / "integration/horton-expositorprov-readable-electronic-v1/inputs/package/content.tei.xml"
    ).read_bytes()
    new = (CANDIDATE / "content.tei.xml").read_bytes()
    delta = _source_only_delta(old, new)
    assert {item["tei_id"] for item in delta} == {
        "horton-expositorprov-feature-007861",
        "horton-expositorprov-feature-007898",
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
    assert len(delta) == 2
