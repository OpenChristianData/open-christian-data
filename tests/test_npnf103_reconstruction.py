from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

from lxml import etree
import pytest

from build.tei.npnf103_oracle import _closure_digest, _closure_paths, _oracle
from build.tei.npnf103_reconstruction import ASSIGNED, _convert
from ocd_kernel.reconstruction import (
    CandidatePackage,
    SourceManifest,
    reconstruct,
    validate,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "raw/ccel/npnf1/npnf103.xml"
MANIFEST = ROOT / 'tests/fixtures/reconstruction-runtime/npnf103.source-manifest.json'
SOURCE_SHA256 = "410f240f8105bb6097316a54a867fa5a4ae02c0d3d03606aefc2df71f5bfc455"
EXPECTED_COUNTS = {
    "br": 4,
    "div2": 16,
    "div3": 580,
    "div4": 226,
    "i": 1309,
    "note": 2775,
    "p": 4414,
    "pb": 504,
    "scripRef": 2297,
    "span": 705,
    "sup": 2,
}
TEI_NS = "http://www.tei-c.org/ns/1.0"
TEI = {"tei": TEI_NS}
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
EXPECTED_CLOSURE = (
    "build/__init__.py",
    "build/tei/__init__.py",
    "build/tei/npnf103_oracle.py",
    "ocd_kernel/__init__.py",
    "ocd_kernel/lib/__init__.py",
    "ocd_kernel/lib/path_io.py",
    "ocd_kernel/lib/storage_topology.py",
    "ocd_kernel/reconstruction/__init__.py",
    "ocd_kernel/reconstruction/contract.py",
    "ocd_kernel/reconstruction/verifier.py",
    "ocd_kernel/tei/__init__.py",
    "ocd_kernel/tei/normalization.py",
    "ocd_kernel/tei/projection_profile.py",
    "ocd_kernel/tei/validate.py",
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _reseal(path: Path, member_name: str) -> CandidatePackage:
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    content = (path / member_name).read_bytes()
    member = next(item for item in manifest["members"] if item["name"] == member_name)
    member.update(bytes=len(content), sha256=_sha(content))
    manifest_path.write_bytes(_canonical(manifest))
    return CandidatePackage.load(path)


def _write_tree(path: Path, tree: etree._ElementTree) -> None:
    path.write_bytes(
        etree.tostring(
            tree,
            encoding="UTF-8",
            xml_declaration=True,
            pretty_print=False,
        )
    )


def _rejection_message(
    source: SourceManifest, candidate: CandidatePackage
) -> str:
    with pytest.raises(ValueError) as caught:
        _oracle(source, candidate)
    return str(caught.value)


@pytest.fixture(scope="module")
def verified_candidate(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[SourceManifest, CandidatePackage]:
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    candidate = reconstruct(
        source, tmp_path_factory.mktemp("npnf103-candidate") / "candidate", _convert
    )
    report = validate(source, candidate, _oracle)
    assert report.status == "pass"
    return source, candidate


def test_retained_npnf103_authority_and_sixteen_work_scope_are_exact() -> None:
    content = SOURCE.read_bytes()
    tree = etree.fromstring(
        content,
        etree.XMLParser(
            resolve_entities=False,
            no_network=True,
            remove_comments=False,
            huge_tree=True,
        ),
    )
    selected = [
        node
        for node in tree.xpath("//ThML.body/div1/div2")
        if node.get("id") in {scope for scope, _ in ASSIGNED}
    ]
    features = [node for division in selected for node in division.iter()]
    observed_counts = {
        tag: sum(node.tag == tag for node in features) for tag in EXPECTED_COUNTS
    }

    assert len(content) == 3_842_341
    assert _sha(content) == SOURCE_SHA256
    assert [node.get("id") for node in selected] == [scope for scope, _ in ASSIGNED]
    assert len(features) == 12_832
    assert sum(len(node.attrib) for node in features) == 35_788
    assert sum(node.text is not None for node in features) == 8_673
    assert sum(node.tail is not None for node in features) == 7_053
    assert (
        sum(len((node.text or "") + (node.tail or "")) for node in features)
        == 2_420_322
    )
    assert observed_counts == EXPECTED_COUNTS
    assert not any(
        isinstance(node, (etree._Comment, etree._ProcessingInstruction))
        for node in features
    )


def test_candidate_is_complete_nonaccepted_and_preserves_credit_uncertainty(
    verified_candidate: tuple[SourceManifest, CandidatePackage],
) -> None:
    _, candidate = verified_candidate
    assert candidate.member_names == (
        "README.source.md",
        "content.tei.xml",
        "manifest.json",
        "provenance.json",
        "source-accountability.json",
        "unresolved.jsonl",
    )
    assert candidate.manifest["status"] == "nonaccepted"
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    assert accountability["assigned_work_count"] == 16
    assert accountability["feature_count"] == 12_832
    assert accountability["omitted_feature_count"] == 0
    assert len(accountability["top_level_division_accounting"]) == 7
    assert len(accountability["direct_div2_accounting"]) == 21
    assert len(accountability["crosswalk"]) == 12_832
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    assert all(work["human_review"] == "required" for work in provenance["works"])
    assert all(work["accepted_ir"] == "not_accepted" for work in provenance["works"])
    assert all(work["publication"] == "not_ready" for work in provenance["works"])
    unresolved = [
        json.loads(line)
        for line in candidate.member_bytes("unresolved.jsonl").decode().splitlines()
    ]
    assert len(unresolved) == 4
    assert {row["id"] for row in unresolved} == {
        "npnf103-on-the-creed-credit-conflict",
        "npnf103-holy-virginity-name-form-conflict",
        "npnf103-edition-witness-and-print-collation",
        "npnf103-rights-human-acceptance-and-publication",
    }


@pytest.mark.parametrize(
    "mutation",
    [
        "omission",
        "duplication",
        "reorder",
        "invention",
        "root-attribute",
        "text-attribute",
        "body-text",
        "invented-front",
        "invented-back",
        "invented-group",
        "invented-standOff",
        "nested-namespace",
        "comment",
        "processing-instruction",
    ],
)
def test_independent_oracle_rejects_resealed_tei_structure_mutations(
    verified_candidate: tuple[SourceManifest, CandidatePackage],
    tmp_path: Path,
    mutation: str,
) -> None:
    source, candidate = verified_candidate
    target = tmp_path / mutation
    shutil.copytree(candidate.path, target)
    xml_path = target / "content.tei.xml"
    tree = etree.parse(str(xml_path), etree.XMLParser(remove_comments=False))
    root = tree.getroot()
    text = root.find(f"{{{TEI_NS}}}text")
    assert text is not None
    body = text.find(f"{{{TEI_NS}}}body")
    assert body is not None
    if mutation == "omission":
        node = body.xpath(".//tei:p", namespaces=TEI)[0]
        node.getparent().remove(node)
    elif mutation == "duplication":
        node = body.xpath(".//tei:p", namespaces=TEI)[0]
        duplicate = etree.fromstring(etree.tostring(node))
        for ordinal, descendant in enumerate(duplicate.iter(), start=1):
            if descendant.get(XML_ID):
                descendant.set(XML_ID, f"npnf103-invented-{ordinal}")
        node.getparent().append(duplicate)
    elif mutation == "reorder":
        first, second = list(body)[:2]
        body.remove(second)
        body.insert(0, second)
        assert list(body)[1] is first
    elif mutation == "invention":
        invented = etree.SubElement(body, f"{{{TEI_NS}}}div")
        invented.set(XML_ID, "npnf103-invented")
    elif mutation == "root-attribute":
        root.set("type", "invented")
    elif mutation == "text-attribute":
        text.set("type", "invented")
    elif mutation == "body-text":
        body.text = "invented direct text"
    elif mutation in {"invented-front", "invented-back", "invented-group"}:
        local = mutation.removeprefix("invented-")
        etree.SubElement(text, f"{{{TEI_NS}}}{local}")
    elif mutation == "invented-standOff":
        etree.SubElement(root, f"{{{TEI_NS}}}standOff")
    elif mutation == "nested-namespace":
        node = body.xpath(".//tei:p", namespaces=TEI)[0]
        node.append(
            etree.Element("{urn:invented}invented", nsmap={"x": "urn:invented"})
        )
    elif mutation == "comment":
        body.append(etree.Comment("invented"))
    else:
        body.append(etree.ProcessingInstruction("invented", "value"))
    _write_tree(xml_path, tree)
    mutated = _reseal(target, "content.tei.xml")
    _rejection_message(source, mutated)


@pytest.mark.parametrize(
    ("mutation", "replacement"),
    [
        ("declaration", b'<?xml version="1.0" encoding="UTF-8"?>'),
        (
            "standalone",
            b"<?xml version='1.0' encoding='UTF-8' standalone='yes'?>",
        ),
        (
            "doctype",
            b"<?xml version='1.0' encoding='UTF-8'?>\n<!DOCTYPE TEI>",
        ),
        (
            "leading-pi",
            b"<?xml version='1.0' encoding='UTF-8'?>\n<?invented value?>",
        ),
    ],
)
def test_independent_oracle_rejects_resealed_document_shell_mutations(
    verified_candidate: tuple[SourceManifest, CandidatePackage],
    tmp_path: Path,
    mutation: str,
    replacement: bytes,
) -> None:
    source, candidate = verified_candidate
    target = tmp_path / mutation
    shutil.copytree(candidate.path, target)
    xml_path = target / "content.tei.xml"
    content = xml_path.read_bytes()
    declaration, rest = content.split(b"\n", 1)
    assert declaration == b"<?xml version='1.0' encoding='UTF-8'?>"
    xml_path.write_bytes(replacement + b"\n" + rest)
    mutated = _reseal(target, "content.tei.xml")
    message = _rejection_message(source, mutated)
    assert any(stage in message for stage in ("prolog", "well-formed", "sibling"))


@pytest.mark.parametrize(
    ("member_name", "mutation"),
    [
        ("README.source.md", "\nHuman review: accepted. Publication: ready.\n"),
        ("provenance.json", None),
        ("source-accountability.json", None),
        ("unresolved.jsonl", ""),
    ],
)
def test_independent_oracle_rejects_resealed_evidence_drift(
    verified_candidate: tuple[SourceManifest, CandidatePackage],
    tmp_path: Path,
    member_name: str,
    mutation: str | None,
) -> None:
    source, candidate = verified_candidate
    target = tmp_path / member_name.replace(".", "-")
    shutil.copytree(candidate.path, target)
    path = target / member_name
    if member_name == "README.source.md":
        path.write_text(path.read_text(encoding="utf-8") + mutation, encoding="utf-8")
    elif member_name == "provenance.json":
        value = json.loads(path.read_bytes())
        value["rights"]["publication_state"] = "ready"
        path.write_bytes(_canonical(value))
    elif member_name == "source-accountability.json":
        value = json.loads(path.read_bytes())
        value["crosswalk"][0]["source_selector"] = "invented"
        path.write_bytes(_canonical(value))
    else:
        path.write_text(mutation, encoding="utf-8")
    mutated = _reseal(target, member_name)
    _rejection_message(source, mutated)


def test_oracle_runtime_closure_and_source_local_authorities_are_exact() -> None:
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    policy = json.loads(source.authority_path("validation-policy").read_bytes())
    observed = tuple(
        path.relative_to(ROOT).as_posix() for path in _closure_paths(ROOT, policy)
    )
    assert observed == EXPECTED_CLOSURE
    assert (
        _closure_digest(ROOT, policy)
        == source.record["validator"]["import_closure_sha256"]
    )
    for authority in source.record["authorities"]:
        content = source.authority_path(authority["name"]).read_bytes()
        assert authority["bytes"] == len(content)
        assert authority["sha256"] == _sha(content)
    oracle_source = (ROOT / "build/tei/npnf103_oracle.py").read_text(encoding="utf-8")
    for forbidden in policy["forbidden_oracle_imports"]:
        assert f"import {forbidden}" not in oracle_source
        assert f"from {forbidden}" not in oracle_source
