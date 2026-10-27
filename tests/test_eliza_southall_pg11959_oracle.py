"""Challenge the independent PG11959 source oracle with readable-body mutations."""

from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path
from copy import deepcopy
from hashlib import sha256
import json
from tests.runtime_candidate_baselines import current_runtime_baseline

from lxml import etree

from build.tei.eliza_southall_pg11959_oracle import _oracle
from build.tools.stage_eliza_southall_pg11959_acceptance import CANDIDATE, MANIFEST, ROOT


TEI = "http://www.tei-c.org/ns/1.0"
RUNTIME_MANIFEST = Path("tests/fixtures/reconstruction-runtime/eliza-southall-pg11959-current-installer.source-manifest.json")
RUNTIME_SHA = 'e5680023b58e10b0d52365a46f086100269526973995557ef6e8360533acd8cd'
RETAINED_SHA = "b02792d55170a43ff43ba31a018ba60034aa42d3a1212c24f864d576e285b65b"


def test_oracle_rejects_changed_text_and_source_style(tmp_path: Path) -> None:
    assert sha256((ROOT / RUNTIME_MANIFEST).read_bytes()).hexdigest() == RUNTIME_SHA
    manifest, package = current_runtime_baseline(
        root=ROOT, original_manifest=MANIFEST, runtime_manifest=RUNTIME_MANIFEST,
        retained_package=CANDIDATE, retained_sha256=RETAINED_SHA,
        destination=tmp_path / "current-source-candidate")
    assert _oracle(manifest, package)["status"] == "pass"
    original = package.member_bytes("content.tei.xml")

    for change in ("wording", "style"):
        document = etree.fromstring(original)
        if change == "wording":
            target = document.xpath(".//t:div[@type='complete-html-body']//t:head", namespaces={"t": TEI})[0]
            target.text = "Changed " + (target.text or "")
        else:
            target = document.xpath(".//t:head[contains(@rend, 'margin-top')]", namespaces={"t": TEI})[0]
            target.set("rend", "lost-source-style")
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
