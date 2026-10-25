"""Challenge the independent PG50916 source oracle with readable-body mutations."""

from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path
from copy import deepcopy
from hashlib import sha256
import json
from tests.runtime_candidate_baselines import current_runtime_baseline

from lxml import etree

from build.tei.evening_incense_pg50916_oracle import _oracle
from build.tools.stage_evening_incense_pg50916_acceptance import CANDIDATE, MANIFEST, ROOT


TEI = "http://www.tei-c.org/ns/1.0"
RUNTIME_MANIFEST = Path("tests/fixtures/reconstruction-runtime/evening-incense-pg50916-current-installer.source-manifest.json")
RUNTIME_SHA = '28679337418088230b1a5c200e9c4a8b97b14520e241845f273b18283ef119ef'
RETAINED_SHA = "b80f9945c241ec7f96d8555da78b0ef0b67dd1c061545f030e948349327183a0"


def test_oracle_rejects_changed_text_and_source_class(tmp_path: Path) -> None:
    assert sha256((ROOT / RUNTIME_MANIFEST).read_bytes()).hexdigest() == RUNTIME_SHA
    manifest, package = current_runtime_baseline(
        root=ROOT, original_manifest=MANIFEST, runtime_manifest=RUNTIME_MANIFEST,
        retained_package=CANDIDATE, retained_sha256=RETAINED_SHA,
        destination=tmp_path / "current-source-candidate")
    assert _oracle(manifest, package)["status"] == "pass"
    original = package.member_bytes("content.tei.xml")

    for change in ("wording", "class"):
        document = etree.fromstring(original)
        if change == "wording":
            target = document.xpath(".//t:div[@type='complete-html-body']//t:head", namespaces={"t": TEI})[0]
            target.text = "Changed " + (target.text or "")
        else:
            target = document.xpath(".//t:seg[@rend='smcap']", namespaces={"t": TEI})[0]
            target.set("rend", "lost-source-class")
        changed = etree.tostring(document, encoding="UTF-8", xml_declaration=True)
        candidate = SimpleNamespace(
            sha256=package.sha256,
            member_bytes=lambda name: changed if name == "content.tei.xml" else package.member_bytes(name),
        )
        result = _oracle(manifest, candidate)
        assert result["status"] == "fail", change
        assert any("TEI" in finding for finding in result["findings"]), result["findings"]


def test_current_oracle_source_manifest_preserves_complete_original_record():
    original = json.loads((ROOT / MANIFEST).read_bytes())
    raw = (ROOT / RUNTIME_MANIFEST).read_bytes()
    assert sha256(raw).hexdigest() == RUNTIME_SHA
    current = json.loads(raw)
    restored = deepcopy(current)
    restored["validator"]["import_closure_sha256"] = original["validator"]["import_closure_sha256"]
    assert restored == original
