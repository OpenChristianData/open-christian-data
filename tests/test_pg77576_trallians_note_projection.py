"""The accepted Trallians endnotes require a source-bound readable back row."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from lxml import etree
import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import cached_edition_lookups
import ocd_kernel.projection.categories.native_documents as native_documents
import ocd_kernel.projection.native_content as native_content
from ocd_kernel.projection.native_content_check import observe_content


ROOT = Path(__file__).resolve().parents[1]
EDITION = (ROOT / "library/works/pg77576-ignatius-trallians"
           / "forms/pg77576-ignatius-trallians-english"
           / "editions/pg77576-ignatius-trallians-pg77576-edition")
MAGNESIANS = (ROOT / "library/works/pg77576-ignatius-magnesians"
              / "forms/pg77576-ignatius-magnesians-english"
              / "editions/pg77576-ignatius-magnesians-pg77576-edition")
NS = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _digest(value: object) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")).encode()).hexdigest()


def test_accepted_trallians_endnotes_are_readable_without_changing_body_or_structure(monkeypatch) -> None:
    master = EDITION / "master.tei.xml"
    source = etree.parse(str(master))
    text = source.find(f".//{NS}text")
    notes = list(text.find(f"{NS}back").iter(f"{NS}note"))
    assert [note.get(XML_ID) for note in notes] == [f"f{number}" for number in range(986, 1077)]
    assert len(list(text.find(f"{NS}body").iter(f"{NS}choice"))) == 26
    assert len(list(text.find(f"{NS}back").iter(f"{NS}choice"))) == 57
    literal_bodies = [observe_content(etree.tostring(note[0], with_tail=False))[1]
                      for note in notes]
    assert all(body.startswith(f"{number}.") for number, body in enumerate(literal_bodies, 986))

    with cached_edition_lookups():
        projection = native_documents.project_accepted_document(
            ROOT, acceptance_path=EDITION / "acceptance.json", category="prose")
        rows, receipt = projection["rows"], projection["receipt"]
        assert len(rows) == 2
        assert receipt["mapping_version"] == native_documents.TRALLIANS_NOTE_PROFILE
        assert [len(row["text"]) for row in rows] == [25404, 4464]
        assert [len(row["source_references"]) for row in rows] == [182, 91]
        assert sha256(rows[0]["text"].encode()).hexdigest() == (
            "6fc2e851dc085d0fd150a21bdbe71cee8b22235ca9ceac1658c0a4bfce89af21")
        assert rows[1]["text"] == "\n\n".join(literal_bodies)
        assert sha256(rows[1]["text"].encode()).hexdigest() == (
            "ab7b54de3fca3110a24826e9d75bf0cb59945ef417c527438ef14eee9cc816dd")
        assert [_digest(row["structure"]) for row in rows] == [
            "1f7f1581a4cf21be6beada25636dcfdb05987b8c066611d4f77ce4909c51850f",
            "26491dee3f835762c006ddfb7ad0ac8ec6c46f693a8c44f8b1bfb2abaf3266c3"]
        assert [_digest(row["source_references"]) for row in rows] == [
            "87c75af5a4847794e562322dfd3ec0f304b86088addfd0d7c1fb78ba37cb788c",
            "ad511dcdcd71671d0557bdd4acae14f978ef17012f33369f4de2473bdd80d9bb"]

        def unavailable(*args, **kwargs):
            raise AssertionError("independent observer invoked a producer")

        monkeypatch.setattr(native_documents, "project_document", unavailable)
        monkeypatch.setattr(native_content, "project_content", unavailable)

        def verify(candidate):
            return native_documents.verify_accepted_document(
                ROOT, acceptance_path=EDITION / "acceptance.json", rows=candidate,
                receipt=receipt, category="prose")

        assert verify(rows) == []
        for mutation in ("empty", "missing", "reordered", "changed"):
            corrupted = deepcopy(rows)
            if mutation == "empty":
                corrupted[1]["text"] = ""
            elif mutation == "missing":
                corrupted[1]["text"] = "\n\n".join(literal_bodies[:-1])
            elif mutation == "reordered":
                corrupted[1]["text"] = "\n\n".join(reversed(literal_bodies))
            else:
                corrupted[1]["text"] = corrupted[1]["text"].replace("986.", "986?", 1)
            assert verify(corrupted), mutation


def test_trallians_profile_rejects_other_identity_and_note_attachment() -> None:
    raw = (EDITION / "master.tei.xml").read_bytes()
    identity = {"work_id": "pg77576-ignatius-trallians",
                "textual_form_id": "pg77576-ignatius-trallians-english",
                "edition_id": "pg77576-ignatius-trallians-pg77576-edition"}
    assert native_documents._trallians_note_route(
        identity, raw, category="prose", collection=False,
        projection_profile=None, allow_acceptance_metadata=True)
    for changed_identity, changed_raw in (({**identity, "edition_id": "unrelated"}, raw),
                                          (identity, raw + b"\n")):
        with pytest.raises(PipelineError):
            native_documents._trallians_note_route(
                changed_identity, changed_raw, category="prose", collection=False,
                projection_profile=None, allow_acceptance_metadata=True)
    et_unit = ET.fromstring(raw).find(f"{NS}text/{NS}back/{NS}div")
    lx_unit = etree.fromstring(raw).find(f"{NS}text/{NS}back/{NS}div")
    assert et_unit is not None and lx_unit is not None
    for label, unit in (("producer", et_unit), ("observer", lx_unit)):
        for mutation in ("wrong_note_number", "wrong_paragraph_number", "omitted_note"):
            changed = deepcopy(unit)
            if mutation == "wrong_note_number":
                changed[0].set("n", "987")
            elif mutation == "wrong_paragraph_number":
                changed[0][0].set("n", "2393")
            else:
                changed.remove(changed[-1])
            with pytest.raises((PipelineError, ValueError)):
                if label == "producer":
                    native_documents._numbered_note_text_et(
                        changed, first_number=986, count=91,
                        first_paragraph=2392, work_label="Trallians")
                else:
                    native_documents._numbered_note_text_lxml(
                        changed, first_number=986, count=91,
                        first_paragraph=2392, work_label="Trallians")


def test_magnesians_readable_back_row_remains_byte_identical() -> None:
    with cached_edition_lookups():
        projection = native_documents.project_accepted_document(
            ROOT, acceptance_path=MAGNESIANS / "acceptance.json", category="prose")
    rows = projection["rows"]
    assert projection["receipt"]["mapping_version"] == native_documents.MAGNESIANS_NOTE_PROFILE
    assert sha256(rows[1]["text"].encode()).hexdigest() == (
        "4d2125649d8be17712cc0217044995895557e09b535bafdd1db5cab3a5ea0733")
