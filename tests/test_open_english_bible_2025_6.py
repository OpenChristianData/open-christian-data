"""Focused source-to-TEI regressions for L605 Open English Bible 2025.6."""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest
from lxml import etree

from ocd_kernel.reconstruction.contract import SourceManifest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "sources/manifest-acquisitions/open-english-bible-2025-6/reconstruction-source-manifest.json"
TEI = "http://www.tei-c.org/ns/1.0"
NS = {"tei": TEI}


def _load_module(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def candidate_material():
    manifest = SourceManifest.load(MANIFEST_PATH, repository_root=ROOT)
    converter = _load_module("oeb_l605_converter_test", "build/tei/open_english_bible_2025_6.py")
    oracle = _load_module("oeb_l605_oracle_test", "build/tei/open_english_bible_2025_6_oracle.py")
    output = converter._convert(manifest)
    return manifest, oracle, output["content.tei.xml"]


def test_candidate_has_one_tei_root_and_passes_source_oracle(candidate_material):
    manifest, oracle, content = candidate_material
    root = etree.fromstring(content)
    assert root.tag == f"{{{TEI}}}TEI"
    assert len(root.xpath(".//tei:TEI", namespaces=NS)) == 0
    assert [node.get("n") for node in root.xpath("./tei:text/tei:group/tei:text", namespaces=NS)] == ["US", "Cth"]
    assert oracle.check_xml(manifest, content) == []


def test_oracle_rejects_multiple_tei_roots(candidate_material):
    manifest, oracle, content = candidate_material
    original = etree.fromstring(content)
    second = copy.deepcopy(original)
    xml_id = "{http://www.w3.org/XML/1998/namespace}id"
    for node in second.iter():
        if node.get(xml_id):
            node.set(xml_id, node.get(xml_id) + "-copy")
    corpus = etree.Element(f"{{{TEI}}}teiCorpus", nsmap={None: TEI})
    corpus.extend([original, second])
    mutated = etree.tostring(corpus, encoding="UTF-8", xml_declaration=True)
    findings = oracle.check_xml(manifest, mutated)
    assert any("exactly one document-level TEI root" in item for item in findings)


def test_oracle_rejects_witness_label_mutation(candidate_material):
    manifest, oracle, content = candidate_material
    root = etree.fromstring(content)
    branches = root.xpath("./tei:text/tei:group/tei:text", namespaces=NS)
    assert len(branches) == 2
    branches[1].set("n", "US")
    mutated = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
    findings = oracle.check_xml(manifest, mutated)
    assert any("variant labels or order differ" in item for item in findings)


def test_oracle_rejects_witness_text_mutation(candidate_material):
    manifest, oracle, content = candidate_material
    root = etree.fromstring(content)
    verses = root.xpath("./tei:text/tei:group/tei:text[@n='Cth']//tei:ab[@type='verse']", namespaces=NS)
    assert verses and (verses[0].text or "").strip()
    verses[0].text = "X" + (verses[0].text or "")
    mutated = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
    findings = oracle.check_xml(manifest, mutated)
    assert any("wording or inline marker order differs" in item for item in findings)
