"""Source-grounded mutation checks for the Davis L332 candidate."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from lxml import etree
from tests.historical_authority_mirrors import bound_callable, prepare_historical_mirror
import pytest

from build.tei.davis_l332_ia import _convert
from build.tei.davis_l332_ia_oracle import check
from ocd_kernel.reconstruction.contract import SourceManifest, reconstruct, validate

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "sources/structured-text/davis-beginners-grammar-1923/source-manifest.json"
NS = {"t": "http://www.tei-c.org/ns/1.0"}
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


@pytest.fixture(scope="module")
def source_manifest(tmp_path_factory):
    mirror, path = prepare_historical_mirror(ROOT, tmp_path_factory.mktemp("davis-authorities") / "root", "davis")
    return SourceManifest.load(path, repository_root=mirror)


@pytest.fixture(scope="module")
def baseline(source_manifest):
    members = _convert(source_manifest)
    return members["content.tei.xml"], members["source-accountability.json"]


def _xml(data: bytes):
    return etree.fromstring(data)


def _bytes(node):
    return etree.tostring(node, encoding="UTF-8", xml_declaration=True)


def _page(tree, n: int):
    found = tree.xpath(f".//t:div[@xml:id='leaf-{n:04d}']", namespaces=NS)
    assert len(found) == 1
    return found[0]


def test_baseline_source_carriers_and_tables(baseline):
    counts = check(ROOT, *baseline)
    assert counts["pages"] == 280
    assert counts["words"] == 50411


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("drop-page", "page order"),
        ("ocr-wording", "OCR lines and wording"),
        ("facsimile", "facsimile target"),
        ("table-cell", "Abbyy table text"),
        ("account-group", "page relationship"),
    ],
)
def test_mutation_rejected_for_source_property(baseline, mutation, reason):
    tei, account = baseline
    tree = _xml(tei)
    ledger = json.loads(account)
    if mutation == "drop-page":
        page = _page(tree, 141)
        page.getparent().remove(page)
    elif mutation == "ocr-wording":
        paragraph = _page(tree, 261).xpath(".//t:div[@type='ocr-paragraph']/t:p", namespaces=NS)[0]
        paragraph.find("{http://www.tei-c.org/ns/1.0}lb").tail += " invented"
    elif mutation == "facsimile":
        _page(tree, 25).find("{http://www.tei-c.org/ns/1.0}pb").set("facs", "scan.pdf#page=26")
    elif mutation == "table-cell":
        cell = _page(tree, 141).xpath(".//t:div[@type='alternate-ocr-layout']/t:table/t:row/t:cell", namespaces=NS)[0]
        cell.find("{http://www.tei-c.org/ns/1.0}lb").tail += " invented"
    elif mutation == "account-group":
        ledger["pages"][220]["group"] = "part-i-lessons"
    changed_tei = _bytes(tree) if mutation != "account-group" else tei
    changed_account = (json.dumps(ledger, ensure_ascii=False, sort_keys=True,
                                  separators=(",", ":")) + "\n").encode("utf-8")
    assert (changed_tei, changed_account) != baseline
    with pytest.raises(ValueError, match=reason):
        check(ROOT, changed_tei, changed_account)



def test_current_bound_seam_and_original_validator_pin_remain_independent(source_manifest, tmp_path):
    original = source_manifest.path.parent / "original-source-manifest.json"
    with pytest.raises(ValueError, match="validator implementation authority drifted"):
        SourceManifest.load(original, repository_root=source_manifest.repository_root)
    converter = bound_callable(source_manifest.repository_root, source_manifest.record["converter"], "converter")
    oracle = bound_callable(source_manifest.repository_root, source_manifest.record["validator"], "validator")
    candidate = reconstruct(source_manifest, tmp_path / "candidate", converter)
    report = validate(source_manifest, candidate, oracle)
    assert report.status == "pass" and report.findings == ()
    assert candidate.manifest["status"] == "nonaccepted"
