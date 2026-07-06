from __future__ import annotations

import json
from pathlib import Path

import pytest
from lxml import etree

from build.tei import validate as tei_validate
from build.tei.writer import TEI_NS

XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
TEI = f"{{{TEI_NS}}}"
NS = {"tei": TEI_NS}

CCEL_CENSUS = Path("ir/census/city-of-god.ccel-npnf102.census.json")
CCEL_TEI = Path("ir/augustine/city-of-god.ccel-npnf102.tei.xml")
SE_CENSUS = Path("ir/census/city-of-god.standard-ebooks.census.json")
SE_TEI = Path("ir/augustine/city-of-god.standard-ebooks.tei.xml")
SE_ENDNOTES = Path(
    "raw/standard_ebooks/"
    "augustine-of-hippo_the-city-of-god_marcus-dods_george-wilson_j-j-smith/"
    "src/epub/text/endnotes.xhtml"
)
BCP_CENSUS_FILES = [
    Path("ir/census/book-of-common-prayer.bcp-1549.census.json"),
    Path("ir/census/book-of-common-prayer.bcp-1559.census.json"),
    Path("ir/census/book-of-common-prayer.bcp-1662.census.json"),
    Path("ir/census/book-of-common-prayer.bcp-1928-collects.census.json"),
]
BCP_TEI_FILES = [
    Path("ir/bcp/book-of-common-prayer.bcp-1549.tei.xml"),
    Path("ir/bcp/book-of-common-prayer.bcp-1559.tei.xml"),
    Path("ir/bcp/book-of-common-prayer.bcp-1662.tei.xml"),
    Path("ir/bcp/book-of-common-prayer.bcp-1928-collects.tei.xml"),
]
BATCH06_CCEL_FILES = [
    (
        Path("ir/census/athanasius-on-the-incarnation.ccel-npnf204.census.json"),
        Path("ir/ccel/athanasius-on-the-incarnation.ccel-npnf204.tei.xml"),
    ),
    (
        Path("ir/census/owen-mortification.ccel-owen-mort.census.json"),
        Path("ir/ccel/owen-mortification.ccel-owen-mort.tei.xml"),
    ),
]


@pytest.fixture(scope="session")
def tei_schema() -> etree.XMLSchema:
    return tei_validate.compiled_schema()


def _read_json_or_skip(path: Path) -> dict:
    if not path.exists():
        pytest.skip(f"{path.as_posix()} is absent; regenerate the committed census artifact first.")
    return json.loads(path.read_text(encoding="utf-8"))


def _read_json_required(path: Path) -> dict:
    assert path.exists(), f"{path.as_posix()} is absent; regenerate the batch 06 census artifact."
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_tei_text_or_skip(path: Path) -> etree._Element:
    if not path.exists():
        pytest.skip(f"{path.as_posix()} is absent; regenerate the committed TEI IR first.")
    tree = etree.parse(str(path))
    text = tree.xpath("/tei:TEI/tei:text", namespaces=NS)
    assert text, f"{path.as_posix()} has no TEI <text> element"
    return text[0]


def _parse_tei_text_required(path: Path) -> etree._Element:
    assert path.exists(), f"{path.as_posix()} is absent; regenerate the batch 06 TEI IR."
    tree = etree.parse(str(path))
    text = tree.xpath("/tei:TEI/tei:text", namespaces=NS)
    assert text, f"{path.as_posix()} has no TEI <text> element"
    return text[0]


def _validate_tei_file(path: Path, schema: etree.XMLSchema) -> list[str]:
    document = etree.parse(str(path))
    if schema.validate(document):
        return []
    return [str(error) for error in schema.error_log]


def _xml_ids(elements: list[etree._Element]) -> set[str]:
    return {element.get(XML_ID) for element in elements if element.get(XML_ID)}


def _corresp_ids(values: list[str]) -> set[str]:
    return {value.removeprefix("#") for value in values if value}


def _feature_ids(census: dict, feature: str) -> set[str]:
    ids = census["features"][feature].get("ids", [])
    return set(ids)


def _feature_count(census: dict, feature: str) -> int:
    return int(census["features"][feature]["count"])


def _assert_subset(feature: str, expected_ids: set[str], actual_ids: set[str]) -> None:
    missing = sorted(expected_ids - actual_ids)
    assert not missing, (
        f"{feature} missing {len(missing)} censused ids; first 10: {missing[:10]}"
    )


def _assert_count(feature: str, expected: int, actual: int) -> None:
    assert actual == expected, f"{feature} count mismatch: expected {expected}, got {actual}"


def _assert_no_unknown_features(census: dict, known_features: set[str]) -> None:
    unknown = set(census["features"]) - known_features
    assert not unknown, f"Unrecognized census feature(s) with no gate check: {sorted(unknown)}"


def _foreign_or_lang_bearing_ids(text: etree._Element) -> set[str]:
    ids: set[str] = set()
    for element in text.iter():
        if element.get(XML_ID) and (element.tag == f"{TEI}foreign" or element.get(XML_LANG)):
            ids.add(element.get(XML_ID))
    return ids


def _assert_ccel_work_census_survives(census: dict, text: etree._Element) -> None:
    known_features = {
        "divisions",
        "paragraphs",
        "notes",
        "page_breaks",
        "scripture_refs",
        "italics",
        "lang_spans",
        "display_spans",
        "arguments",
        "headings",
        "names",
        "citations",
        "tables",
        "table_rows",
        "table_cells",
    }

    _assert_no_unknown_features(census, known_features)
    carriers = {
        "divisions": _xml_ids(text.xpath(".//tei:div", namespaces=NS)),
        "paragraphs": _xml_ids(text.xpath(".//tei:p", namespaces=NS)),
        "notes": _xml_ids(text.xpath(".//tei:note", namespaces=NS)),
        "page_breaks": _xml_ids(text.xpath(".//tei:pb", namespaces=NS)),
        "scripture_refs": _xml_ids(text.xpath(".//tei:ref[@type='scripture']", namespaces=NS)),
        "lang_spans": _foreign_or_lang_bearing_ids(text),
        "display_spans": _xml_ids(text.xpath(".//tei:seg", namespaces=NS)),
        "arguments": _xml_ids(text.xpath(".//tei:argument", namespaces=NS)),
        "headings": _xml_ids(text.xpath(".//tei:head", namespaces=NS)),
        "names": _xml_ids(text.xpath(".//tei:name", namespaces=NS)),
        "citations": _xml_ids(text.xpath(".//tei:title", namespaces=NS)),
        "tables": _xml_ids(text.xpath(".//tei:table", namespaces=NS)),
        "table_rows": _xml_ids(text.xpath(".//tei:row", namespaces=NS)),
        "table_cells": _xml_ids(text.xpath(".//tei:cell", namespaces=NS)),
    }
    for feature in census["features"]:
        if feature == "italics":
            _assert_count(feature, _feature_count(census, feature), len(text.xpath(".//tei:hi[@rend='italic']", namespaces=NS)))
        else:
            _assert_subset(feature, _feature_ids(census, feature), carriers[feature])


def _raw_endnote_body_emphasis_count(path: Path) -> int:
    if not path.exists():
        pytest.skip(f"{path.as_posix()} is absent; cannot recompute endnote-body emphasis.")
    tree = etree.parse(str(path))
    return int(
        tree.xpath(
            "count(//xhtml:section[@id='endnotes']//xhtml:li//xhtml:em)",
            namespaces={"xhtml": "http://www.w3.org/1999/xhtml"},
        )
    )


@pytest.mark.slow
def test_gate_detects_missing_note() -> None:
    census = {"features": {"notes": {"count": 2, "ids": ["note-1", "note-2"]}}}
    tei = etree.fromstring(
        f"""
        <TEI xmlns="{TEI_NS}">
          <text>
            <body>
              <note xml:id="note-1"/>
            </body>
          </text>
        </TEI>
        """.encode()
    )
    text = tei.xpath("/tei:TEI/tei:text", namespaces=NS)[0]

    with pytest.raises(AssertionError, match="note-2"):
        _assert_subset("notes", _feature_ids(census, "notes"), _xml_ids(text.xpath(".//tei:note", namespaces=NS)))


@pytest.mark.slow
def test_ccel_census_id_sets_survive_in_tei_text() -> None:
    census = _read_json_or_skip(CCEL_CENSUS)
    text = _parse_tei_text_or_skip(CCEL_TEI)
    known_features = {
        "divisions_level2",
        "divisions_level3",
        "paragraphs",
        "notes",
        "page_breaks",
        "scripture_refs",
        "italics",
        "lang_spans",
    }

    _assert_no_unknown_features(census, known_features)
    carriers = {
        "divisions_level2": _xml_ids(text.xpath(".//tei:div", namespaces=NS)),
        "divisions_level3": _xml_ids(text.xpath(".//tei:div", namespaces=NS)),
        "paragraphs": _xml_ids(text.xpath(".//tei:p", namespaces=NS)),
        "notes": _xml_ids(text.xpath(".//tei:note", namespaces=NS)),
        "page_breaks": _xml_ids(text.xpath(".//tei:pb", namespaces=NS)),
        "scripture_refs": _xml_ids(text.xpath(".//tei:ref[@type='scripture']", namespaces=NS)),
        "lang_spans": _foreign_or_lang_bearing_ids(text),
    }
    for feature in census["features"]:
        if feature == "italics":
            _assert_count(feature, _feature_count(census, feature), len(text.xpath(".//tei:hi[@rend='italic']", namespaces=NS)))
        else:
            _assert_subset(feature, _feature_ids(census, feature), carriers[feature])


@pytest.mark.slow
def test_standard_ebooks_census_id_sets_survive_in_tei_text() -> None:
    census = _read_json_or_skip(SE_CENSUS)
    text = _parse_tei_text_or_skip(SE_TEI)
    known_features = {
        "sections",
        "noterefs",
        "endnotes",
        "bridgeheads",
        "emphasis",
        "verse_blocks",
    }

    _assert_no_unknown_features(census, known_features)
    for feature in census["features"]:
        if feature == "sections":
            _assert_subset(feature, _feature_ids(census, feature), _xml_ids(text.xpath(".//tei:div", namespaces=NS)))
        elif feature == "endnotes":
            _assert_subset(feature, _feature_ids(census, feature), _xml_ids(text.xpath(".//tei:note", namespaces=NS)))
        elif feature == "noterefs":
            _assert_subset(feature, _feature_ids(census, feature), _corresp_ids(text.xpath(".//tei:note/@corresp", namespaces=NS)))
        elif feature == "bridgeheads":
            _assert_count(feature, _feature_count(census, feature), len(text.xpath(".//tei:argument", namespaces=NS)))
        elif feature == "verse_blocks":
            _assert_count(feature, _feature_count(census, feature), len(text.xpath(".//tei:quote/tei:lg", namespaces=NS)))
        elif feature == "emphasis":
            endnote_emphasis = _raw_endnote_body_emphasis_count(SE_ENDNOTES)
            expected = _feature_count(census, feature) + endnote_emphasis
            _assert_count(feature, expected, len(text.xpath(".//tei:emph", namespaces=NS)))
        else:
            raise AssertionError(f"Unrecognized census feature with no gate check: {feature}")


@pytest.mark.slow
@pytest.mark.parametrize(("census_path", "tei_path"), list(zip(BCP_CENSUS_FILES, BCP_TEI_FILES, strict=True)))
def test_bcp_census_id_sets_survive_in_tei_text(census_path: Path, tei_path: Path) -> None:
    census = _read_json_or_skip(census_path)
    text = _parse_tei_text_or_skip(tei_path)
    known_features = {"services", "collects", "speaker_units", "rubrics", "labels"}

    _assert_no_unknown_features(census, known_features)
    for feature in census["features"]:
        if feature == "services":
            _assert_subset(feature, _feature_ids(census, feature), _xml_ids(text.xpath(".//tei:div[@type='service']", namespaces=NS)))
        elif feature == "collects":
            _assert_subset(feature, _feature_ids(census, feature), _xml_ids(text.xpath(".//tei:div[@type='collect']", namespaces=NS)))
        elif feature == "speaker_units":
            _assert_subset(feature, _feature_ids(census, feature), _xml_ids(text.xpath(".//tei:sp", namespaces=NS)))
        elif feature == "rubrics":
            _assert_subset(feature, _feature_ids(census, feature), _xml_ids(text.xpath(".//tei:p[@rend='rubric']", namespaces=NS)))
        elif feature == "labels":
            _assert_subset(feature, _feature_ids(census, feature), _xml_ids(text.xpath(".//tei:label", namespaces=NS)))
        else:
            raise AssertionError(f"Unrecognized census feature with no gate check: {feature}")


@pytest.mark.slow
@pytest.mark.parametrize(("census_path", "tei_path"), BATCH06_CCEL_FILES)
def test_batch06_ccel_work_census_id_sets_survive_in_tei_text(census_path: Path, tei_path: Path) -> None:
    census = _read_json_required(census_path)
    text = _parse_tei_text_required(tei_path)

    _assert_ccel_work_census_survives(census, text)


@pytest.mark.slow
def test_batch06_ccel_work_gate_detects_deliberate_note_loss(tmp_path: Path) -> None:
    census_path, tei_path = BATCH06_CCEL_FILES[0]
    census = _read_json_required(census_path)
    assert tei_path.exists(), f"{tei_path.as_posix()} is absent; regenerate the batch 06 TEI IR."
    corrupted = tmp_path / tei_path.name
    corrupted.write_text(tei_path.read_text(encoding="utf-8"), encoding="utf-8")
    tree = etree.parse(str(corrupted))
    note = tree.xpath("//tei:note[@xml:id=$note_id]", namespaces=NS, note_id=next(iter(_feature_ids(census, "notes"))))[0]
    note.getparent().remove(note)
    tree.write(str(corrupted), encoding="UTF-8", xml_declaration=True)
    text = _parse_tei_text_required(corrupted)

    with pytest.raises(AssertionError, match="missing 1 censused ids"):
        _assert_ccel_work_census_survives(census, text)


@pytest.mark.slow
def test_city_of_god_tei_structure_regression_guards() -> None:
    se_text = _parse_tei_text_or_skip(SE_TEI)
    ccel_text = _parse_tei_text_or_skip(CCEL_TEI)

    book_1_children = se_text.xpath("./tei:body/tei:div[@xml:id='book-1']/tei:div", namespaces=NS)
    prefaces = [child for child in book_1_children if child.get("type") == "preface"]
    chapters = [child for child in book_1_children if child.get("type") == "chapter"]
    assert len(prefaces) == 1
    assert len(chapters) == 36

    books = ccel_text.xpath("./tei:body/tei:div[@type='book']", namespaces=NS)
    assert len(books) == 22
    for book in books:
        chapters = book.xpath("./tei:div[@type='chapter']", namespaces=NS)
        assert len(chapters) >= 13, (
            f"CCEL book {book.get(XML_ID)} has {len(chapters)} chapter divs; expected at least 13"
        )


@pytest.mark.slow
def test_city_of_god_tei_irs_validate_against_vendored_schema(tei_schema: etree.XMLSchema) -> None:
    missing = [path.as_posix() for path in (CCEL_TEI, SE_TEI) if not path.exists()]
    if missing:
        pytest.skip(f"Committed TEI IR file(s) absent: {missing}")

    assert _validate_tei_file(CCEL_TEI, tei_schema) == []
    assert _validate_tei_file(SE_TEI, tei_schema) == []


@pytest.mark.slow
def test_bcp_tei_irs_validate_against_vendored_schema(tei_schema: etree.XMLSchema) -> None:
    missing = [path.as_posix() for path in BCP_TEI_FILES if not path.exists()]
    if missing:
        pytest.skip(f"Committed BCP TEI IR file(s) absent: {missing}")

    for tei_path in BCP_TEI_FILES:
        assert _validate_tei_file(tei_path, tei_schema) == []


@pytest.mark.slow
def test_batch06_ccel_tei_irs_validate_against_vendored_schema(tei_schema: etree.XMLSchema) -> None:
    for _, tei_path in BATCH06_CCEL_FILES:
        assert tei_path.exists(), f"{tei_path.as_posix()} is absent; regenerate the batch 06 TEI IR."
        assert _validate_tei_file(tei_path, tei_schema) == []
