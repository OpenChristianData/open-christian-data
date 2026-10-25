"""Challenge the independent PG66953 source oracle with readable-body mutations."""

from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path
from copy import deepcopy
from hashlib import sha256
import json
from tests.runtime_candidate_baselines import current_runtime_baseline

from lxml import etree

from build.tei.jarena_lee_pg66953_oracle import _oracle
from build.tools.stage_jarena_lee_pg66953_acceptance import CANDIDATE, MANIFEST, ROOT


TEI = "http://www.tei-c.org/ns/1.0"
RUNTIME_MANIFEST = Path("tests/fixtures/reconstruction-runtime/jarena-lee-pg66953-current-installer.source-manifest.json")
RUNTIME_SHA = 'd93bd4b73120b533c2d2184227e73221cf291d002786190ba41428a23ad918a2'
RETAINED_SHA = "dbe35ba8a3e632126b25bb7420b807f9cf48ec80c8adf52570bc744aaf2f78d3"


def test_oracle_rejects_changed_text_image_and_caption_link(tmp_path: Path) -> None:
    assert sha256((ROOT / RUNTIME_MANIFEST).read_bytes()).hexdigest() == RUNTIME_SHA
    manifest, package = current_runtime_baseline(
        root=ROOT, original_manifest=MANIFEST, runtime_manifest=RUNTIME_MANIFEST,
        retained_package=CANDIDATE, retained_sha256=RETAINED_SHA,
        destination=tmp_path / "current-source-candidate")
    assert _oracle(manifest, package)["status"] == "pass"
    original = package.member_bytes("content.tei.xml")

    for change in ("wording", "image", "caption-link"):
        document = etree.fromstring(original)
        if change == "wording":
            target = document.xpath(".//t:div[@type='complete-html-body']//t:head", namespaces={"t": TEI})[0]
            target.text = "Changed " + (target.text or "")
        elif change == "image":
            target = document.xpath(".//t:figure/t:graphic", namespaces={"t": TEI})[0]
            target.set("url", "raw/gutenberg/66953/html/images/wrong.jpg")
        else:
            target = document.xpath(".//t:div[@type='source-figure']", namespaces={"t": TEI})[0]
            target.set("corresp", "#wrong-caption")
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
