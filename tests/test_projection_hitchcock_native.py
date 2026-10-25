"""Portable closed-profile lexical tests; optional unapplied adapter snapshot."""

import copy
import hashlib
import importlib.util
import os
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from ocd_kernel.projection.categories import reference_entries as current


T = "{http://www.tei-c.org/ns/1.0}"
ID = "{http://www.w3.org/XML/1998/namespace}id"


@pytest.fixture(scope="module")
def adapter():
    proposed = os.environ.get("OCD_HITCHCOCK_ADAPTER")
    if not proposed:
        return current
    path = Path(proposed)
    spec = importlib.util.spec_from_file_location("hitchcock_reviewed_adapter", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # The retained proposal lives under reports, not the installed package root.
    module.ROOT, module.SCHEMA, module.COMMON = current.ROOT, current.SCHEMA, current.COMMON
    return module


@pytest.fixture
def case(tmp_path):
    def create(work="hitchcocks-bible-names-dictionary", profile="hitchcock-native-lexical-v1"):
        identity = {"work_id": work, "textual_form_id": work + "-retained-electronic", "edition_id": work + "-retained-electronic-witness"}
        source = tmp_path / (work + ".jsonl")
        source.write_bytes(b'{"term":"Abel","definitions":["  first  ; literal\\tvalue  "]}\n{"term":"Abel","definitions":["second"]}\n')
        sha = hashlib.sha256(source.read_bytes()).hexdigest()
        root = ET.Element(T + "TEI", {ID: work + "-candidate"})
        header = ET.SubElement(root, T + "teiHeader")
        desc = ET.SubElement(ET.SubElement(header, T + "fileDesc"), T + "sourceDesc")
        binding = ET.SubElement(desc, T + "bibl", {"type": "ocd-acceptance-binding"})
        ET.SubElement(binding, T + "ptr", {"target": "https://example.org/retained"})
        for key, value in {**identity, "source_sha256": sha, "sha256": sha}.items():
            ET.SubElement(binding, T + "idno", {"type": key}).text = value
        ET.SubElement(binding, T + "note", {"type": "source-location"}).text = source.as_posix()
        body = ET.SubElement(ET.SubElement(root, T + "text", {ID: work + "-text", "type": "dictionary"}), T + "body", {ID: work + "-body"})
        census = []
        for ordinal, value in enumerate(("  first  ; literal\tvalue  ", "second"), 1):
            prefix = f"{work}-entry-{ordinal:05d}"
            entry = ET.SubElement(body, T + "entry", {ID: prefix, "n": str(ordinal)})
            ET.SubElement(ET.SubElement(entry, T + "form"), T + "orth", {"type": "headword"}).text = "Abel"
            ET.SubElement(ET.SubElement(entry, T + "sense", {ID: prefix + "-sense"}), T + "def", {ID: prefix + "-definition-001", "n": "1"}).text = value
            census.append({"id": prefix, "source_order": ordinal})
        path = tmp_path / (work + ".tei.xml")
        ET.ElementTree(root).write(path, encoding="utf-8")
        context = {"identity": identity, "edition_title": "Retained electronic witness", "source_url": "https://example.org/retained", "source_sha256": sha, "retained_sha256": sha, "source_path": source, "source_selector": {"tei_entry_profile": profile}, "source_scope": "Complete two-record fixture", "source_unit_count": 2, "source_selected_units": [item["id"] for item in census], "source_census": census, "source_excerpt_sha256": sha}
        return path, root, context
    return create


def project(adapter, path, context):
    projection = adapter.project_reference_entries(path, **context)
    receipt = adapter.build_reference_entries_receipt(projection, identity=context["identity"])
    assert adapter.verify_reference_entries(path, projection["rows"], receipt, **context) == []
    return projection, receipt


@pytest.mark.parametrize("work,profile", [("hitchcocks-bible-names-dictionary", "hitchcock-native-lexical-v1"), ("eastons-bible-dictionary", "easton-native-lexical-v1")])
def test_exact_native_opt_in_preserves_duplicates_and_whitespace(adapter, case, monkeypatch, work, profile):
    path, _, context = case(work, profile)
    projection, receipt = project(adapter, path, context)
    assert [row["headword"] for row in projection["rows"]] == ["Abel", "Abel"]
    assert projection["rows"][0]["definition_blocks"] == ["  first  ; literal\tvalue  "]
    assert projection["rows"][0]["text"] == "  first  ; literal\tvalue  "
    def disabled(*args, **kwargs):
        raise AssertionError("Producer traversal must not run in independent checker")
    for name in ("project_reference_entries", "_easton_lexical", "_row", "_render", "_entries", "_inventory"):
        monkeypatch.setattr(adapter, name, disabled)
    assert adapter.verify_reference_entries(path, projection["rows"], receipt, **context) == []


@pytest.mark.parametrize("mutation", ["missing-profile", "unknown-profile", "nonstring-profile", "easton-profile", "work", "form", "edition", "root"])
def test_native_opt_in_fails_closed(adapter, case, mutation):
    path, root, context = case()
    if mutation == "missing-profile": context["source_selector"] = None
    elif mutation == "unknown-profile": context["source_selector"]["tei_entry_profile"] = "invented"
    elif mutation == "nonstring-profile": context["source_selector"]["tei_entry_profile"] = {}
    elif mutation == "easton-profile": context["source_selector"]["tei_entry_profile"] = "easton-native-lexical-v1"
    elif mutation == "root":
        root.set(ID, "eastons-bible-dictionary-candidate")
        ET.ElementTree(root).write(path, encoding="utf-8")
    else:
        key = {"work": "work_id", "form": "textual_form_id", "edition": "edition_id"}[mutation]
        context["identity"][key] = "another-valid-id"
    with pytest.raises(adapter.UnsupportedStructure, match="unsupported-visible"):
        adapter.project_reference_entries(path, **context)
    errors = adapter.verify_reference_entries(path, [], {}, **context)
    assert len(errors) == 1 and "unsupported-visible" in errors[0]


@pytest.mark.parametrize("mutation", ["body-id", "entry-id", "definition-n", "swap-fields", "nested-definition", "unknown-attribute", "foreign-namespace", "meaningful-tail"])
def test_native_structure_rejected_by_both_routes(adapter, case, mutation):
    path, root, context = case()
    body = root.find(T + "text/" + T + "body")
    first = body[0]
    if mutation == "body-id": body.set(ID, "wrong-body")
    elif mutation == "entry-id": first.set(ID, "wrong-entry")
    elif mutation == "definition-n": first[1][0].set("n", "2")
    elif mutation == "swap-fields": first[:] = [first[1], first[0]]
    elif mutation == "nested-definition": ET.SubElement(first[1][0], T + "hi").text = "invented"
    elif mutation == "unknown-attribute": first[0][0].set("rend", "bold")
    elif mutation == "foreign-namespace": first[1][0].tag = "{urn:foreign}def"
    elif mutation == "meaningful-tail": first[0][0].tail = "invented"
    ET.ElementTree(root).write(path, encoding="utf-8")
    with pytest.raises(adapter.UnsupportedStructure):
        adapter.project_reference_entries(path, **context)
    errors = adapter.verify_reference_entries(path, [], {}, **context)
    assert len(errors) == 1
    assert any(part in errors[0] for part in ("unsupported-visible", "checker: Easton"))


@pytest.mark.parametrize("mutation", ["headword", "definition", "row-omit", "row-duplicate", "row-order", "inventory-tail", "source-census-order"])
def test_saved_public_receipt_mutations_rejected_without_producer(adapter, case, monkeypatch, mutation):
    path, _, context = case()
    projection, receipt = project(adapter, path, context)
    rows, receipt = copy.deepcopy(projection["rows"]), copy.deepcopy(receipt)
    if mutation == "headword": rows[0]["headword"] = "invented"
    elif mutation == "definition": rows[0]["definition_blocks"][0] = "invented"
    elif mutation == "row-omit": rows.pop()
    elif mutation == "row-duplicate": rows.append(copy.deepcopy(rows[-1]))
    elif mutation == "row-order": rows.reverse()
    elif mutation == "inventory-tail": receipt["inventory"][-1]["tail_sha256"] = "0" * 64
    elif mutation == "source-census-order": receipt["source_accounting"]["census"].reverse()
    def disabled(*args, **kwargs): raise AssertionError("Producer called")
    for name in ("project_reference_entries", "_easton_lexical", "_render"):
        monkeypatch.setattr(adapter, name, disabled)
    errors = adapter.verify_reference_entries(path, rows, receipt, **context)
    assert any("mismatch" in error or "independent TEI traversal" in error for error in errors)


@pytest.mark.parametrize("mutation", ["literal-whitespace", "private-framing-tail"])
def test_private_mutations_reject_original_saved_receipt(adapter, case, mutation):
    path, root, context = case()
    projection, receipt = project(adapter, path, context)
    first = root.find(T + "text/" + T + "body")[0]
    if mutation == "literal-whitespace": first[1][0].text = first[1][0].text.strip()
    else: first.tail = "\n  "
    ET.ElementTree(root).write(path, encoding="utf-8")
    errors = adapter.verify_reference_entries(path, projection["rows"], receipt, **context)
    assert "reference receipt master_sha256 mismatch" in errors
    assert "reference receipt inventory mismatch" in errors
