from dataclasses import replace
from pathlib import Path
import hashlib
import json
import shutil

from lxml import etree
import pytest

from build.tei.npnf2_missing_work_roots import WORK_ROOTS, load_work_root, select_work_root
from build.tei.npnf2_missing_work_reconstruction import build_work, _convert
from build.tei.npnf2_missing_work_oracle import _oracle
from ocd_kernel.reconstruction import SourceManifest, CandidatePackage, reconstruct, validate
from build.lib.tei_xsd import compiled_tei_schema


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "tests/fixtures/reconstruction-runtime"


@pytest.mark.parametrize("work_id,root_id,child_divisions", [
    ("cyril-of-jerusalem-catechetical-lectures", "ii", 27),
    ("gregory-of-nazianzus-select-orations", "iii", 27),
    ("gregory-of-nyssa-against-eunomius", "viii.i", 14),
])
def test_retained_work_binding_preserves_complete_root(work_id, root_id, child_divisions):
    tree, root = load_work_root(ROOT, work_id)
    assert root.get("id") == root_id
    assert root.getroottree().getroot() is tree.getroot()
    assert sum(child.tag.startswith("div") for child in root) == child_divisions


@pytest.mark.parametrize("mutation", ["sibling", "duplicate", "displaced", "title", "level"])
def test_wrong_work_binding_rejected(mutation):
    work_id = "gregory-of-nyssa-against-eunomius"
    tree, root = load_work_root(ROOT, work_id)
    binding = WORK_ROOTS[work_id]
    if mutation == "sibling":
        binding = replace(binding, root_path=("viii", "viii.iv"))
    elif mutation == "duplicate":
        root.getparent().append(etree.fromstring(etree.tostring(root)))
    elif mutation == "displaced":
        tree.getroot().find("ThML.body").append(root)
    elif mutation == "title":
        root.set("title", "On the Holy Trinity.")
    else:
        root.tag = "div1"
    with pytest.raises(ValueError):
        select_work_root(tree, binding)


def test_unregistered_work_is_not_silently_routed_to_sibling():
    with pytest.raises(ValueError, match="unsupported NPNF2 work"):
        load_work_root(ROOT, "basil-of-caesarea-letters")


@pytest.mark.parametrize("work_id", WORK_ROOTS)
def test_readable_selected_work_is_schema_valid_and_preserves_carriers(work_id):
    content, accounting = build_work(ROOT, work_id)
    target = etree.fromstring(content)
    schema = compiled_tei_schema(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd")
    assert schema.validate(target), str(schema.error_log)
    _, source = load_work_root(ROOT, work_id)
    ns = {"t": "http://www.tei-c.org/ns/1.0"}
    selected = target.find("t:text/t:body/t:div", ns)
    assert selected.get("subtype") == work_id
    assert len(accounting["represented_carriers"]) == sum(1 for _ in source.iter())
    assert len(selected.findall(".//t:note", ns)) == sum(n.tag == "note" for n in source.iter())
    assert len(selected.findall(".//t:row", ns)) == sum(n.tag == "tr" for n in source.iter())
    assert len(selected.findall(".//t:cell", ns)) == sum(n.tag == "td" for n in source.iter())
    assert len(selected.findall(".//t:lb", ns)) == sum(n.tag == "br" for n in source.iter())
    # Remove only generated heads before comparing full source text/tail order.
    for head in selected.findall(".//t:head", ns):
        head.getparent().remove(head)
    assert "".join(selected.itertext()) == "".join(source.itertext())


@pytest.fixture(scope="module", params=tuple(WORK_ROOTS))
def candidate_pair(request, tmp_path_factory):
    work_id = request.param
    manifest = RUNTIME / f"{work_id}.source-manifest.json"
    source = SourceManifest.load(manifest, repository_root=ROOT)
    output = tmp_path_factory.mktemp("nr")
    try:
        candidate = reconstruct(source, output / "candidate", _convert)
        yield source, candidate
    finally:
        shutil.rmtree(output)


def test_complete_packaged_work_passes_independent_oracle(candidate_pair):
    source, candidate = candidate_pair
    assert validate(source, candidate, _oracle).status == "pass"


@pytest.mark.parametrize("mutation", ["omit", "reorder", "attachment", "text", "header", "attribute", "provenance"])
def test_resealed_semantic_mutations_are_rejected(candidate_pair, tmp_path, mutation):
    source, original = candidate_pair
    destination = tmp_path / "mutant"
    shutil.copytree(original.path, destination)
    try:
        member = "provenance.json" if mutation == "provenance" else "content.tei.xml"
        path = destination / member
        if mutation == "provenance":
            record = json.loads(path.read_bytes())
            record["publication"] = True
            content = (json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
        else:
            root = etree.fromstring(path.read_bytes())
            ns = {"t": "http://www.tei-c.org/ns/1.0"}
            work = root.find("t:text/t:body/t:div", ns)
            if mutation == "omit":
                work.remove(work[-1])
            elif mutation == "reorder":
                work.insert(1, work[-1])
            elif mutation == "attachment":
                note = work.find(".//t:note", ns)
                work.find(".//t:p", ns).append(note)
            elif mutation == "text":
                work.find(".//t:p", ns).text = "Invented text"
            elif mutation == "header":
                root.find("t:teiHeader/t:fileDesc/t:titleStmt/t:title", ns).text = "Wrong work"
            else:
                work.find(".//t:note", ns).set("n", "Invented number")
            content = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
        path.write_bytes(content)
        manifest_path = destination / "manifest.json"
        manifest = json.loads(manifest_path.read_bytes())
        record = next(n for n in manifest["members"] if n["name"] == member)
        record.update(bytes=len(content), sha256=hashlib.sha256(content).hexdigest())
        if member == "content.tei.xml":
            # Rebind the accountability envelope too, so a header mutation
            # must fail the semantic header check rather than a stale digest.
            accountability_path = destination / "source-accountability.json"
            accountability = json.loads(accountability_path.read_bytes())
            accountability["tei_sha256"] = hashlib.sha256(content).hexdigest()
            accountability_bytes = (json.dumps(accountability, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
            accountability_path.write_bytes(accountability_bytes)
            record = next(n for n in manifest["members"] if n["name"] == "source-accountability.json")
            record.update(bytes=len(accountability_bytes), sha256=hashlib.sha256(accountability_bytes).hexdigest())
        manifest_path.write_bytes((json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode())
        candidate = CandidatePackage.load(destination)
        candidate.verify_integrity()
        expected_reason = "complete header metadata mismatch" if mutation == "header" else ("complete provenance mismatch" if mutation == "provenance" else "readable|source title|inline work")
        with pytest.raises(ValueError, match=expected_reason):
            validate(source, candidate, _oracle)
    finally:
        shutil.rmtree(destination)
