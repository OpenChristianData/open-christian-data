"""The accepted Magnesians endnotes have a readable, source-bound back row."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from lxml import etree

from ocd_kernel.library.identities import cached_edition_lookups
import ocd_kernel.projection.categories.native_documents as native_documents
import ocd_kernel.projection.native_content as native_content
from ocd_kernel.projection.native_content_check import observe_content


ROOT = Path(__file__).resolve().parents[1]
EDITION = (ROOT / "library/works/pg77576-ignatius-magnesians"
           / "forms/pg77576-ignatius-magnesians-english"
           / "editions/pg77576-ignatius-magnesians-pg77576-edition")
NS = {"t": "http://www.tei-c.org/ns/1.0"}


def _digest(value: object) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")).encode()).hexdigest()


def test_accepted_magnesians_endnotes_are_readable_without_changing_native_evidence(monkeypatch) -> None:
    notes = etree.parse(str(EDITION / "master.tei.xml")).xpath(
        "/t:TEI/t:text/t:back/t:div[@type='notes']/t:note", namespaces=NS)
    assert [note.get("{http://www.w3.org/XML/1998/namespace}id") for note in notes] == [
        f"f{number}" for number in range(890, 986)]
    literal_bodies = [observe_content(etree.tostring(note[0], with_tail=False))[1]
                      for note in notes]
    assert all(body.startswith(f"{number}.") for number, body in enumerate(literal_bodies, 890))

    with cached_edition_lookups():
        projection = native_documents.project_accepted_document(
            ROOT, acceptance_path=EDITION / "acceptance.json", category="prose")
        rows, receipt = projection["rows"], projection["receipt"]
        assert len(rows) == 2
        assert receipt["mapping_version"] == native_documents.MAGNESIANS_NOTE_PROFILE
        assert [len(row["source_references"]) for row in rows] == [192, 96]
        assert sha256(rows[0]["text"].encode()).hexdigest() == (
            "ce0f238350822c75cd13954efce7230b7ba0afc47f7ca870df2da31d7d50027a")
        assert rows[1]["text"] == "\n\n".join(literal_bodies)
        assert sha256(rows[1]["text"].encode()).hexdigest() == (
            "4d2125649d8be17712cc0217044995895557e09b535bafdd1db5cab3a5ea0733")
        assert [_digest(row["structure"]) for row in rows] == [
            "ec1158491b81046226a41c515195988d18ee9e77d95dba1bf99601feb44ef2a6",
            "c3f3488dc3467fbb6fc26d9c411fde0aa424ed0685d68ed520cb137d235e1d3c"]
        assert [_digest(row["source_references"]) for row in rows] == [
            "4e506a7f6aecdd6e7d795d4b51fb73c6fa662974999938ff2d3a484adc3b8a9d",
            "5c494953829f7f70b47a37d2d1841e4a47e56d33a3dc00dbe282dacc6927fc74"]

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
                corrupted[1]["text"] = corrupted[1]["text"].replace("890.", "890?", 1)
            assert verify(corrupted), mutation
