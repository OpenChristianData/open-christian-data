"""PIPE-007A source-bound Bible verses and independent receipt checking."""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from lxml import etree as E
import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.envelope import canonical_row_bytes, row_text_hash
from ocd_kernel.projection.categories.bible import (
    project_accepted_bible,
    project_bible_document as project,
    verify_accepted_bible,
    verify_bible_document as verify,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "library-pipeline" / "categories" / "bible"
MANIFEST = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
CASES = MANIFEST["fixtures"]
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"


def _context(case: dict) -> dict:
    return copy.deepcopy(case["context"])


def _result(case: dict) -> dict:
    return project(FIXTURE / case["tei_file"], **_context(case))


def test_bible_reference_is_derived_from_bound_verse_components(monkeypatch):
    case = CASES[0]
    out = _result(case)
    locator = out['rows'][0]['locator']
    assert locator['reference_origin'] == 'tei-verse-components'
    assert locator['reference_status'] == 'normalized-verse-components'
    assert locator['reference']['normalized'] == 'Gen.1.1'
    from ocd_kernel.projection.categories import bible
    monkeypatch.setattr(bible, 'normalize_explicit_target', lambda *a, **k: pytest.fail('producer called'))
    path = FIXTURE / case['tei_file']
    assert verify(path, out['rows'], out['receipt'], **_context(case)) == []
    changed = copy.deepcopy(out['rows'])
    changed[0]['locator']['reference']['normalized'] = 'Gen.1.2'
    assert verify(path, changed, _forged_receipt_for_rows(out, changed), **_context(case))
    receipt = copy.deepcopy(out['receipt'])
    receipt['book_codes_sha256'] = '0'*64
    assert verify(path, out['rows'], receipt, **_context(case))


def _forged_receipt_for_rows(result: dict, rows: list[dict]) -> dict:
    """Make receipt internals agree with a forged row list."""

    receipt = copy.deepcopy(result["receipt"])
    receipt["row_count"] = len(rows)
    receipt["output_sha256"] = hashlib.sha256(canonical_row_bytes(rows)).hexdigest()
    # Keep the row-forged receipt otherwise valid.  The independent-check
    # status is tested separately and must remain the producer's pending value.
    receipt["independent_check"] = {"status": "pending", "errors": []}
    for anchor, row in zip(receipt.get("anchors", []), rows):
        anchor["record_id"] = row.get("record_id")
        anchor["text_sha256"] = row_text_hash(str(row.get("text", "")))
        if isinstance(row.get("locator"), dict):
            anchor["locator"] = copy.deepcopy(row["locator"])
            anchor["source_order"] = row["locator"].get("source_order")
    return receipt


def test_three_source_bound_editions_preserve_native_rows_and_accounting():
    assert MANIFEST["category"] == "bible"
    assert len(CASES) == 3
    assert len({case["context"]["identity"]["edition_id"] for case in CASES}) == 3
    assert sum(len(case["selected_units"]) for case in CASES) == MANIFEST["selected_unit_count"]

    outputs = []
    for case in CASES:
        # Retained files do not attest their acquisition timestamp.
        assert case["context"]["accessed_at"] is None
        for name, digest in MANIFEST["files"].items():
            assert hashlib.sha256((FIXTURE / name).read_bytes()).hexdigest() == digest

        source = json.loads((FIXTURE / case["source_file"]).read_text(encoding="utf-8"))
        result = _result(case)
        outputs.append(result)
        assert len(result["rows"]) == len(source["verses"]) == len(case["selected_units"])
        assert [row["text"] for row in result["rows"]] == [" ".join(item["text"].split()) for item in source["verses"]]
        assert [row["locator"]["verse"] for row in result["rows"]] == [
            item["label"] for item in source["verses"]
        ]
        assert [row["locator"]["source_order"] for row in result["rows"]] == [1, 2, 3]
        assert all(row["category"] == "bible" for row in result["rows"])
        assert all(row["versification"] == case["context"]["versification"] for row in result["rows"])
        assert all(row["locator"]["versification"] == case["context"]["versification"] for row in result["rows"])
        # The retained KJVA witness labels this carrier 3; the fixture must
        # preserve that native label rather than inventing a 3a split.
        assert result["rows"][2]["locator"].get("verse_label") is None

        receipt = result["receipt"]
        assert receipt["source_binding"] == {
            "source_url": case["context"]["source_url"],
            "retained_sha256": case["context"]["retained_sha256"],
            "source_sha256": case["context"]["source_sha256"],
        }
        assert receipt["master_sha256"] == case["tei_sha256"]
        assert receipt["row_count"] == 3
        assert receipt["unsupported"] == []
        assert receipt["independent_check"]["status"] == "pending"
        dispositions = {item["disposition"] for item in receipt["inventory"]}
        assert {"private-header", "structure", "row-content"} <= dispositions
        assert "excluded-paratext" not in dispositions
        assert sum(item["disposition"] == "row-content" for item in receipt["inventory"]) == 3
        assert receipt["exclusions"] == []
        assert verify(FIXTURE / case["tei_file"], result, **_context(case)) == []

    # The two Genesis editions share a source book and verse order while their
    # source wording remains distinct.
    assert outputs[0]["rows"][0]["text"] != outputs[1]["rows"][0]["text"]
    assert outputs[0]["rows"][1]["text"] != outputs[1]["rows"][1]["text"]
    assert outputs[0]["rows"][2]["text"] == outputs[1]["rows"][2]["text"]


@pytest.mark.requires_local_artifacts
def test_fixture_excerpts_are_dynamically_bound_to_retained_raw_witnesses():
    """The fixture JSON is an oracle excerpt, not the source authority."""

    for case in CASES:
        source = json.loads((FIXTURE / case["source_file"]).read_text(encoding="utf-8"))
        raw_path = ROOT / source["source_path"]
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        assert hashlib.sha256(raw_path.read_bytes()).hexdigest() == source["source_sha256"]
        envelope = source["raw_envelope"]
        assert envelope["translation"] == raw["translation"]
        assert envelope["book_count"] == len(raw["books"])
        assert envelope["chapter_count"] == sum(len(book["chapters"]) for book in raw["books"])
        assert envelope["verse_count"] == sum(len(chapter["verses"]) for book in raw["books"] for chapter in book["chapters"])
        assert envelope["book_census"] == [
            {"index": index, "name": book["name"], "chapter_count": len(book["chapters"]),
             "verse_count": sum(len(chapter["verses"]) for chapter in book["chapters"])}
            for index, book in enumerate(raw["books"], 1)
        ]
        assert source["raw_outside_scope_count"] + source["selected_chapter_native_unit_count"] == envelope["verse_count"]
        assert source["versification"] == "source-native:" + raw_path.name
        assert source["source_url"] == "ocd-source:" + source["source_path"]
        selector = source["source_selector"]
        book_index = selector["book_index"] - 1
        chapter_index = selector["chapter_index"] - 1
        book = raw["books"][book_index]
        chapter = book["chapters"][chapter_index]
        assert book["name"] == selector["book_name"]
        assert chapter["chapter"] == selector["chapter_number"]
        native = chapter["verses"]
        expected_native = []
        for index, verse in enumerate(native):
            label = str(verse["verse"])
            expected_native.append(
                {
                    "selector": f"books[{book_index}].chapters[{chapter_index}].verses[{index}]",
                    "label": label,
                    "selected": label in set(case["selected_units"]),
                    "text_sha256": hashlib.sha256(verse["text"].encode("utf-8")).hexdigest(),
                }
            )
        for item in expected_native:
            matching = next(native_item for native_item in source["native_units"] if native_item["selector"] == item["selector"])
            assert matching == {**item, **({"text": next(v["text"] for v in source["selected_units"] if v["label"] == item["label"])} if item["selected"] else {})}
        assert [item["label"] for item in source["outside_scope"]] == [
            item["label"] for item in expected_native if not item["selected"]
        ]
        assert source["outside_scope_count"] == len(source["outside_scope"]) == len(native) - len(source["selected_units"])
        selected = [verse for verse in native if str(verse["verse"]) in set(case["selected_units"])]
        assert [item["text"] for item in source["selected_units"]] == [verse["text"] for verse in selected]
        assert source["retained_source_sha256"] == source["source_sha256"] == case["context"]["retained_sha256"]
        tei = E.parse(str(FIXTURE / case["tei_file"]))
        assert tei.xpath("string(//t:sourceDesc//t:ptr/@target)", namespaces={"t": TEI_NS}) == source["source_url"]


def test_fixture_tei_validates_against_bundled_tei_p5_schema():
    schema = E.XMLSchema(E.parse(str(ROOT / "ocd_kernel" / "tei" / "vendor" / "xsd" / "tei_all.xsd")))
    for case in CASES:
        schema.assertValid(E.parse(str(FIXTURE / case["tei_file"])))


@pytest.mark.parametrize(
    "field",
    [
        "schema_version",
        "receipt_version",
        "mapping_version",
        "assembler_version",
        "category",
        "identity",
        "authority",
        "master_sha256",
        "scope_id",
        "source_binding",
        "output_sha256",
        "row_count",
        "anchors",
        "inventory",
        "references",
        "warnings",
        "exclusions",
        "unsupported",
        "schema_sha256",
        "common_schema_sha256",
        "policy_sha256",
        "independent_check",
    ],
)
def test_every_receipt_field_is_recomputed_from_source(field):
    case = CASES[0]
    result = _result(case)
    receipt = copy.deepcopy(result["receipt"])
    if field in {"schema_version", "receipt_version", "mapping_version", "assembler_version", "category", "master_sha256", "output_sha256", "schema_sha256", "common_schema_sha256", "policy_sha256"}:
        receipt[field] = "forged"
    elif field == "identity":
        receipt[field]["edition_id"] = "forged-edition"
    elif field == "authority":
        receipt[field] = {"master": {"sha256": "forged"}}
    elif field == "scope_id":
        receipt[field] = "Gen.1"
    elif field == "source_binding":
        receipt[field]["retained_sha256"] = "0" * 64
    elif field == "row_count":
        receipt[field] = 99
    elif field == "anchors":
        receipt[field][0]["source_order"] = 99
    elif field == "inventory":
        receipt[field].pop()
    elif field == "references":
        receipt[field] = [{"tei_path": "/forged", "original_target": "forged", "resolution": "external", "target_record_id": None, "target_note": None, "source_note": None}]
    elif field == "warnings":
        receipt[field] = [{"tei_path": "/forged", "reason": "forged"}]
    elif field == "exclusions":
        receipt[field] = [{"tei_path": "/forged", "reason": "invented exclusion"}]
    elif field == "unsupported":
        receipt[field] = [{"path": "/forged", "reason": "forged"}]
    elif field == "independent_check":
        receipt[field] = {"status": "passed", "errors": []}
    assert verify(FIXTURE / case["tei_file"], result["rows"], receipt, **_context(case))


def test_independent_check_status_cannot_be_spoofed():
    case = CASES[0]
    result = _result(case)
    receipt = copy.deepcopy(result["receipt"])
    receipt["independent_check"] = {"status": "passed", "errors": []}
    assert verify(FIXTURE / case["tei_file"], result["rows"], receipt, **_context(case))


@pytest.mark.parametrize(
    "mutation",
    [
        "omit",
        "duplicate",
        "reverse",
        "text",
        "record_id",
        "sequence",
        "category",
        "language",
        "representation_revision",
        "provenance",
        "locator_book",
        "locator_chapter",
        "locator_verse",
        "locator_versification",
        "versification",
        "notes",
        "references",
        "extra",
    ],
)
def test_source_rows_cannot_be_hidden_by_forged_internal_receipt(mutation):
    case = CASES[0]
    result = _result(case)
    rows = copy.deepcopy(result["rows"])
    if mutation == "omit":
        rows.pop()
    elif mutation == "duplicate":
        rows.append(copy.deepcopy(rows[-1]))
    elif mutation == "reverse":
        rows.reverse()
    elif mutation == "text":
        rows[0]["text"] += " Invented wording."
    elif mutation == "record_id":
        rows[0]["record_id"] = "forged-record"
    elif mutation == "sequence":
        rows[0]["sequence"] = 99
    elif mutation == "category":
        rows[0]["category"] = "prose"
    elif mutation == "language":
        rows[0]["language"] = "fr"
    elif mutation == "representation_revision":
        rows[0]["representation_revision"] = "forged-revision"
    elif mutation == "provenance":
        rows[0]["provenance"]["edition_title"] = "Invented edition"
    elif mutation == "locator_book":
        rows[0]["locator"]["book"] = "Invented"
    elif mutation == "locator_chapter":
        rows[0]["locator"]["chapter"] = 99
    elif mutation == "locator_verse":
        rows[0]["locator"]["verse"] = 99
    elif mutation == "locator_versification":
        rows[0]["locator"]["versification"] = "invented"
    elif mutation == "versification":
        rows[0]["versification"] = "invented"
    elif mutation == "notes":
        rows[0]["notes"] = [{"text": "forged", "place": "foot", "label": "x"}]
    elif mutation == "references":
        rows[0]["references"] = [{"label": "forged", "resolution": "external", "target_record_id": None, "target_note": None, "source_note": None}]
    elif mutation == "extra":
        rows[0]["forged"] = True
    receipt = _forged_receipt_for_rows(result, rows)
    assert any(error.startswith("row ") for error in verify(FIXTURE / case["tei_file"], rows, receipt, **_context(case)))


@pytest.mark.parametrize(
    "change",
    ["table", "attribute", "loose", "duplicate-id", "namespace", "doctype", "bad-versification", "missing-retained", "text-structure", "root-attribute", "root-acceptance-marker", "root-language", "comment"],
)
def test_unsupported_or_unbound_source_fails_both_routes(change, tmp_path):
    case = CASES[0]
    source_path = FIXTURE / case["tei_file"]
    tree = E.parse(str(source_path))
    ns = {"t": TEI_NS}
    book = tree.xpath("//t:body/t:div[@type='book']", namespaces=ns)[0]
    verse = tree.xpath("//t:ab[@type='verse']", namespaces=ns)[0]
    if change == "table":
        E.SubElement(book, f"{{{TEI_NS}}}table")
    elif change == "attribute":
        book.set("ana", "invented")
    elif change == "loose":
        book.text = "Unmapped words"
    elif change == "duplicate-id":
        verse.getparent().xpath("./t:ab", namespaces=ns)[1].set(f"{{{XML_NS}}}id", verse.get(f"{{{XML_NS}}}id"))
    elif change == "namespace":
        book.tag = "{urn:wrong}div"
    elif change == "doctype":
        raw = b'<!DOCTYPE TEI [<!ENTITY x "danger">]>' + E.tostring(tree, encoding="utf-8")
    elif change == "bad-versification":
        tree.xpath("//t:idno[@type='versification']", namespaces=ns)[0].text = "invented"
    elif change == "missing-retained":
        idno = tree.xpath("//t:idno[@type='sha256']", namespaces=ns)[0]
        idno.getparent().remove(idno)
    elif change == "text-structure":
        E.SubElement(tree.xpath("/t:TEI/t:text", namespaces=ns)[0], f"{{{TEI_NS}}}group")
    elif change == "root-attribute":
        tree.getroot().set("ana", "invented")
    elif change == "root-acceptance-marker":
        tree.getroot().set("ana", "#nonaccepted-candidate")
    elif change == "root-language":
        tree.getroot().set(f"{{{XML_NS}}}lang", "fr")
    elif change == "comment":
        raw = E.tostring(tree, encoding="utf-8").replace(b"<text", b"<!-- forged --><text", 1)
    if change not in {"doctype", "comment"}:
        raw = E.tostring(tree, encoding="utf-8")
    path = tmp_path / "bad-bible.tei.xml"
    path.write_bytes(raw)
    with pytest.raises(PipelineError):
        project(path, **_context(case))
    result = _result(case)
    assert verify(path, result["rows"], result["receipt"], **_context(case))


def test_matching_document_language_projects_and_verifies(tmp_path):
    case = CASES[0]
    tree = E.parse(str(FIXTURE / case["tei_file"]))
    tree.getroot().set(f"{{{XML_NS}}}lang", _context(case)["language"])
    path = tmp_path / "declared-language.tei.xml"
    path.write_bytes(E.tostring(tree, encoding="utf-8"))

    result = project(path, **_context(case))

    assert result["rows"] == _result(case)["rows"]
    assert verify(path, result["rows"], result["receipt"], **_context(case)) == []


def test_checker_has_no_producer_dependency(monkeypatch):
    case = CASES[0]
    result = _result(case)
    import ocd_kernel.projection.categories.bible as module

    monkeypatch.setattr(module, "project_bible_document", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("producer called")))
    assert verify(FIXTURE / case["tei_file"], result["rows"], result["receipt"], **_context(case)) == []


def test_two_document_tei_corpus_preserves_order_and_rejects_omission_or_reordering(tmp_path):
    first_case, second_case = CASES[:2]
    first = E.parse(str(FIXTURE / first_case["tei_file"])).getroot()
    second = E.parse(str(FIXTURE / second_case["tei_file"])).getroot()
    chapter = first.xpath(".//t:body/t:div[@type='book']/t:div[@type='chapter']", namespaces={"t": TEI_NS})[0]
    first_verse = chapter.xpath("./t:ab[@type='verse']", namespaces={"t": TEI_NS})[0]
    introduction = E.Element(f"{{{TEI_NS}}}ab", {"type": "introduction-paragraph", "n": "ip"})
    E.SubElement(introduction, f"{{{TEI_NS}}}note", {"type": "source-usfm-raw"}).text = r"\ip Set apart from DANIEL, as neither the Narration of \bk Bel and the Dragon. \bk*"
    introduction[0].tail = "Set apart from DANIEL, as neither the Narration of "
    E.SubElement(introduction, f"{{{TEI_NS}}}title", {"type": "book-name"}).text = "Bel and the Dragon."
    chapter.getparent().insert(chapter.getparent().index(chapter), introduction)
    preverse_heading = E.Element(f"{{{TEI_NS}}}ab", {"type": "paragraph-break", "n": "p"})
    E.SubElement(preverse_heading, f"{{{TEI_NS}}}note", {"type": "source-usfm-raw"}).text = r"\p A Prayer of Jesus the son of Sirach."
    preverse_heading[0].tail = "A Prayer of Jesus the son of Sirach."
    chapter.insert(chapter.index(first_verse), preverse_heading)
    E.SubElement(first_verse, f"{{{TEI_NS}}}seg", {"type": "usfm-qs"}).text = r' \+w Selah|strong="H5542"\+w*'
    paragraph_break = E.Element(f"{{{TEI_NS}}}ab", {"type": "paragraph-break", "n": "p"})
    paragraph_break.text = " Continuation before"
    source_marker = E.SubElement(paragraph_break, f"{{{TEI_NS}}}note", {"type": "source-usfm-raw"})
    source_marker.text = r"\p Continuation before a footnote"
    source_marker.tail = " and"
    footnote = E.SubElement(paragraph_break, f"{{{TEI_NS}}}note", {"type": "footnote"})
    footnote.text = "continuation note"
    footnote.tail = " continuation after"
    nested_break = E.SubElement(paragraph_break, f"{{{TEI_NS}}}ab", {"type": "paragraph-break", "n": "p"})
    nested_break.text = " nested continuation"
    E.SubElement(nested_break, f"{{{TEI_NS}}}note", {"type": "source-usfm-raw"}).text = r"\p nested continuation"
    E.SubElement(paragraph_break, f"{{{TEI_NS}}}seg", {"type": "usfm-qs"}).text = r' \+w Selah|strong="H5542"\+w*'
    no_break = E.Element(f"{{{TEI_NS}}}ab", {"type": "continuation-paragraph", "n": "nb"})
    no_break.text = " and no-break continuation"
    E.SubElement(no_break, f"{{{TEI_NS}}}note", {"type": "source-usfm-raw"}).text = r"\nb and no-break continuation"
    chapter.insert(chapter.index(first_verse) + 1, paragraph_break)
    chapter.insert(chapter.index(paragraph_break) + 1, no_break)
    omitted_verse = E.SubElement(chapter, f"{{{TEI_NS}}}ab", {"type": "verse", "n": "4"})
    E.SubElement(omitted_verse, f"{{{TEI_NS}}}note", {"type": "source-usfm-raw"}).text = r"\v 4 \f + \ft Verse 4 omitted \f*"
    E.SubElement(omitted_verse, f"{{{TEI_NS}}}note", {"type": "footnote"}).text = "Verse 4 is omitted by the source authorities."
    omitted_range = E.SubElement(chapter, f"{{{TEI_NS}}}ab", {"type": "verse", "n": "15-16"})
    E.SubElement(omitted_range, f"{{{TEI_NS}}}note", {"type": "source-usfm-raw"}).text = r"\v 15-16 \f + \ft Verses 15 and 16 are omitted by the best authorities. \f*"
    E.SubElement(omitted_range, f"{{{TEI_NS}}}note", {"type": "footnote"}).text = "Verses 15 and 16 are omitted by the best authorities."
    corpus = E.Element(f"{{{TEI_NS}}}teiCorpus", nsmap={None: TEI_NS})
    corpus.set(f"{{{XML_NS}}}id", "fixture-corpus")
    corpus.set(f"{{{XML_NS}}}lang", "en")
    corpus.append(copy.deepcopy(first[0]))
    for prefix, document in (("one", first), ("two", second)):
        for node in document.iter():
            current_id = node.get(f"{{{XML_NS}}}id")
            if current_id:
                node.set(f"{{{XML_NS}}}id", f"{prefix}-{current_id}")
        corpus.append(document)
    original_path = tmp_path / "corpus.tei.xml"
    original_path.write_bytes(E.tostring(corpus, encoding="utf-8", xml_declaration=True))

    context = _context(first_case)
    result = project(original_path, **context)
    assert result["receipt"]["mapping_version"] == "ocd-bible-corpus-mapping-provisional-v2"
    assert len(result["rows"]) == 8
    assert [row["locator"]["source_order"] for row in result["rows"]] == list(range(1, 9))
    assert [anchor["tei_path"].split("/TEI[")[1].split("]")[0] for anchor in result["receipt"]["anchors"]] == ["1"] * 5 + ["2"] * 3
    assert "Continuation before" in result["rows"][0]["text"]
    assert "continuation after" in result["rows"][0]["text"]
    assert result["rows"][0]["text"].count("nested continuation") == 1
    assert result["rows"][0]["text"].count("Selah") == 2
    assert "strong=" not in result["rows"][0]["text"]
    assert all("A Prayer of Jesus the son of Sirach." not in row["text"] for row in result["rows"])
    assert "no-break continuation" in result["rows"][0]["text"]
    assert result["rows"][0]["notes"][-1]["text"] == "continuation note"
    continuation_warnings = [warning for warning in result["receipt"]["warnings"] if warning["reason"] == "source-continuation-attached-to-preceding-verse"]
    assert len(continuation_warnings) == 2
    assert len([warning for warning in result["receipt"]["warnings"] if warning["reason"] == "source-usfm-word-annotation-rendered-to-surface"]) == 2
    assert len([warning for warning in result["receipt"]["warnings"] if warning["reason"] == "source-structural-text-not-projected-to-verse"]) == 2
    assert any(item["tei_path"] == continuation_warnings[0]["tei_path"] and item["disposition"] == "row-content" for item in result["receipt"]["inventory"])
    assert result["rows"][3]["text"] == ""
    assert result["rows"][3]["notes"] == [{"text": "Verse 4 is omitted by the source authorities.", "place": "unspecified", "label": ""}]
    assert result["rows"][4]["text"] == ""
    assert result["rows"][4]["locator"]["verse"] == "15-16"
    assert result["rows"][4]["locator"]["verse_label"] == "15-16"
    assert result["rows"][4]["notes"] == [{"text": "Verses 15 and 16 are omitted by the best authorities.", "place": "unspecified", "label": ""}]
    assert result["rows"][0]["locator"]["verse"] == "1"
    from ocd_kernel.release.features import configuration_features
    from ocd_kernel.release.typed_rows import check_rows, encode_rows
    assert encode_rows(result["rows"], configuration_features(result["rows"]))
    combined = [_result(CASES[0])["rows"][0], result["rows"][4]]
    combined_features = configuration_features(combined)
    check_rows(encode_rows(combined, combined_features), combined, combined_features)
    assert verify(original_path, result["rows"], result["receipt"], **context) == []

    private_namespace = f"source-native:retained-member-set:{context['source_sha256']}"
    aliased_root = E.fromstring(original_path.read_bytes())
    aliased_root.xpath("./t:teiHeader//t:idno[@type='versification']", namespaces={"t": TEI_NS})[0].text = private_namespace
    aliased_path = tmp_path / "digest-namespace-corpus.tei.xml"
    aliased_path.write_bytes(E.tostring(aliased_root, encoding="utf-8", xml_declaration=True))
    aliased_context = dict(context, versification=private_namespace)
    aliased = project(aliased_path, **aliased_context)
    public_namespace = f"source-native:retained-member-set:{context['identity']['edition_id']}:{context['representation_revision']}"
    assert {row["versification"] for row in aliased["rows"]} == {public_namespace}
    assert {row["locator"]["versification"] for row in aliased["rows"]} == {public_namespace}
    from ocd_kernel.release.public_allowlist import _scan
    assert all(not _scan(row, "public Bible row") for row in aliased["rows"])
    assert verify(aliased_path, aliased["rows"], aliased["receipt"], **aliased_context) == []

    reversed_root = E.fromstring(original_path.read_bytes())
    first_doc, second_doc = reversed_root[1], reversed_root[2]
    reversed_root.remove(first_doc)
    reversed_root.insert(2, first_doc)
    reversed_path = tmp_path / "reversed-corpus.tei.xml"
    reversed_path.write_bytes(E.tostring(reversed_root, encoding="utf-8", xml_declaration=True))
    assert verify(reversed_path, result["rows"], result["receipt"], **context)

    omitted_root = E.fromstring(original_path.read_bytes())
    omitted_root.remove(omitted_root[2])
    omitted_path = tmp_path / "omitted-corpus-member.tei.xml"
    omitted_path.write_bytes(E.tostring(omitted_root, encoding="utf-8", xml_declaration=True))
    assert verify(omitted_path, result["rows"], result["receipt"], **context)

    for index, (label_type, label) in enumerate((("paragraph-break", None), ("typo", None), ("typo", "not-a-verse"))):
        mislabeled_root = E.fromstring(original_path.read_bytes())
        first_verse = mislabeled_root.xpath("./t:TEI[1]//t:ab[@type='verse']", namespaces={"t": TEI_NS})[0]
        first_verse.set("type", label_type)
        if label is None:
            first_verse.attrib.pop("n")
        else:
            first_verse.set("n", label)
        mislabeled_path = tmp_path / f"mislabeled-corpus-verse-{index}.tei.xml"
        mislabeled_path.write_bytes(E.tostring(mislabeled_root, encoding="utf-8", xml_declaration=True))
        with pytest.raises(PipelineError, match="unclassified typed verse carrier"):
            project(mislabeled_path, **context)
        assert any("unclassified typed verse carrier" in error for error in verify(mislabeled_path, [], {}, **context))

    for index, ambiguous in enumerate((False, True)):
        malformed = E.fromstring(original_path.read_bytes())
        block = malformed.xpath("./t:TEI[1]//t:ab[@type='paragraph-break'][last()]", namespaces={"t": TEI_NS})[0]
        marker = block.xpath("./t:note[@type='source-usfm-raw']", namespaces={"t": TEI_NS})[0]
        marker.text = r"\p-unknown continuation" if not ambiguous else r"\p continuation"
        if ambiguous:
            E.SubElement(block, f"{{{TEI_NS}}}note", {"type": "source-usfm-raw"}).text = r"\q1 conflicting marker"
        malformed_path = tmp_path / f"malformed-continuation-marker-{index}.tei.xml"
        malformed_path.write_bytes(E.tostring(malformed, encoding="utf-8", xml_declaration=True))
        with pytest.raises(PipelineError, match="unclassified typed verse carrier"):
            project(malformed_path, **context)
        assert any("unclassified typed verse carrier" in error for error in verify(malformed_path, [], {}, **context))

    nested_verse = E.fromstring(original_path.read_bytes())
    block = nested_verse.xpath("./t:TEI[1]//t:ab[@type='paragraph-break'][last()]", namespaces={"t": TEI_NS})[0]
    E.SubElement(block, f"{{{TEI_NS}}}ab", {"type": "verse", "n": "99"}).text = "Nested numbered verse"
    nested_verse_path = tmp_path / "nested-verse-in-continuation.tei.xml"
    nested_verse_path.write_bytes(E.tostring(nested_verse, encoding="utf-8", xml_declaration=True))
    with pytest.raises(PipelineError, match="source continuation contains a verse"):
        project(nested_verse_path, **context)
    assert any("source continuation contains a verse" in error for error in verify(nested_verse_path, [], {}, **context))

    preverse_poetry = E.fromstring(original_path.read_bytes())
    heading = preverse_poetry.xpath("./t:TEI[1]//t:div[@type='chapter']/t:ab[@type='paragraph-break'][1]", namespaces={"t": TEI_NS})[0]
    heading.set("type", "poetry-line")
    heading.set("n", "q1")
    heading[0].text = r"\q1 A Prayer of Jesus the son of Sirach."
    preverse_poetry_path = tmp_path / "preverse-poetry.tei.xml"
    preverse_poetry_path.write_bytes(E.tostring(preverse_poetry, encoding="utf-8", xml_declaration=True))
    with pytest.raises(PipelineError, match="source continuation has no preceding verse"):
        project(preverse_poetry_path, **context)
    assert any("source continuation has no preceding verse" in error for error in verify(preverse_poetry_path, [], {}, **context))

    standalone_inline = E.fromstring(original_path.read_bytes())
    chapter = standalone_inline.xpath("./t:TEI[1]//t:div[@type='chapter']", namespaces={"t": TEI_NS})[0]
    E.SubElement(chapter, f"{{{TEI_NS}}}seg", {"type": "usfm-qs"}).text = "Unbound Selah"
    standalone_inline_path = tmp_path / "standalone-inline.tei.xml"
    standalone_inline_path.write_bytes(E.tostring(standalone_inline, encoding="utf-8", xml_declaration=True))
    with pytest.raises(PipelineError, match="unclassified typed verse carrier"):
        project(standalone_inline_path, **context)
    assert any("unclassified typed verse carrier" in error for error in verify(standalone_inline_path, [], {}, **context))

    malformed_introduction = E.fromstring(original_path.read_bytes())
    malformed_introduction.xpath("./t:TEI[1]//t:ab[@type='introduction-paragraph']/t:note", namespaces={"t": TEI_NS})[0].text = r"\ip-unknown text"
    malformed_introduction_path = tmp_path / "malformed-introduction.tei.xml"
    malformed_introduction_path.write_bytes(E.tostring(malformed_introduction, encoding="utf-8", xml_declaration=True))
    with pytest.raises(PipelineError, match="source introduction marker mismatch"):
        project(malformed_introduction_path, **context)
    assert any("source introduction marker mismatch" in error for error in verify(malformed_introduction_path, [], {}, **context))

    for index, xpath in enumerate(("./t:TEI[1]//t:ab[@type='verse'][1]/t:seg[@type='usfm-qs']",
                                   "./t:TEI[1]//t:ab[@type='paragraph-break']/t:seg[@type='usfm-qs']")):
        malformed_word = E.fromstring(original_path.read_bytes())
        malformed_word.xpath(xpath, namespaces={"t": TEI_NS})[0].text = r' \+w Selah|strong="H5542"'
        malformed_word_path = tmp_path / f"malformed-word-{index}.tei.xml"
        malformed_word_path.write_bytes(E.tostring(malformed_word, encoding="utf-8", xml_declaration=True))
        with pytest.raises(PipelineError, match="unsupported USFM word annotation"):
            project(malformed_word_path, **context)
        assert any("unsupported USFM word annotation" in error for error in verify(malformed_word_path, [], {}, **context))

    for mutation in ("corpus-text", "document-tail", "nested-document", "conflicting-language", "wrong-language"):
        malformed = E.fromstring(original_path.read_bytes())
        if mutation == "corpus-text":
            malformed.text = "unmapped text"
        elif mutation == "document-tail":
            malformed[1].tail = "unmapped text"
        elif mutation == "nested-document":
            malformed[1].find(".//{" + TEI_NS + "}body").append(copy.deepcopy(malformed[2]))
        elif mutation == "wrong-language":
            malformed.set(f"{{{XML_NS}}}lang", "fr")
            malformed[1].set(f"{{{XML_NS}}}lang", "fr")
            malformed[2].set(f"{{{XML_NS}}}lang", "fr")
        else:
            malformed[2].set(f"{{{XML_NS}}}lang", "fr")
        malformed_path = tmp_path / f"malformed-{mutation}.tei.xml"
        malformed_path.write_bytes(E.tostring(malformed, encoding="utf-8", xml_declaration=True))
        with pytest.raises(PipelineError):
            project(malformed_path, **context)
        assert verify(malformed_path, [], {}, **context)


def test_accepted_retained_member_set_corpus_binds_each_document_and_order():
    import xml.etree.ElementTree as ET
    from lxml import etree as lxml
    import ocd_kernel.projection.categories.bible as module

    namespace = f"{{{TEI_NS}}}"
    corpus = ET.Element(namespace + "teiCorpus")
    ET.SubElement(corpus, namespace + "teiHeader")
    paths = ["raw/usfm/01-GENeng-rv.usfm", "raw/usfm/02-EXOeng-rv.usfm"]
    members = []
    for position, path in enumerate(paths, 1):
        member = {"path": path, "position": position, "bytes": 10, "sha256": str(position) * 64}
        members.append(member)
        document = ET.SubElement(corpus, namespace + "TEI")
        ET.SubElement(document, namespace + "teiHeader")
        body = ET.SubElement(ET.SubElement(document, namespace + "text"), namespace + "body")
        ET.SubElement(body, namespace + "div", {
            "type": "book", "n": "GEN" if position == 1 else "EXO",
            "corresp": f"source-usfm:eng-rv/{path.rsplit('/', 1)[-1]}#line=1",
        })
    expected = [{"path": member["path"], "position": member["position"]} for member in members]
    metadata = {"acceptance": {
        "source": {"source_kind": "retained-member-set", "missing_members": [], "unknown_members": []},
        "scope": {"included_members": copy.deepcopy(members), "expected_members": copy.deepcopy(expected), "excluded_members": []},
    }}
    header = {"source_url": "https://example.test/find/show.php?id=eng-rv"}
    module._validate_accepted_member_set(corpus, header, metadata)
    checker_corpus = lxml.fromstring(ET.tostring(corpus, encoding="utf-8"))
    module._checker_validate_accepted_member_set(checker_corpus, header, metadata)

    for locator in (
        "source-usfm:eng-rv/02-EXOeng-rv.usfm#line=1",
        "source-usfm:other-edition/01-GENeng-rv.usfm#line=1",
        "source-usfm:eng-rv/01-GENeng-rv.usfm#garbage#line=1",
    ):
        mutated = copy.deepcopy(corpus)
        first_book = next(node for node in mutated[1].iter() if node.tag.endswith("}div"))
        first_book.set("corresp", locator)
        with pytest.raises(PipelineError, match="does not identify"):
            module._validate_accepted_member_set(mutated, header, metadata)
        checker_mutated = lxml.fromstring(ET.tostring(mutated, encoding="utf-8"))
        with pytest.raises(PipelineError, match="does not identify"):
            module._checker_validate_accepted_member_set(checker_mutated, header, metadata)


def test_retained_member_set_header_distinguishes_provider_page_from_package():
    import xml.etree.ElementTree as ET
    from lxml import etree as lxml
    import ocd_kernel.projection.categories.bible as module

    namespace = f"{{{TEI_NS}}}"
    corpus = ET.Element(namespace + "teiCorpus")
    header = ET.SubElement(corpus, namespace + "teiHeader")
    source_desc = ET.SubElement(ET.SubElement(ET.SubElement(header, namespace + "fileDesc"), namespace + "sourceDesc"), namespace + "listBibl")
    ET.SubElement(source_desc, namespace + "ref", target="https://example.test/source?id=eng-rv").text = "provider page"
    package = ET.SubElement(source_desc, namespace + "bibl", {"type": "ocd-acceptance-binding"})
    ET.SubElement(package, namespace + "ptr", target="https://example.test/package.zip")
    ET.SubElement(source_desc, namespace + "idno", {"type": "source_kind"}).text = "retained-member-set"
    ET.SubElement(source_desc, namespace + "idno", {"type": "sha256"}).text = "a" * 64

    parsed = module._header(corpus)
    assert parsed["source_url"] == "https://example.test/source?id=eng-rv"
    assert parsed["package_url"] == "https://example.test/package.zip"
    checker = lxml.fromstring(ET.tostring(corpus, encoding="utf-8"))
    checked = module._checker_header(checker, {})
    assert checked["source_url"] == parsed["source_url"]
    assert checked["package_url"] == parsed["package_url"]

    unscoped = copy.deepcopy(corpus)
    unscoped_desc = unscoped.find(".//" + namespace + "sourceDesc")
    ET.SubElement(ET.SubElement(unscoped_desc, namespace + "bibl"), namespace + "ptr", target="https://example.test/other.zip")
    with pytest.raises(PipelineError, match="provider ref and one bound package ptr"):
        module._header(unscoped)
    checker_unscoped = lxml.fromstring(ET.tostring(unscoped, encoding="utf-8"))
    with pytest.raises(PipelineError, match="provider ref and one bound package ptr"):
        module._checker_header(checker_unscoped, {})


def test_missing_receipt_and_accepted_wrapper_versification_override_are_closed():
    case = CASES[0]
    result = _result(case)
    assert verify(FIXTURE / case["tei_file"], result["rows"], None, **_context(case))
    assert "versification" not in inspect.signature(project_accepted_bible).parameters

@pytest.mark.parametrize('mutation,reason', [
    ('header-attribute', 'header element or attribute'),
    ('header-element', 'header element or attribute'),
    ('header-name-in-body', 'unsupported-visible: title'),
    ('attribute-namespace', 'attribute namespace'),
    ('conflicting-ref', 'conflicting reference targets'),
    ('whitespace-ptr', 'source ptr'),
])
def test_closed_headers_and_reference_targets_fail_before_receipt(mutation, reason, tmp_path):
    case = CASES[0]
    tree = E.parse(str(FIXTURE / case['tei_file']))
    ns = {'t': TEI_NS}
    title = tree.xpath('//t:teiHeader//t:title', namespaces=ns)[0]
    verse = tree.xpath('//t:ab[@type="verse"]', namespaces=ns)[0]
    if mutation == 'header-attribute':
        title.set('ana', 'forged')
    elif mutation == 'header-element':
        E.SubElement(tree.xpath('//t:teiHeader', namespaces=ns)[0], f'{{{TEI_NS}}}bogus')
    elif mutation == 'header-name-in-body':
        E.SubElement(verse, f'{{{TEI_NS}}}title').text = 'unmapped'
    elif mutation == 'attribute-namespace':
        verse.set('{urn:forged}type', 'verse')
    elif mutation == 'whitespace-ptr':
        tree.xpath('//t:sourceDesc/t:bibl/t:ptr', namespaces=ns)[0].set('target', '   ')
    else:
        E.SubElement(verse, f'{{{TEI_NS}}}ref', target='Bible:Gen.1.1', cRef='Bible:Gen.1.2').text = 'reference'
    path = tmp_path / 'closed-bible.xml'
    path.write_bytes(E.tostring(tree))
    with pytest.raises(PipelineError, match=reason):
        project(path, **_context(case))
    errors = verify(path, [], {}, **_context(case))
    assert any(reason in error for error in errors), errors

@pytest.mark.parametrize('kind,value', [('sha256', '0' * 64), ('retained_sha256', '1' * 64), ('work_id', 'forged'), ('bible_versification', 'forged')])
def test_duplicate_header_binding_rejected_before_context(kind, value, tmp_path):
    case = CASES[0]
    tree = E.parse(str(FIXTURE / case['tei_file']))
    bibl = tree.xpath('//t:sourceDesc/t:bibl', namespaces={'t': TEI_NS})[0]
    E.SubElement(bibl, f'{{{TEI_NS}}}idno', type=kind).text = value
    path = tmp_path / 'duplicate-binding.xml'
    path.write_bytes(E.tostring(tree))
    with pytest.raises(PipelineError, match='duplicate source binding'):
        project(path, **_context(case))
    errors = verify(path, [], {}, **_context(case))
    assert any('duplicate source binding' in error for error in errors), errors


@pytest.mark.parametrize('mutation,reason', [('sourceDesc', 'sourceDesc'), ('ptr', 'source ptr')])
def test_duplicate_source_container_or_pointer_rejected(mutation, reason, tmp_path):
    case = CASES[0]
    tree = E.parse(str(FIXTURE / case['tei_file']))
    ns = {'t': TEI_NS}
    if mutation == 'sourceDesc':
        header = tree.xpath('//t:teiHeader', namespaces=ns)[0]
        E.SubElement(header, f'{{{TEI_NS}}}sourceDesc')
    else:
        bibl = tree.xpath('//t:sourceDesc/t:bibl', namespaces=ns)[0]
        E.SubElement(bibl, f'{{{TEI_NS}}}ptr', target=_context(case)['source_url'])
    path = tmp_path / f'duplicate-{mutation}.xml'
    path.write_bytes(E.tostring(tree, encoding='utf-8'))
    with pytest.raises(PipelineError, match=reason):
        project(path, **_context(case))
    errors = verify(path, [], {}, **_context(case))
    assert any(reason in error for error in errors), errors


def test_checker_renders_inserted_note_and_following_tail_once(tmp_path):
    """A source mutation exercises note inclusion and adjacent tail ownership."""

    case = CASES[0]
    tree = E.parse(str(FIXTURE / case['tei_file']))
    verse = tree.xpath('//t:ab[@type="verse"]', namespaces={'t': TEI_NS})[0]
    note = E.Element(f'{{{TEI_NS}}}note', place='foot')
    note.text = 'source-derived note'
    note.tail = ' source-derived tail'
    verse.insert(0, note)
    path = tmp_path / 'note-tail.xml'
    path.write_bytes(E.tostring(tree, encoding='utf-8', xml_declaration=True))
    result = project(path, **_context(case))
    assert result['rows'][0]['notes'] == [{'text': 'source-derived note', 'place': 'foot', 'label': ''}]
    assert result['rows'][0]['text'].count('source-derived tail') == 1
    assert verify(path, result, **_context(case)) == []


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def _set_header_idno(parent, kind: str, value: str) -> None:
    nodes = [
        node for node in parent
        if E.QName(node).localname == 'idno' and node.get('type') == kind
    ]
    if nodes:
        nodes[0].text = str(value)
        for duplicate in nodes[1:]:
            parent.remove(duplicate)
    else:
        E.SubElement(parent, f'{{{TEI_NS}}}idno', type=kind).text = str(value)


def _set_header_note(parent, kind: str, value: str) -> None:
    nodes = [
        node for node in parent
        if E.QName(node).localname == 'note' and node.get('type') == kind
    ]
    if nodes:
        nodes[0].text = value
        for duplicate in nodes[1:]:
            parent.remove(duplicate)
    else:
        E.SubElement(parent, f'{{{TEI_NS}}}note', type=kind).text = value


def _accepted_bible_fixture(tmp_path_factory):
    """Build a temporary accepted handoff from the real KJV fixture and raw witness."""

    from ocd_kernel.tei.acceptance import build_acceptance_record, make_file_binding, write_acceptance

    case = next(item for item in CASES if item['fixture_id'] == 'kjv-genesis')
    source = json.loads((FIXTURE / case['source_file']).read_text(encoding='utf-8'))
    context = case['context']
    raw_path = ROOT / source['source_path']
    raw = raw_path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == source['source_sha256']
    source_scope = case['retained_source']['scope']
    identity = {**context['identity'], 'acquisition_id': 'fixture-bible-accepted'}
    base = tmp_path_factory.mktemp('bc')
    edition_root = base / 'library' / 'works' / identity['work_id'] / 'forms' / identity['textual_form_id'] / 'editions' / identity['edition_id']
    edition_root.mkdir(parents=True)
    work_path = base / 'library' / 'works' / identity['work_id'] / 'work.json'
    _write_json(work_path, {
        'schema_version': '2.0',
        'work_id': identity['work_id'],
        'title': context['edition_title'],
        'evidence': ['fixture acceptance simulation'],
        'textual_forms': [{
            'textual_form_id': identity['textual_form_id'],
            'editions': [{
                'edition_id': identity['edition_id'],
                'title': context['edition_title'],
                'language': 'en',
                'category': 'bible',
                'acquisition_ids': [identity['acquisition_id']],
            }],
        }],
    })
    _write_json(base / 'library' / 'works' / identity['work_id'] / 'state.json', {
        'schema_version': '2.0',
        'work_id': identity['work_id'],
        'targets': [{
            'target_id': identity['edition_id'],
            'target_type': 'edition',
            'stage': 'review',
            'updated_at': '2026-09-08T00:00:00Z',
            'evidence': ['candidate.tei.xml'],
        }],
    })
    retained = base / 'retained' / 'source.json'
    retained.parent.mkdir(parents=True, exist_ok=True)
    retained.write_bytes((FIXTURE / case['source_file']).read_bytes())
    retained_hash = hashlib.sha256(retained.read_bytes()).hexdigest()
    included = {
        'path': 'retained/source.json',
        'position': 1,
        'bytes': retained.stat().st_size,
        'sha256': retained_hash,
        'scope': source_scope,
    }
    acquisition_url = 'https://example.invalid/ocd-fixture/bible-kjv'
    acquisition = {
        'schema_version': '2.0',
        'acquisition_id': identity['acquisition_id'],
        'edition_id': identity['edition_id'],
        'provider': 'offline fixture source',
        'url': acquisition_url,
        'source_path': source['source_path'],
        'source_bytes': len(raw),
        'source_sha256': source['source_sha256'],
        'source_scope': source_scope,
        'retained_files': [{
            key: included[key] for key in ('path', 'bytes', 'sha256', 'scope')
        } | {'media_type': 'application/json'}],
        'route': 'born-digital',
    }
    acquisition_path = edition_root / 'acquisitions' / f"{identity['acquisition_id']}.json"
    _write_json(acquisition_path, acquisition)

    tree = E.parse(str(FIXTURE / case['tei_file']))
    ns = {'t': TEI_NS}
    header = tree.xpath('/t:TEI/t:teiHeader', namespaces=ns)[0]
    bibl = tree.xpath('//t:sourceDesc/t:bibl', namespaces=ns)[0]
    ptr = bibl.xpath('./t:ptr', namespaces=ns)[0]
    ptr.set('target', acquisition_url)
    _set_header_idno(bibl, 'sha256', retained_hash)
    _set_header_idno(bibl, 'source_sha256', source['source_sha256'])
    _set_header_idno(bibl, 'source_bytes', str(len(raw)))
    _set_header_idno(bibl, 'acquisition_id', identity['acquisition_id'])
    _set_header_note(bibl, 'source-location', source['source_path'])
    _set_header_note(bibl, 'source-scope', source_scope)
    revision = context['representation_revision']
    revision_desc = header.find(f'{{{TEI_NS}}}revisionDesc')
    if revision_desc is None:
        revision_desc = E.SubElement(header, f'{{{TEI_NS}}}revisionDesc')
    for change in list(revision_desc):
        revision_desc.remove(change)
    change = E.SubElement(revision_desc, f'{{{TEI_NS}}}change', when='2026-09-08')
    change.set(f'{{{XML_NS}}}id', revision)
    change.text = 'Bound category fixture.'
    candidate = base / 'candidate.tei.xml'
    candidate.write_bytes(E.tostring(tree, encoding='utf-8', xml_declaration=True))
    candidate_binding = make_file_binding(base, candidate)
    scope = {
        'kind': 'member',
        'declared': source_scope,
        'expected_members': [{'path': included['path'], 'position': 1}],
        'included_members': [included],
        'excluded_members': [],
    }
    source_obj = {
        'source_path': source['source_path'],
        'source_sha256': source['source_sha256'],
        'source_bytes': len(raw),
        'source_scope': source_scope,
    }
    accounting = {
        'contract': 'ocd-source-accounting-v1',
        'identity': identity,
        'source': source_obj,
        'source_sha256': source['source_sha256'],
        'source_bytes': len(raw),
        'scope': source_scope,
        'accepted_scope': {'kind': 'member', 'declared': source_scope},
        'expected_members': scope['expected_members'],
        'included_members': scope['included_members'],
        'excluded_members': [],
        'missing_members': [],
        'unknown_members': [],
    }
    source_accounting_path = base / 'evidence' / 'source-accounting.json'
    _write_json(source_accounting_path, accounting)
    technical = {
        'producer': {'id': 'producer:bible-fixture'},
        'checker': {'id': 'checker:bible-fixture'},
        'shared_assumptions': ['Synthetic acceptance evidence is fixture-only.'],
        'independent_corroboration': 'Source-derived Bible fixture checks remain separate.',
    }
    for name in ('validation', 'accounting', 'fidelity', 'reproducibility', 'schema', 'closure'):
        proof_path = base / 'evidence' / f'{name}.json'
        proof = {
            'contract': f'ocd-tei-{name}-v1',
            'identity': identity,
            'source': source_obj,
            'candidate': candidate_binding,
            'scope': source_scope,
            'status': 'pass',
            'command': 'simulated-accepted-category-fixture',
            'exit_code': 0,
            'expected_members': scope['expected_members'],
            'included_members': scope['included_members'],
            'excluded_members': [],
            'missing_members': [],
            'unknown_members': [],
        }
        if name == 'accounting':
            proof['accepted_scope'] = {'kind': 'member', 'declared': source_scope}
        _write_json(proof_path, proof)
        technical[name] = {
            'path': proof_path,
            'status': 'pass',
            'command': 'simulated-accepted-category-fixture',
            'exit_code': 0,
        }
    coverage = {
        'status': 'partial',
        'declared': source_scope,
        'reached': [source_scope],
        'inspected': [source_scope],
        'unreviewed': ['human acceptance'],
    }
    review = {
        'reviewer': 'agent:bible-fixture',
        'reviewed_at': '2026-09-08T00:00:00Z',
        'coverage': coverage,
        'source_quality_uncertainty': ['fixture scope only'],
        'discrepancies': [],
        'unreviewed_residuals': ['human acceptance not performed'],
    }
    review_path = base / 'evidence' / 'review.json'
    _write_json(review_path, {
        'contract': 'ocd-tei-review-v1',
        'identity': identity,
        'source': source_obj,
        'candidate': candidate_binding,
        'scope': source_scope,
        **review,
    })
    decision = {
        'source_local_disposition': 'Offline fixture simulation only',
        'blockers': [],
        'agent_assessment': {
            'status': 'accepted',
            'actor': 'agent:bible-fixture',
            'assessed_at': '2026-09-08T00:00:00Z',
            'supported_scope': source_scope,
            'unassessed_stronger_claims': ['real acceptance'],
            'unresolved_claims': [],
        },
        'human_decision': {'status': 'not-recorded'},
    }
    record = build_acceptance_record(
        base,
        identity=identity,
        candidate_path=candidate,
        source_accounting_path=source_accounting_path,
        scope=scope,
        technical=technical,
        review={**review, 'report_path': review_path},
        representation_revision={'id': revision, 'date': '2026-09-08', 'note': 'Bound category fixture.'},
        decision=decision,
        missing_members=[],
        unknown_members=[],
    )
    acceptance_path = edition_root / 'acceptance.json'
    write_acceptance(acceptance_path, record)
    return base, acceptance_path, case, source


@pytest.mark.requires_local_artifacts
def test_accepted_bible_requires_promotion_binds_authority_and_is_independent(tmp_path_factory, monkeypatch):
    from ocd_kernel.tei.acceptance import promote_accepted_master

    root, acceptance_path, case, source = _accepted_bible_fixture(tmp_path_factory)
    pending_errors = verify_accepted_bible(root, acceptance_path=acceptance_path, rows=[], receipt={})
    assert any('promoted' in error for error in pending_errors), pending_errors
    with pytest.raises(PipelineError, match='promoted'):
        project_accepted_bible(root, acceptance_path=acceptance_path)

    promoted = promote_accepted_master(
        root,
        acceptance_path=acceptance_path,
        destination=tmp_path_factory.mktemp('bc') / 'out',
    )
    output = project_accepted_bible(
        promoted.destination_root,
        acceptance_path=promoted.acceptance_path,
    )
    assert len(output['rows']) == len(source['verses']) == 3
    assert [row['text'] for row in output['rows']] == [item['text'] for item in source['verses']]
    authority = output['receipt']['authority']
    assert set(authority) == {'acceptance', 'work', 'master', 'acquisition'}
    assert all(set(binding) == {'path', 'sha256'} for binding in authority.values())
    assert verify_accepted_bible(
        promoted.destination_root,
        acceptance_path=promoted.acceptance_path,
        rows=output['rows'],
        receipt=output['receipt'],
    ) == []

    import ocd_kernel.projection.categories.bible as module
    monkeypatch.setattr(
        module,
        'project_bible_document',
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('producer called')),
    )
    assert verify_accepted_bible(
        promoted.destination_root,
        acceptance_path=promoted.acceptance_path,
        rows=output['rows'],
        receipt=output['receipt'],
    ) == []
    forged = copy.deepcopy(output['receipt'])
    forged['authority']['master']['sha256'] = '0' * 64
    assert verify_accepted_bible(
        promoted.destination_root,
        acceptance_path=promoted.acceptance_path,
        rows=output['rows'],
        receipt=forged,
    )

    work_path = promoted.destination_root / 'library' / 'works' / case['context']['identity']['work_id'] / 'work.json'
    work = json.loads(work_path.read_text(encoding='utf-8'))
    work['textual_forms'][0]['editions'][0]['category'] = 'commentary'
    _write_json(work_path, work)
    category_errors = verify_accepted_bible(
        promoted.destination_root,
        acceptance_path=promoted.acceptance_path,
        rows=output['rows'],
        receipt=output['receipt'],
    )
    assert any('Bible category' in error for error in category_errors), category_errors


def test_declared_preserve_space_verse_keeps_exact_source_text_and_is_checked(tmp_path, monkeypatch):
    case = CASES[0]
    tree = E.parse(str(FIXTURE / case['tei_file']))
    first = tree.xpath('//t:ab[@type="verse"]', namespaces={'t': TEI_NS})[0]
    first.set(f'{{{XML_NS}}}space', 'preserve')
    first.text = '  In  the beginning.  \n'
    path = tmp_path / 'preserved-bible.tei.xml'
    path.write_bytes(E.tostring(tree, encoding='utf-8'))
    context = _context(case)
    output = project(path, **context)
    assert output['rows'][0]['text'] == first.text
    assert output['rows'][1]['text'] == _result(case)['rows'][1]['text']
    verse_receipt = next(item for item in output['receipt']['inventory'] if item['tei_path'].endswith('/ab[1]'))
    assert verse_receipt['attributes']['xml:space'] == 'preserve'
    import ocd_kernel.projection.categories.bible as module
    monkeypatch.setattr(module, 'project_bible_document', lambda *args, **kwargs: pytest.fail('producer called'))
    assert verify(path, output['rows'], output['receipt'], **context) == []
    stripped = copy.deepcopy(output['rows'])
    stripped[0]['text'] = stripped[0]['text'].strip()
    assert verify(path, stripped, _forged_receipt_for_rows(output, stripped), **context)
    for value in ('default', 'invented'):
        first.set(f'{{{XML_NS}}}space', value)
        path.write_bytes(E.tostring(tree, encoding='utf-8'))
        with pytest.raises(PipelineError, match='ab/@xml:space'):
            project(path, **context)
        assert any('ab/@xml:space' in error for error in verify(path, [], {}, **context))
    first.set(f'{{{XML_NS}}}space', 'preserve')
    first.text = '  \n  '
    path.write_bytes(E.tostring(tree, encoding='utf-8'))
    blank = project(path, **context)
    assert blank['rows'][0]['text'] == first.text
    assert {'tei_path': blank['receipt']['anchors'][0]['tei_path'], 'reason': 'source-native-blank-verse-slot'} in blank['receipt']['warnings']
    assert verify(path, blank['rows'], blank['receipt'], **context) == []
    omitted = copy.deepcopy(blank['rows'])
    del omitted[0]
    assert verify(path, omitted, blank['receipt'], **context)
    invented = copy.deepcopy(blank['rows'])
    invented[0]['text'] = 'invented filler'
    assert verify(path, invented, blank['receipt'], **context)
    first.attrib.pop(f'{{{XML_NS}}}space')
    path.write_bytes(E.tostring(tree, encoding='utf-8'))
    with pytest.raises(PipelineError, match='empty Bible verse'):
        project(path, **context)
    assert any('empty Bible verse' in error for error in verify(path, [], {}, **context))
    first.set(f'{{{XML_NS}}}space', 'preserve')
    first.text = ''
    path.write_bytes(E.tostring(tree, encoding='utf-8'))
    empty = project(path, **context)
    assert empty['rows'][0]['text'] == ''
    assert {'tei_path': empty['receipt']['anchors'][0]['tei_path'],
            'reason': 'source-native-blank-verse-slot'} in empty['receipt']['warnings']
    assert verify(path, empty['rows'], empty['receipt'], **context) == []


@pytest.mark.requires_local_artifacts
def test_accepted_asv_uses_exact_source_native_namespace_without_rewriting_master(monkeypatch):
    import ocd_kernel.projection.categories.bible as module

    acceptance = ROOT / "library/works/asv/forms/english-asv/editions/retained-json/acceptance.json"
    master = acceptance.parent / "master.tei.xml"
    before = hashlib.sha256(master.read_bytes()).hexdigest()
    output = project_accepted_bible(ROOT, acceptance_path=acceptance)
    assert len(output["rows"]) == 31102
    assert {row["versification"] for row in output["rows"]} == {"source-native:ASV.json"}
    assert all(row["locator"]["versification"] == "source-native:ASV.json" for row in output["rows"])
    assert hashlib.sha256(master.read_bytes()).hexdigest() == before
    assert output["receipt"]["authority"]["acquisition"]["path"].endswith("scrollmapper-retained-json.json")

    monkeypatch.setattr(module, "_accepted_versification", lambda *args: (_ for _ in ()).throw(AssertionError("producer called")))
    assert verify_accepted_bible(ROOT, acceptance_path=acceptance, rows=output["rows"], receipt=output["receipt"]) == []


@pytest.mark.requires_local_artifacts
def test_accepted_revised_version_corpus_projects_all_source_members_without_rewriting_master(monkeypatch):
    import ocd_kernel.projection.categories.bible as module

    acceptance = ROOT / "library/works/revised-version-with-apocrypha/forms/revised-version-with-apocrypha-retained-en/editions/revised-version-with-apocrypha-electronic/acceptance.json"
    master = acceptance.parent / "master.tei.xml"
    before = hashlib.sha256(master.read_bytes()).hexdigest()
    output = project_accepted_bible(ROOT, acceptance_path=acceptance)
    assert output["receipt"]["mapping_version"] == module.CORPUS_MAPPING_VERSION
    assert output["receipt"]["master_sha256"] == before
    assert output["receipt"]["source_binding"]["source_url"] == "https://ebible.org/find/show.php?id=eng-rv"
    assert output["receipt"]["source_binding"]["package_url"] == "https://ebible.org/Scriptures/eng-rv_usfm.zip"
    for field in ("source_sha256", "retained_sha256"):
        assert output["receipt"]["source_binding"][field] == "3a89e51d2971fa40d36c6c7517abb674bb1f5c29ea9cbf845ce3e91c8d3d3ae9"
    namespace = "source-native:retained-member-set:revised-version-with-apocrypha-electronic:revised-version-with-apocrypha-accepted-electronic-v1"
    assert {row["versification"] for row in output["rows"]} == {
        namespace
    }
    assert all(row["locator"]["versification"] == namespace for row in output["rows"])
    assert [row["locator"]["source_order"] for row in output["rows"]] == list(range(1, len(output["rows"]) + 1))
    assert {int(anchor["tei_path"].split("/TEI[")[1].split("]")[0]) for anchor in output["receipt"]["anchors"]} == set(range(1, 81))
    assert hashlib.sha256(master.read_bytes()).hexdigest() == before

    monkeypatch.setattr(module, "_projection", lambda *args, **kwargs: pytest.fail("producer called"))
    assert verify_accepted_bible(ROOT, acceptance_path=acceptance, rows=output["rows"], receipt=output["receipt"]) == []


@pytest.mark.requires_local_artifacts
def test_accepted_engwebpb_retains_complete_source_order_and_continuation_notes(monkeypatch):
    import ocd_kernel.projection.categories.bible as module

    acceptance = ROOT / "library/works/engwebpb/forms/engwebpb-retained-en/editions/engwebpb-electronic-2020/acceptance.json"
    master = acceptance.with_name("master.tei.xml")
    before = hashlib.sha256(master.read_bytes()).hexdigest()
    output = project_accepted_bible(ROOT, acceptance_path=acceptance)
    rows = output["rows"]
    assert len(rows) == 31103
    assert sum(len(row["notes"]) for row in rows) == 1568
    assert len(output["inventory"]) == 68
    assert sum(item["retained_only_counts"].get("note", 0) for item in output["inventory"]) == 4
    assert sum(item["disposition"] == "source-member-retained-only" for item in output["inventory"]) == 2
    assert [row["locator"]["source_order"] for row in rows] == list(range(1, 31104))
    assert all(row["references"] == [] for row in rows)
    assert all(row["locator"]["reference_status"] == "unsupported-verse-components" for row in rows)
    assert all(row["versification"] == "source-native:retained-member-set:engwebpb-electronic-2020:engwebpb-retained-current-20261003-v1" for row in rows)
    assert output["receipt"]["mapping_version"] == module.ENGWEBPB_MAPPING_VERSION
    assert output["receipt"]["master_sha256"] == before
    assert hashlib.sha256(master.read_bytes()).hexdigest() == before

    monkeypatch.setattr(module, "_projection", lambda *args, **kwargs: pytest.fail("producer called"))
    monkeypatch.setattr(module, "_render", lambda *args, **kwargs: pytest.fail("producer renderer called"))
    assert verify_accepted_bible(ROOT, acceptance_path=acceptance, rows=rows, receipt=output["receipt"]) == []


@pytest.mark.requires_local_artifacts
def test_engwebpb_source_bindings_and_visible_body_fail_closed():
    import ocd_kernel.projection.categories.bible as module

    master = ROOT / "library/works/engwebpb/forms/engwebpb-retained-en/editions/engwebpb-electronic-2020/master.tei.xml"
    root, _raw, paths, parents = module._checker_parse(master)
    members = module._engwebpb_members()
    body = root.find(f"{{{TEI_NS}}}text/{{{TEI_NS}}}body")
    assert body is not None
    body.text = "invented"
    with pytest.raises(module.UnsupportedStructure, match="loose body text"):
        module._checker_engwebpb_validate(root, paths, parents, members)
    body.text = None

    first = next(node for node in body[0].iter() if node.get("corresp", "").endswith("#line=1"))
    original = first.get("corresp")
    first.set("corresp", original[:-1] + "2")
    with pytest.raises(module.UnsupportedStructure, match="source line order"):
        module._checker_engwebpb_validate(root, paths, parents, members)
    first.set("corresp", original)

    first.set("invented", "x")
    with pytest.raises(module.UnsupportedStructure, match="shape"):
        module._checker_engwebpb_validate(root, paths, parents, members)


@pytest.mark.requires_local_artifacts
def test_engwebpb_both_traversals_reject_source_attachment_and_body_mutations():
    import ocd_kernel.projection.categories.bible as module

    master = ROOT / "library/works/engwebpb/forms/engwebpb-retained-en/editions/engwebpb-electronic-2020/master.tei.xml"
    members = module._engwebpb_members()
    raw = master.read_bytes()
    producer = ET.fromstring(raw)
    checker, _raw, checker_paths, checker_parents = module._checker_parse(master)
    cases = (
        (producer, module._paths(producer), module._parents(producer), module._engwebpb_validate),
        (checker, checker_paths, checker_parents, module._checker_engwebpb_validate),
    )
    for root, paths, parents, validate in cases:
        text = root.find(f"{{{TEI_NS}}}text")
        body = text.find(f"{{{TEI_NS}}}body")
        first_section = body[0]
        line_nodes = [node for node in first_section.iter() if node.get("corresp", "").endswith("#line=1")]
        assert line_nodes
        line_node = line_nodes[0]

        def reject(node, field, changed, reason):
            original = node.get(field)
            node.set(field, changed)
            try:
                with pytest.raises(module.UnsupportedStructure, match=reason):
                    validate(root, paths, parents, members)
            finally:
                if original is None:
                    node.attrib.pop(field)
                else:
                    node.set(field, original)

        for node, field in ((root, "text"), (text, "text"), (first_section, "tail")):
            old = getattr(node, field)
            setattr(node, field, "invented")
            try:
                with pytest.raises(module.UnsupportedStructure, match="loose"):
                    validate(root, paths, parents, members)
            finally:
                setattr(node, field, old)

        reject(line_node, "corresp", line_node.get("corresp").replace("#line=1", "#line=2"), "source line order")
        reject(line_node, "corresp", line_node.get("corresp").replace("engwebpb/", "other/"), "source pointer")
        reject(line_node, "invented", "x", "shape")

        span = next(
            node for node in first_section.iter()
            if "&span=" in node.get("corresp", "")
            and int(node.get("corresp").split("&span=", 1)[1].split(":", 1)[1])
            <= len(members[0][1][int(node.get("corresp").split("#line=", 1)[1].split("&", 1)[0])])
        )
        source = span.get("corresp")
        line = int(source.split("#line=", 1)[1].split("&", 1)[0])
        changed = source.replace(f"#line={line}&", f"#line={line + 1}&")
        reject(span, "corresp", changed, "source span line")

        note = next(node for node in first_section.iter() if node.tag == f"{{{TEI_NS}}}note")
        note_parent = parents[note]
        note_index = list(note_parent).index(note)
        note_parent.remove(note)
        try:
            with pytest.raises(module.UnsupportedStructure, match="complete source carrier accounting"):
                validate(root, paths, parents, members)
        finally:
            note_parent.insert(note_index, note)

        empty = next(node for node in body.iter() if node.tag == f"{{{TEI_NS}}}ab" and
                     (module._engwebpb_blank_note_only(node) if validate is module._engwebpb_validate
                      else module._checker_engwebpb_blank_note_only(node)))
        source = empty.get("corresp")
        line = int(source.rsplit("=", 1)[-1])
        reject(empty, "corresp", source.rsplit("=", 1)[0] + "=" + str(line + 1), "blank verse source line")


@pytest.mark.requires_local_artifacts
def test_source_native_namespace_rejects_changed_member_or_asserted_standard():
    import ocd_kernel.projection.categories.bible as module

    acceptance = ROOT / "library/works/asv/forms/english-asv/editions/retained-json/acceptance.json"
    metadata = module._accepted_metadata(ROOT, acceptance)
    header = {"ids": {}}
    mismatched = copy.deepcopy(metadata)
    mismatched["acceptance"]["source"]["source_path"] = "raw/other/ASV.json"
    for derive in (module._accepted_versification, module._checker_accepted_versification):
        with pytest.raises(PipelineError, match="singular source-native"):
            derive(header, mismatched)
        with pytest.raises(PipelineError, match="disagrees with source-native"):
            declared = copy.deepcopy(metadata)
            declared["edition"].record["versification"] = "KJV"
            derive(header, declared)


def test_checker_constructs_schema_once_for_multiple_rows(monkeypatch):
    import ocd_kernel.projection.categories.bible as module

    case = CASES[0]
    output = _result(case)
    original = module._validator
    calls = []
    def counted():
        calls.append(1)
        return original()
    monkeypatch.setattr(module, "_validator", counted)
    assert verify(FIXTURE / case["tei_file"], output["rows"], output["receipt"], **_context(case)) == []
    assert len(calls) == 1
    invalid = copy.deepcopy(output["rows"])
    invalid[0]["text"] = None
    errors = verify(FIXTURE / case["tei_file"], invalid, output["receipt"], **_context(case))
    assert any("schema mismatch" in error for error in errors)
    assert len(calls) == 2
