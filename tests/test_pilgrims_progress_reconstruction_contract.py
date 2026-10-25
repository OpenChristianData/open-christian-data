from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from lxml import etree
import pytest

from build.tei.pilgrims_progress_oracle import _closure, _oracle
import build.tei.pilgrims_progress_oracle as bunyan_oracle
from build.tei.pilgrims_progress_reconstruction import _convert
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, reconstruct, validate


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'tests/fixtures/reconstruction-runtime/pilgrims-progress.source-manifest.json'
TEI = "http://www.tei-c.org/ns/1.0"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


@pytest.fixture(scope="module")
def source_manifest() -> SourceManifest:
    return SourceManifest.load(MANIFEST, repository_root=ROOT)


@pytest.fixture(scope="module")
def candidate(source_manifest: SourceManifest, tmp_path_factory: pytest.TempPathFactory) -> CandidatePackage:
    return reconstruct(source_manifest, tmp_path_factory.mktemp("bunyan-candidate") / "package", _convert)


def _reseal(candidate: CandidatePackage, root: Path, name: str, content: bytes) -> CandidatePackage:
    output = root / "mutated"
    output.mkdir()
    for member in candidate.member_names:
        shutil.copy2(candidate.path / member, output / member)
    (output / name).write_bytes(content)
    manifest = json.loads((output / "manifest.json").read_bytes())
    for member in manifest["members"]:
        if member["name"] == name:
            member["bytes"] = len(content)
            member["sha256"] = _sha(content)
    (output / "manifest.json").write_bytes(_canonical(manifest))
    return CandidatePackage.load(output)


def test_exact_retained_checkout_and_nonaccepted_package(source_manifest: SourceManifest, candidate: CandidatePackage) -> None:
    profile = json.loads(source_manifest.authority_path("reconstruction-profile").read_bytes())
    assert profile["source_scope"] == {**profile["source_scope"], "commit":"37b799fba3e61db5306584a8064b45282af08c19", "tree":"74cb0e78da9cb29c38b0463d03036471358799e6", "member_count":26, "bytes":6028743}
    assert candidate.member_names == ("README.source.md", "content.tei.xml", "manifest.json", "provenance.json", "source-accountability.json", "unresolved.jsonl")
    assert candidate.manifest["status"] == "nonaccepted"
    assert validate(source_manifest, candidate, _oracle).status == "pass"


def test_complete_source_and_feature_accounting(candidate: CandidatePackage) -> None:
    value = json.loads(candidate.member_bytes("source-accountability.json"))
    assert (value["xml_member_count"], value["non_xml_member_count"]) == (19, 7)
    assert (value["xml_observation_count"], value["element_count"], value["attribute_count"], value["text_count"]) == (31735, 12091, 9241, 10403)
    assert (value["represented_count"], value["evidence_only_count"], value["omitted_count"], value["duplicate_count"]) == (30783, 952, 0, 0)
    assert value["ordered_dispositions_sha256"] == "707617f01555273f5613f21f76eef80790aee12e5b691b998183e8917060e381"
    assert {item["disposition"] for item in value["observations"]} == {"represented", "evidence-only"}
    features = value["feature_inventory"]
    assert (features["note_references"], features["note_bodies"], features["note_backlinks"], features["visible_note_labels"]) == (1010, 1010, 1010, 1010)
    assert (features["lists"], features["list_items"], features["attributed_notes"], features["unattributed_notes"], features["cites"], features["distinct_cite_strings"]) == (2, 1026, 653, 357, 771, 156)
    assert (features["verse_groups"], features["poems"], features["verses"], features["songs"], features["stanzas"], features["verse_lines"], features["indentation_spans"]) == (95, 10, 65, 20, 171, 1045, 21)
    assert features["abbr_eoc_renditions"] == 14
    assert (features["body_verse_groups"], features["front_verse_groups"], features["back_verse_groups"], features["note_verse_groups"]) == (45, 10, 1, 39)
    bindings = value["semantic_bindings"]
    assert (len(bindings["notes"]), len(bindings["verse"]), len(bindings["toc"]), len(bindings["image_strings"]), len(bindings["cite_occurrences"]), len(bindings["distinct_cite_strings"])) == (1010, 95, 13, 18, 771, 156)
    assert [row["nav_type"] for row in bindings["toc"]].count("toc") == 11
    assert [row["nav_type"] for row in bindings["toc"]].count("landmarks") == 2


def test_spine_order_note_graph_poetry_and_rights(candidate: CandidatePackage) -> None:
    root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    ns = {"t": TEI}
    divs = root.xpath("/t:TEI/t:text/t:body/t:div", namespaces=ns)
    assert [node.get("{http://www.w3.org/XML/1998/namespace}id") for node in divs] == ["titlepage","imprint","foreword","halftitlepage","preface-1","part-1","preface-2","part-2","endnotes","colophon","uncopyright"]
    assert [node.get("ana") for node in divs] == ["#frontmatter"] * 5 + ["#bodymatter", "#frontmatter", "#bodymatter"] + ["#backmatter"] * 3
    assert len(root.xpath("//t:ref[@type='note']", namespaces=ns)) == 1010
    assert len(root.xpath("//t:ref[@type='backlink']", namespaces=ns)) == 1010
    assert len(root.xpath("//t:list", namespaces=ns)) == 2
    assert len(root.xpath("//t:item", namespaces=ns)) == 1026
    assert len(root.xpath("//t:lg[@type='stanza']", namespaces=ns)) == 171
    assert len(root.xpath("//t:l", namespaces=ns)) == 1045
    assert len(root.xpath("//t:seg[starts-with(@rend,'i')]", namespaces=ns)) == 21
    assert len(root.xpath("//t:abbr[@rend='eoc']", namespaces=ns)) == 14
    readme = candidate.member_bytes("README.source.md")
    assert b"CC0" in readme and b"United States public domain" in readme and b"other countries" in readme and b"nonaccepted" in readme and b"human acceptance" in readme


def test_same_process_and_fresh_process_determinism(source_manifest: SourceManifest, candidate: CandidatePackage, tmp_path: Path) -> None:
    second = reconstruct(source_manifest, tmp_path / "second", _convert)
    assert second.sha256 == candidate.sha256
    script = """
from pathlib import Path
import sys
from ocd_kernel.reconstruction.contract import SourceManifest, reconstruct
from build.tei.pilgrims_progress_reconstruction import _convert
root=Path(sys.argv[1]); manifest=SourceManifest.load(root/sys.argv[2],repository_root=root)
print(reconstruct(manifest,Path(sys.argv[3]),_convert).sha256)
"""
    result = subprocess.run([sys.executable, "-c", script, str(ROOT), MANIFEST.relative_to(ROOT).as_posix(), str(tmp_path / "fresh")], check=True, capture_output=True, text=True, cwd=ROOT)
    assert result.stdout.strip() == candidate.sha256


def _mutate(candidate: CandidatePackage, tmp_path: Path, mutation: str) -> CandidatePackage:
    if mutation in {"accountability-omission", "accountability-duplication", "accountability-collapse", "toc-swap", "image-string-swap", "cite-string-swap", "metadata-claim-invention"}:
        value = json.loads(candidate.member_bytes("source-accountability.json"))
        if mutation == "accountability-omission":
            value["observations"].pop(100)
        elif mutation == "accountability-duplication":
            value["observations"][100] = value["observations"][99]
        else:
            if mutation == "accountability-collapse":
                for item in value["observations"]:
                    item["disposition"] = "evidence-only"
                value["represented_count"] = 0
                value["evidence_only_count"] = 31735
            elif mutation == "toc-swap":
                value["semantic_bindings"]["toc"][0]["target"], value["semantic_bindings"]["toc"][1]["target"] = value["semantic_bindings"]["toc"][1]["target"], value["semantic_bindings"]["toc"][0]["target"]
            elif mutation == "image-string-swap":
                value["semantic_bindings"]["image_strings"][0]["value"], value["semantic_bindings"]["image_strings"][1]["value"] = value["semantic_bindings"]["image_strings"][1]["value"], value["semantic_bindings"]["image_strings"][0]["value"]
            elif mutation == "cite-string-swap":
                value["semantic_bindings"]["cite_occurrences"][0]["value"], value["semantic_bindings"]["cite_occurrences"][1]["value"] = value["semantic_bindings"]["cite_occurrences"][1]["value"], value["semantic_bindings"]["cite_occurrences"][0]["value"]
            elif mutation == "metadata-claim-invention":
                value["semantic_bindings"]["metadata_claims"]["opf"]["language"] = ["invented"]
        return _reseal(candidate, tmp_path, "source-accountability.json", _canonical(value))
    if mutation == "rights-conflation":
        value = json.loads(candidate.member_bytes("provenance.json"))
        value["rights"] = {"all":"public domain"}
        return _reseal(candidate, tmp_path, "provenance.json", _canonical(value))
    if mutation == "readme-rights-conflation":
        return _reseal(candidate, tmp_path, "README.source.md", b"# Source and rights\n\nAll content is public domain worldwide and cleared for publication.\n")

    root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    ns = {"t": TEI}
    if mutation == "section-reorder":
        body = root.xpath("/t:TEI/t:text/t:body", namespaces=ns)[0]
        body.insert(0, body[1])
    elif mutation == "crossed-noteref":
        root.xpath("//t:ref[@type='note']", namespaces=ns)[0].set("target", "#note-2")
    elif mutation == "crossed-backlink":
        root.xpath("//t:ref[@type='backlink']", namespaces=ns)[0].set("target", "#noteref-2")
    elif mutation == "note-body-id-swap":
        items = root.xpath("//t:item[starts-with(@xml:id,'note-')]", namespaces={**ns, "xml":"http://www.w3.org/XML/1998/namespace"})
        key = "{http://www.w3.org/XML/1998/namespace}id"
        items[0].set(key, "note-2")
        items[1].set(key, "note-1")
    elif mutation == "note-body-corresp-swap":
        items = root.xpath("//t:item[starts-with(@xml:id,'note-')]", namespaces={**ns, "xml":"http://www.w3.org/XML/1998/namespace"})
        left, right = items[0], items[1]
        left_value, right_value = left.get("corresp"), right.get("corresp")
        left.set("corresp", right_value); right.set("corresp", left_value)
    elif mutation == "text-misattachment":
        paragraph = root.xpath("//t:div[@xml:id='part-1']/t:p", namespaces={**ns, "xml":"http://www.w3.org/XML/1998/namespace"})[0]
        paragraph.text = (paragraph.text or "") + " invented"
    elif mutation == "list-item-loss":
        item = root.xpath("//t:list/t:item", namespaces=ns)[0]
        item.getparent().remove(item)
    elif mutation == "poetry-genre":
        root.xpath("//t:lg[@type='poem']|//t:lg[@type='verse']|//t:lg[@type='song']", namespaces=ns)[0].set("type", "prose")
    elif mutation == "stanza-line-loss":
        line = root.xpath("//t:lg[@type='stanza']/t:l", namespaces=ns)[0]
        line.getparent().remove(line)
    elif mutation == "stanza-line-move":
        stanzas = root.xpath("//t:lg[@type='stanza']", namespaces=ns)
        stanzas[1].insert(0, stanzas[0][0])
    elif mutation == "indentation-loss":
        root.xpath("//t:seg[starts-with(@rend,'i')]", namespaces=ns)[0].attrib.pop("rend")
    elif mutation == "indentation-swap":
        left = root.xpath("//t:seg[@rend='i1']", namespaces=ns)[0]
        right = root.xpath("//t:seg[@rend='i2']", namespaces=ns)[0]
        left.set("rend", "i2"); right.set("rend", "i1")
    elif mutation == "abbr-eoc-omission":
        root.xpath("//t:abbr[@rend='eoc']", namespaces=ns)[0].attrib.pop("rend")
    elif mutation == "abbr-eoc-invention":
        root.xpath("//t:abbr[not(@rend)]", namespaces=ns)[0].set("rend", "eoc")
    elif mutation == "abbr-eoc-relocation":
        source = root.xpath("//t:abbr[@rend='eoc']", namespaces=ns)[0]
        destination = root.xpath("//t:abbr[not(@rend)]", namespaces=ns)[0]
        source.attrib.pop("rend"); destination.set("rend", "eoc")
    elif mutation == "carrier-swap":
        left = root.xpath("//t:hi[@rend='bold']", namespaces=ns)[0]
        right = root.xpath("//t:hi[@rend='italic']", namespaces=ns)[0]
        left.set("rend", "italic"); right.set("rend", "bold")
    elif mutation == "anchor-target-invention":
        root.xpath("//t:ref[not(@type)]", namespaces=ns)[0].set("target", "invented-target.xhtml")
    elif mutation == "anchor-target-swap":
        nodes = root.xpath("//t:ref[not(@type)]", namespaces=ns)
        left, right = nodes[0], nodes[1]
        left_value, right_value = left.get("target"), right.get("target")
        left.set("target", right_value); right.set("target", left_value)
    elif mutation == "image-url-invention":
        root.xpath("//t:figure/t:graphic", namespaces=ns)[0].set("url", "invented.svg")
    elif mutation == "image-url-swap":
        nodes = root.xpath("//t:figure/t:graphic", namespaces=ns)
        left, right = nodes[0], nodes[1]
        left_value, right_value = left.get("url"), right.get("url")
        left.set("url", right_value); right.set("url", left_value)
    elif mutation == "time-when-invention":
        root.xpath("//t:date[@when]", namespaces=ns)[0].set("when", "1900-01-01")
    elif mutation == "time-when-swap":
        nodes = root.xpath("//t:date[@when]", namespaces=ns)
        left = nodes[0]
        right = next(node for node in nodes[1:] if node.get("when") != left.get("when"))
        left_value, right_value = left.get("when"), right.get("when")
        left.set("when", right_value); right.set("when", left_value)
    elif mutation == "repeated-marker-swap":
        nodes = root.xpath("//t:abbr[normalize-space(.)='vol.']", namespaces=ns)
        left, right = nodes[0], nodes[1]
        left_value, right_value = left.get("corresp"), right.get("corresp")
        left.set("corresp", right_value); right.set("corresp", left_value)
    elif mutation == "language-misattachment":
        nodes = root.xpath("//*[@xml:lang='la']", namespaces={"xml":"http://www.w3.org/XML/1998/namespace"})
        nodes[0].attrib.pop("{http://www.w3.org/XML/1998/namespace}lang")
        root.xpath("//t:p[not(@xml:lang)]", namespaces={**ns, "xml":"http://www.w3.org/XML/1998/namespace"})[0].set("{http://www.w3.org/XML/1998/namespace}lang", "la")
    elif mutation == "image-alt":
        root.xpath("//t:figDesc", namespaces=ns)[1].text = "invented alternative"
    elif mutation == "metadata-invention":
        root.xpath("/t:TEI/t:teiHeader/t:fileDesc/t:titleStmt/t:title", namespaces=ns)[0].text = "Invented title"
    elif mutation == "tei-rights-conflation":
        root.xpath("/t:TEI/t:teiHeader/t:fileDesc/t:publicationStmt/t:availability/t:p", namespaces=ns)[0].text = "All content is public domain worldwide and cleared for publication."
    else:
        raise AssertionError(mutation)
    content = etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False)
    return _reseal(candidate, tmp_path, "content.tei.xml", content)


@pytest.mark.parametrize("mutation", [
    "accountability-omission", "accountability-duplication", "accountability-collapse",
    "section-reorder", "crossed-noteref", "crossed-backlink", "note-body-id-swap", "note-body-corresp-swap", "text-misattachment",
    "list-item-loss", "poetry-genre", "stanza-line-loss", "stanza-line-move", "indentation-loss", "indentation-swap", "abbr-eoc-omission", "abbr-eoc-invention", "abbr-eoc-relocation",
    "carrier-swap", "repeated-marker-swap", "language-misattachment", "anchor-target-invention", "anchor-target-swap",
    "image-url-invention", "image-url-swap", "time-when-invention", "time-when-swap", "image-alt", "toc-swap", "image-string-swap", "cite-string-swap",
    "metadata-invention", "metadata-claim-invention", "tei-rights-conflation", "readme-rights-conflation", "rights-conflation",
])
def test_independent_oracle_rejects_fidelity_mutations(source_manifest: SourceManifest, candidate: CandidatePackage, tmp_path: Path, mutation: str) -> None:
    with pytest.raises(ValueError):
        _oracle(source_manifest, _mutate(candidate, tmp_path, mutation))


def test_recursive_import_closures_are_bound(source_manifest: SourceManifest) -> None:
    profile = json.loads(source_manifest.authority_path("reconstruction-profile").read_bytes())
    oracle_sha, oracle_members = _closure(ROOT)
    producer_sha, producer_members = _closure(ROOT, ROOT / "build/tei/pilgrims_progress_reconstruction.py")
    assert oracle_sha == source_manifest.record["validator"]["import_closure_sha256"]
    assert producer_sha == profile["producer_import_closure_sha256"]
    forbidden = ("build/tei/se_to_tei.py", "build/tei/census.py", "build/reconstruction/")
    assert not any(str(item["path"]).startswith(forbidden) for item in oracle_members + producer_members)


@pytest.mark.parametrize("field,bad", [("commit", "0" * 40), ("tree", "1" * 40), ("tracked_members", ["invented.xhtml"])])
def test_actual_git_checkout_drift_is_rejected(monkeypatch: pytest.MonkeyPatch, source_manifest: SourceManifest, candidate: CandidatePackage, field: str, bad: object) -> None:
    actual = bunyan_oracle._git_evidence(ROOT / "raw/standard_ebooks/john-bunyan_the-pilgrims-progress")
    monkeypatch.setattr(bunyan_oracle, "_git_evidence", lambda checkout: {**actual, field: bad})
    with pytest.raises(ValueError, match="Git checkout authority"):
        _oracle(source_manifest, candidate)


def test_recursive_dependency_mutation_changes_oracle_closure(tmp_path: Path) -> None:
    expected, members = _closure(ROOT)
    for row in members:
        source = ROOT / str(row["path"])
        target = tmp_path / str(row["path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    copied_oracle = tmp_path / "build/tei/pilgrims_progress_oracle.py"
    assert _closure(tmp_path, copied_oracle)[0] == expected
    dependency = tmp_path / "ocd_kernel/reconstruction/contract.py"
    dependency.write_bytes(dependency.read_bytes() + b"\n# isolated mutation\n")
    assert _closure(tmp_path, copied_oracle)[0] != expected


def test_runtime_editable_shadow_fails_closed(tmp_path: Path) -> None:
    shadow = tmp_path / "shadow/ocd_kernel/reconstruction"
    shadow.mkdir(parents=True)
    (shadow.parent / "__init__.py").write_text("", encoding="utf-8")
    (shadow / "__init__.py").write_text("", encoding="utf-8")
    (shadow / "contract.py").write_text("raise RuntimeError('editable shadow intercepted')\n", encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(tmp_path / "shadow") + os.pathsep + str(ROOT)}
    result = subprocess.run([sys.executable, "-c", "import build.tei.pilgrims_progress_oracle"], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert "editable shadow intercepted" in result.stderr
