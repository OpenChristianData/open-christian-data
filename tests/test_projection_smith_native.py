"""Smith retained lexical profile remains exact and independently checked."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import os
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from ocd_kernel.projection.categories import reference_entries as current


T = "{http://www.tei-c.org/ns/1.0}"
ID = "{http://www.w3.org/XML/1998/namespace}id"
WORK = "smiths-bible-dictionary"
PROFILE = "smith-native-lexical-v1"


@pytest.fixture(scope="module")
def adapter():
    proposed = os.environ.get("OCD_SMITH_ADAPTER")
    if not proposed:
        return current
    path = Path(proposed)
    spec = importlib.util.spec_from_file_location("smith_reviewed_adapter", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT, module.SCHEMA, module.COMMON = current.ROOT, current.SCHEMA, current.COMMON
    return module


@pytest.fixture
def case(tmp_path: Path):
    identity = {"work_id": WORK, "textual_form_id": WORK + "-retained-electronic", "edition_id": WORK + "-retained-electronic-witness"}
    source = tmp_path / "smiths.jsonl"
    source.write_text('{"term":"Aaron","definitions":["  first\\tpart  ","second\\nline"]}\n{"term":"Aaron","definitions":["third"]}\n', encoding="utf-8")
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    root = ET.Element(T + "TEI", {ID: WORK + "-candidate"})
    desc = ET.SubElement(ET.SubElement(ET.SubElement(root, T + "teiHeader"), T + "fileDesc"), T + "sourceDesc")
    binding = ET.SubElement(desc, T + "bibl", {"type": "ocd-acceptance-binding"})
    ET.SubElement(binding, T + "ptr", {"target": "https://example.org/retained"})
    for key, value in {**identity, "source_sha256": sha, "sha256": sha}.items():
        ET.SubElement(binding, T + "idno", {"type": key}).text = value
    ET.SubElement(binding, T + "note", {"type": "source-location"}).text = source.as_posix()
    body = ET.SubElement(ET.SubElement(root, T + "text", {ID: WORK + "-text", "type": "dictionary"}), T + "body", {ID: WORK + "-body"})
    census = []
    for ordinal, blocks in enumerate((("  first\tpart  ", "second\nline"), ("third",)), 1):
        prefix = f"{WORK}-entry-{ordinal:05d}"
        entry = ET.SubElement(body, T + "entry", {ID: prefix, "n": str(ordinal)})
        ET.SubElement(ET.SubElement(entry, T + "form"), T + "orth", {"type": "headword"}).text = "Aaron"
        sense = ET.SubElement(entry, T + "sense", {ID: prefix + "-sense"})
        for number, block in enumerate(blocks, 1):
            ET.SubElement(sense, T + "def", {ID: f"{prefix}-definition-{number:03d}", "n": str(number)}).text = block
        census.append({"id": prefix, "source_order": ordinal})
    path = tmp_path / "smiths.tei.xml"
    ET.ElementTree(root).write(path, encoding="utf-8")
    context = {"identity": identity, "edition_title": "Retained electronic witness", "source_url": "https://example.org/retained", "source_sha256": sha, "retained_sha256": sha, "source_path": source, "source_selector": {"tei_entry_profile": PROFILE}, "source_scope": "Complete two-record fixture", "source_unit_count": 2, "source_selected_units": [item["id"] for item in census], "source_census": census, "source_excerpt_sha256": sha}
    return path, root, context


def test_smith_multiple_definitions_duplicate_terms_and_literal_whitespace(adapter, case, monkeypatch):
    path, _, context = case
    projection = adapter.project_reference_entries(path, **context)
    receipt = adapter.build_reference_entries_receipt(projection, identity=context["identity"])
    rows = projection["rows"]
    assert [row["headword"] for row in rows] == ["Aaron", "Aaron"]
    assert rows[0]["definition_blocks"] == ["  first\tpart  ", "second\nline"]
    assert rows[0]["text"] == "  first\tpart  \n\nsecond\nline"
    assert [row["source_order"] for row in rows] == [1, 2]

    def disabled(*args, **kwargs):
        raise AssertionError("Producer traversal called by independent checker")

    for name in ("project_reference_entries", "_easton_lexical", "_render", "_entries", "_inventory"):
        monkeypatch.setattr(adapter, name, disabled)
    assert adapter.verify_reference_entries(path, rows, receipt, **context) == []


@pytest.mark.parametrize("mutation", ["profile", "form", "edition", "root"])
def test_smith_exact_profile_identity_rejects_wrong_binding(adapter, case, mutation):
    path, root, context = case
    if mutation == "profile":
        context["source_selector"]["tei_entry_profile"] = "hitchcock-native-lexical-v1"
    elif mutation == "root":
        root.set(ID, "hitchcocks-bible-names-dictionary-candidate")
        ET.ElementTree(root).write(path, encoding="utf-8")
    else:
        context["identity"][{"form": "textual_form_id", "edition": "edition_id"}[mutation]] = "another-valid-id"
    with pytest.raises(adapter.UnsupportedStructure, match="unsupported-visible"):
        adapter.project_reference_entries(path, **context)
    assert any("unsupported-visible" in error for error in adapter.verify_reference_entries(path, [], {}, **context))


@pytest.mark.parametrize("mutation", ["missing-middle-definition", "reordered-definition", "unknown-attribute", "term-change"])
def test_smith_native_shape_mutations_fail_closed(adapter, case, mutation):
    path, root, context = case
    first = root.find(T + "text/" + T + "body")[0]
    if mutation == "missing-middle-definition":
        first[1].remove(first[1][0])
    elif mutation == "reordered-definition":
        first[1][0].set("n", "2")
    elif mutation == "unknown-attribute":
        first[0][0].set("rend", "invented")
    else:
        first[0][0].text = "Invented"
    ET.ElementTree(root).write(path, encoding="utf-8")
    if mutation == "term-change":
        # The source remains unchanged, and a saved receipt must reject the new master.
        original = copy.deepcopy(root)
        original.find(T + "text/" + T + "body")[0][0][0].text = "Aaron"
        ET.ElementTree(original).write(path, encoding="utf-8")
        projection = adapter.project_reference_entries(path, **context)
        receipt = adapter.build_reference_entries_receipt(projection, identity=context["identity"])
        ET.ElementTree(root).write(path, encoding="utf-8")
        errors = adapter.verify_reference_entries(path, projection["rows"], receipt, **context)
        assert any("rows do not match" in error or "master_sha256" in error for error in errors)
    else:
        with pytest.raises(adapter.UnsupportedStructure):
            adapter.project_reference_entries(path, **context)
        assert adapter.verify_reference_entries(path, [], {}, **context)
