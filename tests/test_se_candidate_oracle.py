from pathlib import Path
import hashlib
import json
import shutil

import pytest
from lxml import etree

from build.tei.se_candidate_oracle import _oracle
from build.tei.se_candidate_reconstruction import _convert
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, reconstruct, validate

ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = [
    "george-macdonald_unspoken-sermons/george-macdonald-unspoken-sermons.source-manifest.json",
    "g-k-chesterton_heretics/heretics.source-manifest.json",
    "g-k-chesterton_orthodoxy/orthodoxy.source-manifest.json",
    "g-k-chesterton_the-everlasting-man/the-everlasting-man.source-manifest.json",
]


def _runtime_manifest(relative):
    # Preserve the retained manifest; only this test selects its explicit derivative.
    cases = json.loads(
        (ROOT / "tests/fixtures/reconstruction-runtime/next-binding-se-four.json").read_bytes()
    )
    original = "sources/standard-ebooks/" + relative
    matches = [case for case in cases if case["original"] == original]
    assert len(matches) == 1
    return ROOT / matches[0]["manifest"]


@pytest.mark.parametrize("relative", MANIFESTS)
def test_retained_candidate_independent_oracle(relative, tmp_path):
    manifest = SourceManifest.load(_runtime_manifest(relative), repository_root=ROOT)
    candidate = reconstruct(manifest, tmp_path / "package", _convert)
    assert validate(manifest, candidate, _oracle).status == "pass"


@pytest.fixture(scope="module")
def mutation_baseline(tmp_path_factory):
    manifest = SourceManifest.load(_runtime_manifest(MANIFESTS[0]), repository_root=ROOT)
    candidate = reconstruct(manifest, tmp_path_factory.mktemp("se-mut") / "package", _convert)
    assert _oracle(manifest, candidate)["status"] == "pass"
    try:
        yield manifest, candidate
    finally:
        shutil.rmtree(candidate.path)


def _assert_mutation_rejected(mutation_baseline, tmp_path, mutation):
    manifest, baseline = mutation_baseline
    directory = tmp_path / "mutated"
    shutil.copytree(baseline.path, directory)
    name = "content.tei.xml"
    if mutation == "accountability":
        name = "source-accountability.json"
        accounting = json.loads((directory / name).read_bytes())
        accounting["members"][0]["reason"] = "Invented disposition"
        content = json.dumps(accounting).encode()
    else:
        tree = etree.fromstring((directory / name).read_bytes())
        ns = {"t": "http://www.tei-c.org/ns/1.0"}
        paragraphs = tree.xpath("//t:body//t:p", namespaces=ns)
        paragraph = paragraphs[0]
        if mutation == "omit":
            paragraph.getparent().remove(paragraph)
        elif mutation == "duplicate":
            paragraph.getparent().append(etree.fromstring(etree.tostring(paragraph)))
        elif mutation == "order":
            parent = tree.xpath("//t:body", namespaces=ns)[0]
            before = [node.get("{http://www.w3.org/XML/1998/namespace}id") for node in parent]
            assert len(parent) > 1
            parent.append(parent[0])
            assert before != [node.get("{http://www.w3.org/XML/1998/namespace}id") for node in parent]
        elif mutation == "wording":
            paragraph.text = "Invented sentence. " + (paragraph.text or "")
        elif mutation == "role":
            tree.xpath("//t:head[@ana]", namespaces=ns)[0].set("ana", "unrelated-role")
        elif mutation == "rendition":
            tree.xpath("//t:seg[@rend='i1']", namespaces=ns)[0].set("rend", "i2")
        elif mutation == "note-attachment":
            tree.xpath("//t:ref[@type='note']", namespaces=ns)[0].set("target", "#note-2")
        elif mutation == "local-link":
            tree.xpath("//t:ref[@target='#uncopyright']", namespaces=ns)[0].set("target", "#titlepage")
        elif mutation == "image":
            tree.xpath("//t:graphic", namespaces=ns)[0].set("url", "data:image/svg+xml;base64,SW52ZW50ZWQ=")
        elif mutation == "metadata":
            tree.xpath("//t:titleStmt/t:title", namespaces=ns)[0].text = "Different work"
        elif mutation == "container-role":
            tree.find("{http://www.tei-c.org/ns/1.0}text").set("type", "invented")
        elif mutation == "container-text":
            tree.find("{http://www.tei-c.org/ns/1.0}text").text = "Invented text outside sections."
        elif mutation == "section-tail":
            tree.xpath("//t:body/t:div", namespaces=ns)[0].tail = "Invented text between sections."
        elif mutation == "empty-container":
            etree.SubElement(tree.find("{http://www.tei-c.org/ns/1.0}text"), "{http://www.tei-c.org/ns/1.0}back")
        content = etree.tostring(tree, encoding="UTF-8", xml_declaration=True)
    (directory / name).write_bytes(content)
    record = json.loads((directory / "manifest.json").read_bytes())
    member = next(row for row in record["members"] if row["name"] == name)
    member.update(bytes=len(content), sha256=hashlib.sha256(content).hexdigest())
    (directory / "manifest.json").write_text(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    candidate = CandidatePackage.load(directory)
    candidate.verify_integrity()
    with pytest.raises(ValueError, match="SE oracle:"):
        _oracle(manifest, candidate)


@pytest.mark.parametrize("mutation", ["omit", "duplicate", "order", "wording", "role", "rendition", "note-attachment", "local-link", "image", "metadata", "accountability", "container-role", "container-text", "section-tail", "empty-container"])
def test_resealed_mutations_are_rejected(mutation_baseline, tmp_path, mutation):
    try:
        _assert_mutation_rejected(mutation_baseline, tmp_path, mutation)
    finally:
        directory = tmp_path / "mutated"
        if directory.exists():
            shutil.rmtree(directory)
