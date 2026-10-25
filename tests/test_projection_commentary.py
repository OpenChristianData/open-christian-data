"""PIPE-007B source-bound commentary units and independent receipt checking."""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
import subprocess
import sys
from pathlib import Path

from lxml import etree as E
import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.envelope import canonical_row_bytes, row_text_hash
from ocd_kernel.projection.categories.commentary import (
    project_accepted_commentary,
    project_commentary_document as project,
    verify_accepted_commentary,
    verify_commentary_document as verify,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "library-pipeline" / "categories" / "commentary"
ARTIFACT = ROOT / "plans" / "2026-08-31-library-pipeline-redesign" / "artifacts" / "PIPE-007B"
MANIFEST = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
CASES = MANIFEST["fixtures"]
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"


def _source(case: dict) -> dict:
    return json.loads((FIXTURE / f"source-{case['fixture_id']}.json").read_text(encoding="utf-8"))


def _context(case: dict) -> dict:
    source = _source(case)
    return {
        "identity": source["identity"],
        "language": "en",
        "representation_revision": source["representation_revision"],
        "edition_title": source["edition_title"],
        "scope_id": case["scope_id"],
        "source_url": source["source_url"],
        "source_sha256": source["source_sha256"],
        "retained_sha256": source["retained_source_sha256"],
    }


def _result(case: dict) -> dict:
    return project(FIXTURE / Path(case["tei_path"]).name, **_context(case))


def test_commentary_entry_attribution_preserves_distinct_context(tmp_path: Path, monkeypatch) -> None:
    case = CASES[0]
    baseline = _result(case)
    path = tmp_path / 'attribution.xml'
    tree = E.parse(str(FIXTURE / Path(case['tei_path']).name))
    anchor_path = baseline['receipt']['anchors'][0]['tei_path']
    qualified_path = '/'.join('tei:'+part if part else '' for part in anchor_path.split('/'))
    unit = tree.xpath(qualified_path, namespaces={'tei':TEI_NS})[0]
    note = E.SubElement(unit, '{'+TEI_NS+'}note', type='source-attribution')
    fields = {'source-title':'Homily source', 'source-credit':'Source provider', 'attribution-note':'Additional author context'}
    for role, text in fields.items():
        E.SubElement(note, '{'+TEI_NS+'}seg', type=role).text = text
    E.SubElement(note, '{'+TEI_NS+'}ref', type='source-url', target='https://example.org/homily').text = 'Source'
    tree.write(str(path), encoding='utf-8')
    out = project(path, **_context(case))
    for role, text in fields.items():
        assert out['rows'][0]['provenance'][role.replace('-', '_')] == text
    assert out['rows'][0]['provenance']['source_url'] == 'https://example.org/homily'
    from ocd_kernel.projection.categories import commentary
    monkeypatch.setattr(commentary, '_entry_attribution', lambda *a: pytest.fail('producer called'))
    assert verify(path, out['rows'], out['receipt'], **_context(case)) == []
    changed = copy.deepcopy(out['rows'])
    changed[0]['provenance']['attribution_note'] = 'Source provider'
    assert verify(path, changed, out['receipt'], **_context(case))


@pytest.mark.parametrize('raw', ['Bible:John.3.16a-4.2b', 'Bible:Unknown.3.1'])
def test_commentary_explicit_reference_normalization(tmp_path, monkeypatch, raw):
    case = CASES[0]
    baseline = _result(case)
    tree = E.parse(str(FIXTURE / Path(case['tei_path']).name))
    anchor = baseline['receipt']['anchors'][0]['tei_path']
    unit = tree.xpath('/'.join('t:'+part if part else '' for part in anchor.split('/')), namespaces={'t':TEI_NS})[0]
    for key in ('scope', 'target', 'osisRef', 'cRef', 'corresp'):
        unit.attrib.pop(key, None)
    unit.set('scope', raw)
    path = tmp_path / 'target.xml'
    tree.write(str(path), encoding='utf-8')
    out = project(path, **_context(case))
    scope = out['rows'][0]['locator']['scope']
    assert scope['raw'] == raw
    if 'Unknown' in raw:
        assert scope['normalization_status'] == 'unsupported-explicit-target'
        assert 'reference' not in scope
    else:
        assert scope['reference']['normalized'] == 'John.3.16a-John.4.2b'
        assert scope['reference']['end'] == {'book':'John','chapter':4,'verse':'2b'}
    from ocd_kernel.projection.categories import commentary
    monkeypatch.setattr(commentary, 'normalize_explicit_target', lambda *a, **k: pytest.fail('producer called'))
    assert verify(path, out['rows'], out['receipt'], **_context(case)) == []
    changed = copy.deepcopy(out['receipt'])
    changed['book_codes_sha256'] = '0'*64
    assert verify(path, out['rows'], changed, **_context(case))
    if 'reference' in scope:
        changed_rows = copy.deepcopy(out['rows'])
        changed_rows[0]['locator']['scope']['reference']['normalized'] = 'John.3.16'
        assert verify(path, changed_rows, out['receipt'], **_context(case))


@pytest.mark.parametrize('invalid', [None, 'empty', 'duplicate'])
def test_commentary_source_scope_labels_are_explicit(tmp_path, monkeypatch, invalid):
    case = CASES[0]
    baseline = _result(case)
    tree = E.parse(str(FIXTURE / Path(case['tei_path']).name))
    anchor = baseline['receipt']['anchors'][0]['tei_path']
    unit = tree.xpath('/'.join('t:'+part if part else '' for part in anchor.split('/')), namespaces={'t':TEI_NS})[0]
    label = E.SubElement(unit, '{'+TEI_NS+'}label', type='scripture-reference')
    label.text = 'The source reference wording'
    E.SubElement(unit, '{'+TEI_NS+'}label', type='scripture-book').text = 'Source book name'
    if invalid == 'empty':
        label.text = ''
    elif invalid == 'duplicate':
        unit.append(copy.deepcopy(label))
    path = tmp_path / 'labels.xml'
    tree.write(str(path), encoding='utf-8')
    if invalid:
        with pytest.raises(PipelineError):
            project(path, **_context(case))
        assert verify(path, [], {}, **_context(case))
        return
    out = project(path, **_context(case))
    scope = out['rows'][0]['locator']['scope']
    assert scope['source_label'] == 'The source reference wording'
    assert scope['book_label'] == 'Source book name'
    assert all('source_label' not in row['locator']['scope'] for row in out['rows'][1:])
    from ocd_kernel.projection.categories import commentary
    monkeypatch.setattr(commentary, '_source_scope_labels', lambda *a: pytest.fail('producer called'))
    assert verify(path, out['rows'], out['receipt'], **_context(case)) == []
    changed = copy.deepcopy(out['rows'])
    changed[0]['locator']['scope']['source_label'] = scope['normalized']
    assert verify(path, changed, out['receipt'], **_context(case))


@pytest.mark.parametrize('target', ['John', 'John.3', 'John.3.16'])
def test_commentary_introduction_requires_explicit_role(tmp_path, target):
    case = CASES[0]
    baseline = _result(case)
    tree = E.parse(str(FIXTURE / Path(case['tei_path']).name))
    anchor = baseline['receipt']['anchors'][0]['tei_path']
    unit = tree.xpath('/'.join('t:'+part if part else '' for part in anchor.split('/')), namespaces={'t':TEI_NS})[0]
    for key in ('scope', 'target', 'osisRef', 'cRef', 'corresp'):
        unit.attrib.pop(key, None)
    unit.set('scope', target)
    path = tmp_path / 'intro.xml'
    tree.write(str(path), encoding='utf-8')
    ordinary = project(path, **_context(case))
    assert 'unit_role' not in ordinary['rows'][0]['locator']
    unit.set('subtype', 'introduction')
    tree.write(str(path), encoding='utf-8')
    if target == 'John.3.16':
        with pytest.raises(PipelineError):
            project(path, **_context(case))
        assert verify(path, [], {}, **_context(case))
        return
    out = project(path, **_context(case))
    locator = out['rows'][0]['locator']
    assert locator['unit_role'] == 'introduction'
    assert locator['scope']['reference']['start']['chapter'] == (3 if target == 'John.3' else None)
    assert verify(path, out['rows'], out['receipt'], **_context(case)) == []
    changed = copy.deepcopy(out['rows'])
    changed[0]['locator'].pop('unit_role')
    assert verify(path, changed, out['receipt'], **_context(case))


def test_commentary_cross_references_preserve_targets_and_ranges(tmp_path, monkeypatch):
    case = CASES[0]
    baseline = _result(case)
    tree = E.parse(str(FIXTURE / Path(case['tei_path']).name))
    anchor = baseline['receipt']['anchors'][0]['tei_path']
    unit = tree.xpath('/'.join('t:'+part if part else '' for part in anchor.split('/')), namespaces={'t':TEI_NS})[0]
    paragraph = E.SubElement(unit, '{'+TEI_NS+'}p')
    targets = ['Bible:John.3.16a-4.2b', 'Bible:Unknown.1.1', 'https://example.org/source']
    for index, target in enumerate(targets):
        ref = E.SubElement(paragraph, '{'+TEI_NS+'}ref', type='scripture-cross-reference' if index < 2 else 'source', target=target)
        ref.text = 'Printed reference '+str(index)
        ref.tail = ' '
    path = tmp_path / 'crossrefs.xml'
    tree.write(str(path), encoding='utf-8')
    out = project(path, **_context(case))
    refs = out['rows'][0]['references'][-3:]
    assert [ref['source_target'] for ref in refs] == targets
    assert refs[0]['source_role'] == 'scripture-cross-reference'
    assert refs[0]['scripture']['normalized'] == 'John.3.16a-John.4.2b'
    assert refs[1]['normalization_status'] == 'unsupported-explicit-target'
    assert 'scripture' not in refs[1]
    assert 'normalization_status' not in refs[2]
    from ocd_kernel.projection.categories import commentary
    monkeypatch.setattr(commentary, 'normalize_explicit_target', lambda *a, **k: pytest.fail('producer called'))
    assert verify(path, out['rows'], out['receipt'], **_context(case)) == []
    for mutation in ('drop-target', 'drop-endpoint', 'swap'):
        changed = copy.deepcopy(out['rows'])
        references = changed[0]['references']
        if mutation == 'drop-target':
            references[-3].pop('source_target')
        elif mutation == 'drop-endpoint':
            references[-3]['scripture']['normalized'] = 'John.3.16a'
        else:
            references[-3], references[-2] = references[-2], references[-3]
        assert verify(path, changed, out['receipt'], **_context(case))


@pytest.mark.parametrize(('language', 'label'), [(None,'John'), ('en','John'), ('en-US','John'), ('fr','Jean'), ('en','Exodus')])
def test_commentary_english_book_name_requires_evidence(tmp_path, language, label):
    case = CASES[0]
    baseline = _result(case)
    tree = E.parse(str(FIXTURE / Path(case['tei_path']).name))
    anchor = baseline['receipt']['anchors'][0]['tei_path']
    unit = tree.xpath('/'.join('t:'+part if part else '' for part in anchor.split('/')), namespaces={'t':TEI_NS})[0]
    for key in ('scope','target','osisRef','cRef','corresp'):
        unit.attrib.pop(key, None)
    unit.set('scope', 'John.3')
    node = E.SubElement(unit, '{'+TEI_NS+'}label', type='scripture-book')
    node.text = label
    if language:
        node.set('{'+XML_NS+'}lang', language)
    path = tmp_path / 'english.xml'
    tree.write(str(path), encoding='utf-8')
    if label == 'Exodus':
        with pytest.raises(PipelineError, match='contradicts'):
            project(path, **_context(case))
        assert verify(path, [], {}, **_context(case))
        return
    out = project(path, **_context(case))
    scope = out['rows'][0]['locator']['scope']
    assert scope['book_label'] == label
    if language in ('en','en-US'):
        assert scope['english_book_name'] == 'John'
        assert scope['book_name_status'] == 'explicit-english-label'
    else:
        assert 'english_book_name' not in scope
        assert scope['book_name_status'] == 'english-language-not-declared'
    assert verify(path, out['rows'], out['receipt'], **_context(case)) == []


def _forged_receipt_for_rows(result: dict, rows: list[dict]) -> dict:
    """Keep the receipt pending while making only row accounting agree."""

    receipt = copy.deepcopy(result["receipt"])
    receipt["row_count"] = len(rows)
    receipt["output_sha256"] = hashlib.sha256(canonical_row_bytes(rows)).hexdigest()
    receipt["independent_check"] = {"status": "pending", "errors": []}
    for anchor, row in zip(receipt["anchors"], rows):
        anchor["record_id"] = row.get("record_id")
        anchor["text_sha256"] = row_text_hash(str(row.get("text", "")))
        if isinstance(row.get("locator"), dict):
            anchor["locator"] = copy.deepcopy(row["locator"])
            anchor["source_order"] = row["locator"].get("source_order")
    return receipt


def test_three_real_commentary_extracts_preserve_scopes_order_and_accounting():
    assert MANIFEST["category"] == "commentary"
    assert MANIFEST["fixture_count"] == 3
    assert MANIFEST["native_unit_count"] == 40
    assert MANIFEST["selected_unit_count"] == 8
    assert MANIFEST["outside_scope_unit_count"] == 32
    assert MANIFEST["excluded_source_scope_unit_count"] == 1
    assert MANIFEST["excluded_tei_unit_count"] == 0

    for case in CASES:
        source = _source(case)
        result = _result(case)
        selected = source["selected_units"]
        assert [row["text"] for row in result["rows"]] == [item["normalized_text"] for item in selected]
        assert [row["locator"]["scope"]["raw"] for row in result["rows"]] == [item["scope"] for item in selected]
        assert [row["sequence"] for row in result["rows"]] == list(range(1, len(selected) + 1))
        assert [row["locator"]["source_order"] for row in result["rows"]] == list(range(1, len(selected) + 1))
        assert all(row["category"] == "commentary" for row in result["rows"])
        assert result["rows"][0]["locator"]["scope"]["type"] in {"book", "chapter", "range"}
        assert result["receipt"]["source_binding"] == {
            "source_url": source["source_url"],
            "retained_sha256": source["retained_source_sha256"],
            "source_sha256": source["source_sha256"],
        }
        assert result["receipt"]["master_sha256"] == hashlib.sha256((FIXTURE / Path(case["tei_path"]).name).read_bytes()).hexdigest()
        assert result["receipt"]["scope_id"] == case["scope_id"]
        assert result["receipt"]["row_count"] == len(selected)
        assert result["receipt"]["unsupported"] == []
        assert result["receipt"]["independent_check"] == {"status": "pending", "errors": []}
        inventory = result["receipt"]["inventory"]
        assert {item["disposition"] for item in inventory} >= {"private-header", "structure", "row-content", "outside-scope"}
        assert sum(item["disposition"] == "outside-scope" and item["attributes"].get("type") == "commentary-unit" for item in inventory) == source["outside_scope_count"]
        assert sum(item["disposition"] == "row-content" and item["attributes"].get("type") == "commentary-unit" for item in inventory) == source["selected_unit_count"]
        assert len(result["receipt"]["exclusions"]) >= source["outside_scope_count"]
        assert verify(FIXTURE / Path(case["tei_path"]).name, result, **_context(case)) == []

    # A source carrier remains one occurrence, and the first Matthew Henry
    # carrier is not inferred to end at the next carrier's number.
    henry = next(item for item in CASES if item["fixture_id"] == "matthew-henry-gen-1")
    henry_result = _result(henry)
    assert len(henry_result["rows"]) == 3
    assert henry_result["rows"][-1]["locator"]["scope"]["raw"] == "Bible:GEN.1.1"
    assert henry_result["rows"][-1]["locator"]["scope"]["type"] == "verse"


@pytest.mark.requires_local_artifacts
def test_fixture_excerpts_are_dynamically_bound_to_retained_raw_witnesses():
    """The checked-in fixture JSON is checked against the retained source at run time."""

    for case in CASES:
        source = _source(case)
        raw_path = ROOT / source["source_path"]
        assert raw_path.exists()
        assert hashlib.sha256(raw_path.read_bytes()).hexdigest() == source["source_sha256"]
        assert source["source_url"] == "ocd-source:" + source["source_path"]
        selector = source["source_selector"]
        expected_native: list[dict] = []
        if selector["kind"] == "json-api":
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            chapter = raw["chapter"]
            selected_selectors = set(selector["selected_selectors"])
            if selector.get("native_scope") != "chapter":
                expected_native.append({"selector": "book.introduction", "scope": f"Bible:{selector['book_id']}", "text": raw["book"]["introduction"], "selected": "book.introduction" in selected_selectors})
            if chapter.get("introduction") is not None:
                expected_native.append({"selector": "chapter.introduction", "scope": f"Bible:{selector['book_id']}.{chapter['number']}", "text": chapter["introduction"], "selected": "chapter.introduction" in selected_selectors})
            for item in chapter["content"]:
                assert isinstance(item.get("content"), list) and len(item["content"]) == 1
                native_selector = f"chapter.content[{item['number']}]"
                expected_native.append({"selector": native_selector, "scope": f"Bible:{selector['book_id']}.{chapter['number']}.{item['number']}", "text": item["content"][0], "selected": native_selector in selected_selectors})
        else:
            tree = E.parse(str(raw_path), E.XMLParser(recover=True, load_dtd=False, resolve_entities=False, no_network=True))
            paragraph = tree.xpath('//p[@id="ii.ii-p3"]')[0]
            selected_selectors = set(selector["selected_selectors"])
            for ref in paragraph.xpath("./scripRef"):
                native_selector = f'//p[@id="ii.ii-p3"]/scripRef[@id="{ref.get("id")}"]'
                label = " ".join("".join(ref.itertext()).split())
                text = " ".join((label + (ref.tail or "")).split())
                expected_native.append({"selector": native_selector, "scope": ref.get("osisRef"), "text": text, "selected": native_selector in selected_selectors})
        assert [item["selector"] for item in source["native_units"]] == [item["selector"] for item in expected_native]
        for actual, expected in zip(source["native_units"], expected_native):
            assert actual["scope"] == expected["scope"]
            assert actual["text"] == expected["text"]
            assert actual["normalized_text"] == " ".join(expected["text"].split())
            assert actual["selected"] is expected["selected"]
            assert actual["text_sha256"] == hashlib.sha256(actual["normalized_text"].encode("utf-8")).hexdigest()
        assert [item["selector"] for item in source["outside_scope"]] == [item["selector"] for item in expected_native if not item["selected"]]
        assert source["outside_scope_count"] == len(source["outside_scope"]) == len(expected_native) - len(source["selected_units"])
        assert source["selected_units"] == [item for item in source["native_units"] if item["selected"]]
        if selector.get("native_scope") == "chapter":
            assert source["source_scope_exclusions"] == [{"selector": "book.introduction", "reason": "outside-selected-chapter-scope"}]
            assert source["source_scope_exclusion_count"] == 1
        else:
            assert source["source_scope_exclusions"] == []
            assert source["source_scope_exclusion_count"] == 0
        tei = E.parse(str(FIXTURE / Path(case["tei_path"]).name))
        assert tei.xpath("string(//t:sourceDesc//t:ptr/@target)", namespaces={"t": TEI_NS}) == source["source_url"]
        assert not tei.xpath("//t:head", namespaces={"t": TEI_NS})
        assert "Selected native" not in "".join(tei.getroot().itertext())


def test_fixture_tei_validates_against_bundled_tei_p5_schema():
    schema = E.XMLSchema(E.parse(str(ROOT / "ocd_kernel" / "tei" / "vendor" / "xsd" / "tei_all.xsd")))
    for case in CASES:
        schema.assertValid(E.parse(str(FIXTURE / Path(case["tei_path"]).name)))


@pytest.mark.requires_local_artifacts
def test_second_process_fixture_builder_reproduces_bytes():
    builder = ARTIFACT / "03-build-commentary-fixtures.py"
    completed = subprocess.run([sys.executable, str(builder), "--check"], cwd=ROOT, capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stdout + completed.stderr


@pytest.mark.parametrize(
    "field",
    [
        "schema_version", "receipt_version", "mapping_version", "assembler_version", "category", "identity", "authority", "master_sha256", "scope_id", "source_binding", "output_sha256", "row_count", "anchors", "inventory", "references", "warnings", "exclusions", "unsupported", "schema_sha256", "common_schema_sha256", "policy_sha256", "independent_check",
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
        receipt[field] = {"master": "forged"}
    elif field == "scope_id":
        receipt[field] = "forged-scope"
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
        receipt[field] = []
    elif field == "unsupported":
        receipt[field] = [{"path": "/forged", "reason": "forged"}]
    elif field == "independent_check":
        receipt[field] = {"status": "passed", "errors": []}
    assert verify(FIXTURE / Path(case["tei_path"]).name, result["rows"], receipt, **_context(case))


def test_independent_check_status_cannot_be_spoofed():
    case = CASES[0]
    result = _result(case)
    receipt = copy.deepcopy(result["receipt"])
    receipt["independent_check"] = {"status": "passed", "errors": []}
    assert verify(FIXTURE / Path(case["tei_path"]).name, result["rows"], receipt, **_context(case))


@pytest.mark.parametrize("mutation", ["omit", "duplicate", "reverse", "text", "record_id", "sequence", "category", "language", "representation_revision", "provenance", "scope", "locator", "source_id", "notes", "references", "extra"])
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
    elif mutation == "scope":
        rows[0]["locator"]["scope"]["raw"] = "Bible:Invented.1.1"
    elif mutation == "locator":
        rows[0]["locator"]["source_order"] = 99
    elif mutation == "source_id":
        rows[0]["locator"]["source_id"] = "invented-source-id"
    elif mutation == "notes":
        rows[0]["notes"] = [{"text": "forged", "place": "foot", "label": "x"}]
    elif mutation == "references":
        rows[0]["references"] = [{"label": "forged", "resolution": "external", "target_record_id": None, "target_note": None, "source_note": None}]
    elif mutation == "extra":
        rows[0]["forged"] = True
    receipt = _forged_receipt_for_rows(result, rows)
    assert verify(FIXTURE / Path(case["tei_path"]).name, rows, receipt, **_context(case))


@pytest.mark.parametrize(
    "change",
    ["attribute", "loose", "duplicate-id", "namespace", "doctype", "bad-target", "missing-retained", "text-structure", "root-attribute", "comment", "prolog-pi", "epilog-pi", "empty", "detached-ref"],
)
def test_unsupported_or_unbound_source_fails_both_routes(change, tmp_path):
    case = CASES[0]
    source_path = FIXTURE / Path(case["tei_path"]).name
    tree = E.parse(str(source_path))
    ns = {"t": TEI_NS}
    selection = tree.xpath("//t:body/t:div[@type='selection']", namespaces=ns)[0]
    selected_unit = selection.xpath("./t:div[@type='commentary-unit']", namespaces=ns)[0]
    selected_ref = selected_unit.xpath(".//t:ref", namespaces=ns)[0]
    if change == "attribute":
        selected_unit.set("ana", "invented")
    elif change == "loose":
        selection.text = "Unmapped words"
    elif change == "duplicate-id":
        outside = tree.xpath("//t:body/t:div[@type='outside-scope']/t:div", namespaces=ns)[0]
        outside.set(f"{{{XML_NS}}}id", selected_unit.get(f"{{{XML_NS}}}id"))
    elif change == "namespace":
        selected_unit.tag = "{urn:wrong}div"
    elif change == "doctype":
        raw = b'<!DOCTYPE TEI [<!ENTITY x "danger">]>' + E.tostring(tree, encoding="utf-8")
    elif change == "bad-target":
        selected_ref.set("target", "Bible:ZEP.1.2 Bible:ZEP.1.3")
    elif change == "missing-retained":
        idno = tree.xpath("//t:sourceDesc//t:idno[@type='sha256']", namespaces=ns)[0]
        idno.getparent().remove(idno)
    elif change == "text-structure":
        E.SubElement(selected_unit, f"{{{TEI_NS}}}table")
    elif change == "root-attribute":
        tree.getroot().set("ana", "invented")
    elif change == "comment":
        raw = E.tostring(tree, encoding="utf-8").replace(b"<text", b"<!-- forged --> <text", 1)
    elif change == "prolog-pi":
        raw = b"<?forged instruction?>" + E.tostring(tree, encoding="utf-8")
    elif change == "epilog-pi":
        raw = E.tostring(tree, encoding="utf-8") + b"<?forged instruction?>"
    elif change == "empty":
        selected_ref.tail = None
    elif change == "detached-ref":
        selected_ref.getparent().remove(selected_ref)
    if change not in {"doctype", "comment", "prolog-pi", "epilog-pi"}:
        raw = E.tostring(tree, encoding="utf-8")
    path = tmp_path / "bad-commentary.tei.xml"
    path.write_bytes(raw)
    with pytest.raises(PipelineError):
        project(path, **_context(case))
    result = _result(case)
    assert verify(path, result, **_context(case))


def test_checker_has_no_producer_dependency(monkeypatch):
    case = CASES[0]
    result = _result(case)
    import ocd_kernel.projection.categories.commentary as module

    monkeypatch.setattr(module, "project_commentary_document", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("producer called")))
    assert verify(FIXTURE / Path(case["tei_path"]).name, result["rows"], result["receipt"], **_context(case)) == []


def test_missing_receipt_and_accepted_wrapper_scope_are_closed():
    case = CASES[0]
    result = _result(case)
    assert verify(FIXTURE / Path(case["tei_path"]).name, result["rows"], None, **_context(case))
    assert "scope_id" not in inspect.signature(project_accepted_commentary).parameters

@pytest.mark.parametrize('namespace', ['urn:forged', XML_NS])
def test_foreign_attribute_cannot_alias_allowed_name(namespace, tmp_path):
    case = CASES[0]
    tree = E.parse(str(FIXTURE / Path(case['tei_path']).name))
    ref = tree.xpath('//t:ref', namespaces={'t': TEI_NS})[0]
    ref.set(f'{{{namespace}}}type', 'scripture')
    path = tmp_path / 'attribute-namespace.xml'
    path.write_bytes(E.tostring(tree))
    with pytest.raises(PipelineError, match='attribute namespace'):
        project(path, **_context(case))
    errors = verify(path, [], {}, **_context(case))
    assert any('attribute namespace' in error for error in errors), errors


def test_generated_xml_anchors_are_private():
    for case in CASES:
        path = FIXTURE / Path(case['tei_path']).name
        tree = E.parse(str(path))
        raw_ids = tree.xpath('//@xml:id', namespaces={'xml': XML_NS})
        result = _result(case)
        assert all('source_id' not in row['locator'] for row in result['rows'])
        assert all(row['locator']['divisions'] == [] for row in result['rows'])
        public = json.dumps(result['rows'], ensure_ascii=False)
        assert not any('"' + value + '"' in public for value in raw_ids)
        assert verify(path, result['rows'], result['receipt'], **_context(case)) == []


def test_administrative_selection_cannot_hide_a_source_heading(tmp_path):
    case = CASES[0]
    tree = E.parse(str(FIXTURE / Path(case['tei_path']).name))
    selection = tree.xpath('//t:div[@type="selection"]', namespaces={'t': TEI_NS})[0]
    E.SubElement(selection, f'{{{TEI_NS}}}head').text = 'A source heading must not disappear'
    path = tmp_path / 'selection-heading.xml'
    path.write_bytes(E.tostring(tree))
    with pytest.raises(PipelineError, match='administrative wrapper'):
        project(path, **_context(case))
    errors = verify(path, [], {}, **_context(case))
    assert any('administrative wrapper' in error for error in errors), errors


@pytest.mark.parametrize('attribute', ['n', 'head'])
def test_administrative_outside_scope_sibling_cannot_hide_source_structure(attribute, tmp_path):
    case = CASES[0]
    tree = E.parse(str(FIXTURE / Path(case['tei_path']).name))
    outside = tree.xpath('//t:div[@type="outside-scope"]', namespaces={'t': TEI_NS})[0]
    if attribute == 'n':
        outside.set('n', '1')
    else:
        E.SubElement(outside, f'{{{TEI_NS}}}head').text = 'A source heading must not disappear'
    path = tmp_path / f'outside-{attribute}.xml'
    path.write_bytes(E.tostring(tree, encoding='utf-8'))
    with pytest.raises(PipelineError, match='administrative wrapper'):
        project(path, **_context(case))
    errors = verify(path, [], {}, **_context(case))
    assert any('administrative wrapper' in error for error in errors), errors


@pytest.mark.parametrize('mutation,reason', [('sourceDesc', 'sourceDesc'), ('ptr', 'source ptr')])
def test_duplicate_source_container_or_pointer_rejected(mutation, reason, tmp_path):
    case = CASES[0]
    tree = E.parse(str(FIXTURE / Path(case['tei_path']).name))
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


def test_commentary_schema_rejects_private_source_id_locator():
    import ocd_kernel.projection.categories.commentary as module

    row = copy.deepcopy(_result(CASES[0])['rows'][0])
    row['locator']['source_id'] = 'private-xml-id'
    errors = list(module._validator().iter_errors(row))
    assert any('source_id' in error.message or 'source_id' in str(error.json_path) for error in errors), errors


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


def _accepted_commentary_fixture(tmp_path_factory, *, entry_attribution=False, explicit_target=None, introduction=False):
    """Build a temporary accepted handoff from the real Adam Clarke fixture."""

    from ocd_kernel.tei.acceptance import build_acceptance_record, make_file_binding, write_acceptance

    case = CASES[0]
    source = _source(case)
    source['identity']['work_id'] = 'fixture-' + source['identity']['work_id']
    raw_path = ROOT / source['source_path']
    raw = raw_path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == source['source_sha256']
    scope_decl = 'selected native units: ' + '; '.join(source['source_selector']['selected_selectors'])
    identity = {**source['identity'], 'acquisition_id': 'fixture-commentary-accepted'}
    base = tmp_path_factory.mktemp('bc')
    edition_root = base / 'library' / 'works' / identity['work_id'] / 'forms' / identity['textual_form_id'] / 'editions' / identity['edition_id']
    edition_root.mkdir(parents=True)
    work_path = base / 'library' / 'works' / identity['work_id'] / 'work.json'
    _write_json(work_path, {
        'schema_version': '2.0',
        'work_id': identity['work_id'],
        'title': source['edition_title'],
        'evidence': ['fixture acceptance simulation'],
        'textual_forms': [{
            'textual_form_id': identity['textual_form_id'],
            'editions': [{
                'edition_id': identity['edition_id'],
                'title': source['edition_title'],
                'language': 'en',
                'category': 'commentary',
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
    retained.write_bytes((FIXTURE / f"source-{case['fixture_id']}.json").read_bytes())
    retained_hash = hashlib.sha256(retained.read_bytes()).hexdigest()
    included = {
        'path': 'retained/source.json',
        'position': 1,
        'bytes': retained.stat().st_size,
        'sha256': retained_hash,
        'scope': scope_decl,
    }
    acquisition_url = 'https://example.invalid/ocd-fixture/commentary-adam-clarke'
    acquisition = {
        'schema_version': '2.0',
        'acquisition_id': identity['acquisition_id'],
        'edition_id': identity['edition_id'],
        'provider': 'offline fixture source',
        'url': acquisition_url,
        'source_path': source['source_path'],
        'source_bytes': len(raw),
        'source_sha256': source['source_sha256'],
        'source_scope': scope_decl,
        'retained_files': [{
            key: included[key] for key in ('path', 'bytes', 'sha256', 'scope')
        } | {'media_type': 'application/json'}],
        'route': 'born-digital',
    }
    acquisition_path = edition_root / 'acquisitions' / f"{identity['acquisition_id']}.json"
    _write_json(acquisition_path, acquisition)

    tree = E.parse(str(FIXTURE / Path(case['tei_path']).name))
    ns = {'t': TEI_NS}
    body = tree.xpath('//t:body', namespaces=ns)[0]
    for outside in body.xpath('./t:div[@type="outside-scope"]', namespaces=ns):
        body.remove(outside)
    header = tree.xpath('/t:TEI/t:teiHeader', namespaces=ns)[0]
    bibl = tree.xpath('//t:sourceDesc/t:bibl', namespaces=ns)[0]
    ptr = bibl.xpath('./t:ptr', namespaces=ns)[0]
    ptr.set('target', acquisition_url)
    _set_header_idno(bibl, 'sha256', retained_hash)
    _set_header_idno(bibl, 'source_sha256', source['source_sha256'])
    _set_header_idno(bibl, 'source_bytes', str(len(raw)))
    _set_header_idno(bibl, 'work_id', identity['work_id'])
    _set_header_idno(bibl, 'acquisition_id', identity['acquisition_id'])
    _set_header_note(bibl, 'source-location', source['source_path'])
    _set_header_note(bibl, 'source-scope', scope_decl)
    revision = source['representation_revision']
    revision_desc = header.find(f'{{{TEI_NS}}}revisionDesc')
    if revision_desc is None:
        revision_desc = E.SubElement(header, f'{{{TEI_NS}}}revisionDesc')
    changes = [change for change in revision_desc if E.QName(change).localname == 'change']
    if changes:
        change = changes[0]
        for duplicate in changes[1:]:
            revision_desc.remove(duplicate)
    else:
        change = E.SubElement(revision_desc, f'{{{TEI_NS}}}change')
    change.set('when', '2026-09-08')
    change.set(f'{{{XML_NS}}}id', revision)
    change.text = 'Source-bound PIPE-007B fixture.'
    if explicit_target is not None:
        units = body.xpath('.//t:div[@type="commentary-unit" or @type="commentary" or @type="annotation" or @type="entry"]', namespaces=ns)
        assert units
        for key in ('scope', 'target', 'osisRef', 'cRef', 'corresp'):
            units[0].attrib.pop(key, None)
        units[0].set('scope', explicit_target)
        E.SubElement(units[0], '{'+TEI_NS+'}label', type='scripture-reference').text = 'John 3:16a–4:2b'
        book_label = E.SubElement(units[0], '{'+TEI_NS+'}label', type='scripture-book')
        book_label.text = 'John'
        book_label.set('{'+XML_NS+'}lang', 'en')
        if introduction:
            units[0].set('subtype', 'introduction')
            change.text = 'Synthetic introduction-role fixture for pipeline verification.'
    elif introduction:
        raise ValueError('introduction fixture requires an explicit target')
    if entry_attribution:
        units = body.xpath('.//t:div[@type="commentary-unit" or @type="commentary" or @type="annotation" or @type="entry"]', namespaces=ns)
        assert units
        note = E.SubElement(units[0], '{'+TEI_NS+'}note', type='source-attribution')
        for role, text in [('source-title', 'Synthetic source work'), ('attribution-note', 'Synthetic author context')]:
            E.SubElement(note, '{'+TEI_NS+'}seg', type=role).text = text
        E.SubElement(note, '{'+TEI_NS+'}ref', type='source-url', target='https://example.org/commentary-entry').text = 'Entry source'
        paragraph = E.SubElement(units[0], '{'+TEI_NS+'}p')
        E.SubElement(paragraph, '{'+TEI_NS+'}ref', type='scripture-cross-reference', target='Bible:Gen.1.26-2.3').text = 'Genesis 1:26–2:3'
    candidate = base / 'candidate.tei.xml'
    candidate.write_bytes(E.tostring(tree, encoding='utf-8', xml_declaration=True))
    candidate_binding = make_file_binding(base, candidate)
    scope = {
        'kind': 'member',
        'declared': scope_decl,
        'expected_members': [{'path': included['path'], 'position': 1}],
        'included_members': [included],
        'excluded_members': [],
    }
    source_obj = {
        'source_path': source['source_path'],
        'source_sha256': source['source_sha256'],
        'source_bytes': len(raw),
        'source_scope': scope_decl,
    }
    accounting = {
        'contract': 'ocd-source-accounting-v1',
        'identity': identity,
        'source': source_obj,
        'source_sha256': source['source_sha256'],
        'source_bytes': len(raw),
        'scope': scope_decl,
        'accepted_scope': {'kind': 'member', 'declared': scope_decl},
        'expected_members': scope['expected_members'],
        'included_members': scope['included_members'],
        'excluded_members': [],
        'missing_members': [],
        'unknown_members': [],
    }
    source_accounting_path = base / 'evidence' / 'source-accounting.json'
    _write_json(source_accounting_path, accounting)
    technical = {
        'producer': {'id': 'producer:commentary-fixture'},
        'checker': {'id': 'checker:commentary-fixture'},
        'shared_assumptions': ['Synthetic acceptance evidence is fixture-only.'],
        'independent_corroboration': 'Source-derived commentary fixture checks remain separate.',
    }
    for name in ('validation', 'accounting', 'fidelity', 'reproducibility', 'schema', 'closure'):
        proof_path = base / 'evidence' / f'{name}.json'
        proof = {
            'contract': f'ocd-tei-{name}-v1',
            'identity': identity,
            'source': source_obj,
            'candidate': candidate_binding,
            'scope': scope_decl,
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
            proof['accepted_scope'] = {'kind': 'member', 'declared': scope_decl}
        _write_json(proof_path, proof)
        technical[name] = {
            'path': proof_path,
            'status': 'pass',
            'command': 'simulated-accepted-category-fixture',
            'exit_code': 0,
        }
    coverage = {
        'status': 'partial',
        'declared': scope_decl,
        'reached': [scope_decl],
        'inspected': [scope_decl],
        'unreviewed': ['human acceptance'],
    }
    review = {
        'reviewer': 'agent:commentary-fixture',
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
        'scope': scope_decl,
        **review,
    })
    decision = {
        'source_local_disposition': 'Offline fixture simulation only',
        'blockers': [],
        'agent_assessment': {
            'status': 'accepted',
            'actor': 'agent:commentary-fixture',
            'assessed_at': '2026-09-08T00:00:00Z',
            'supported_scope': scope_decl,
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
        representation_revision={'id': revision, 'date': '2026-09-08', 'note': change.text},
        decision=decision,
        missing_members=[],
        unknown_members=[],
    )
    acceptance_path = edition_root / 'acceptance.json'
    write_acceptance(acceptance_path, record)
    return base, acceptance_path, case, source


@pytest.mark.requires_local_artifacts
def test_accepted_commentary_requires_promotion_binds_authority_and_is_independent(tmp_path_factory, monkeypatch):
    from ocd_kernel.lib.path_io import io_path
    from ocd_kernel.tei.acceptance import promote_accepted_master

    root, acceptance_path, case, source = _accepted_commentary_fixture(tmp_path_factory)
    pending_errors = verify_accepted_commentary(root, acceptance_path=acceptance_path, rows=[], receipt={})
    assert any('promoted' in error for error in pending_errors), pending_errors
    with pytest.raises(PipelineError, match='promoted'):
        project_accepted_commentary(root, acceptance_path=acceptance_path)

    promoted = promote_accepted_master(
        root,
        acceptance_path=acceptance_path,
        destination=tmp_path_factory.mktemp('bc') / 'out',
    )
    output = project_accepted_commentary(
        promoted.destination_root,
        acceptance_path=promoted.acceptance_path,
    )
    assert len(output['rows']) == len(source['selected_units']) == 3
    assert [row['text'] for row in output['rows']] == [item['normalized_text'] for item in source['selected_units']]
    authority = output['receipt']['authority']
    assert set(authority) == {'acceptance', 'work', 'master', 'acquisition'}
    assert all(set(binding) == {'path', 'sha256'} for binding in authority.values())
    assert verify_accepted_commentary(
        promoted.destination_root,
        acceptance_path=promoted.acceptance_path,
        rows=output['rows'],
        receipt=output['receipt'],
    ) == []

    prefixed = project_accepted_commentary(
        io_path(promoted.destination_root),
        acceptance_path=io_path(promoted.acceptance_path),
    )
    assert prefixed == output
    assert verify_accepted_commentary(
        io_path(promoted.destination_root),
        acceptance_path=io_path(promoted.acceptance_path),
        rows=output['rows'],
        receipt=output['receipt'],
    ) == []

    import ocd_kernel.projection.categories.commentary as module
    metadata = module._accepted_metadata(promoted.destination_root, promoted.acceptance_path)
    with pytest.raises(PipelineError, match='outside root'):
        module._accepted_authority(
            metadata['root'],
            acceptance_path=metadata['acceptance_path'],
            work_path=ROOT / 'AGENTS.md',
            master_path=metadata['master_path'],
            acquisition_path=metadata['acquisition_path'],
        )

    monkeypatch.setattr(
        module,
        'project_commentary_document',
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('producer called')),
    )
    assert verify_accepted_commentary(
        promoted.destination_root,
        acceptance_path=promoted.acceptance_path,
        rows=output['rows'],
        receipt=output['receipt'],
    ) == []
    forged = copy.deepcopy(output['receipt'])
    forged['authority']['master']['sha256'] = '0' * 64
    assert verify_accepted_commentary(
        promoted.destination_root,
        acceptance_path=promoted.acceptance_path,
        rows=output['rows'],
        receipt=forged,
    )

    work_path = promoted.destination_root / 'library' / 'works' / source['identity']['work_id'] / 'work.json'
    work = json.loads(work_path.read_text(encoding='utf-8'))
    work['textual_forms'][0]['editions'][0]['category'] = 'bible'
    _write_json(work_path, work)
    category_errors = verify_accepted_commentary(
        promoted.destination_root,
        acceptance_path=promoted.acceptance_path,
        rows=output['rows'],
        receipt=output['receipt'],
    )
    assert any('commentary category' in error for error in category_errors), category_errors
