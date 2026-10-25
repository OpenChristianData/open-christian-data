from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import tempfile

from lxml import etree
import pytest

from build.tei.npnf_chrysostom_oracle import (
    _closure_digest,
    _closure_paths,
    _oracle,
)
from build.tei.npnf_chrysostom_reconstruction import (
    ASSIGNED,
    SOURCE_SPECS,
    _convert,
)
from ocd_kernel.reconstruction import (
    CandidatePackage,
    SourceManifest,
    reconstruct,
    validate,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'tests/fixtures/reconstruction-runtime/npnf-chrysostom.source-manifest.json'

EXPECTED_CENSUS = {
    "elements": 58_867,
    "attributes": 155_252,
    "text_nodes": 43_635,
    "tail_nodes": 49_691,
    "characters": 10_468_284,
    "non_ascii_characters": 192_872,
    "note": 9_477,
    "pb": 2_027,
    "scripRef": 11_490,
}


def _independent_assigned_census() -> Counter[str]:
    census: Counter[str] = Counter()
    for spec in SOURCE_SPECS:
        path = ROOT / spec["path"]
        content = path.read_bytes()
        assert len(content) == spec["bytes"]
        assert hashlib.sha256(content).hexdigest() == spec["sha256"]
        tree = etree.fromstring(
            content,
            etree.XMLParser(
                resolve_entities=False,
                no_network=True,
                remove_comments=False,
                huge_tree=True,
            ),
        ).getroottree()
        assert tree.docinfo.doctype == (
            '<!DOCTYPE ThML PUBLIC "-//CCEL/DTD Theological Markup Language//EN" '
            '"http://www.ccel.org/dtd/ThML10.dtd">'
        )
        assert len(tree.xpath("/comment()")) == 2
        body = tree.getroot().find("ThML.body")
        assert body is not None
        selected = {
            node.get("id"): node
            for node in body
            if isinstance(node.tag, str) and node.tag == "div1"
        }
        for scope in spec["assigned_div1"]:
            for node in selected[scope].iter():
                assert isinstance(node.tag, str)
                census["elements"] += 1
                census["attributes"] += len(node.attrib)
                census["note"] += node.tag == "note"
                census["pb"] += node.tag == "pb"
                census["scripRef"] += node.tag == "scripRef"
                if node.text is not None:
                    census["text_nodes"] += 1
                    census["characters"] += len(node.text)
                    census["non_ascii_characters"] += sum(
                        ord(char) > 127 for char in node.text
                    )
                if node.tail is not None:
                    census["tail_nodes"] += 1
                    census["characters"] += len(node.tail)
                    census["non_ascii_characters"] += sum(
                        ord(char) > 127 for char in node.tail
                    )
    return census


def test_four_retained_members_and_seven_work_bindings_are_exact() -> None:
    assert sum(int(spec["bytes"]) for spec in SOURCE_SPECS) == 17_287_222
    assert tuple(
        work_id for spec in SOURCE_SPECS for _, work_id in spec["works"]
    ) == tuple(work_id for _, _, work_id in ASSIGNED)
    assert len(ASSIGNED) == 7
    assert _independent_assigned_census() == Counter(EXPECTED_CENSUS)


@pytest.fixture(scope="module")
def candidate() -> tuple[SourceManifest, CandidatePackage]:
    with tempfile.TemporaryDirectory(prefix="npnf-chrysostom-tests-") as directory:
        source = SourceManifest.load(MANIFEST, repository_root=ROOT)
        package = reconstruct(source, Path(directory) / "candidate", _convert)
        yield source, package


def test_candidate_preserves_all_assigned_roots_and_source_apparatus(
    candidate: tuple[SourceManifest, CandidatePackage],
) -> None:
    _, package = candidate
    assert package.member_names == (
        "README.source.md",
        "content.tei.xml",
        "manifest.json",
        "provenance.json",
        "source-accountability.json",
        "unresolved.jsonl",
    )
    tree = etree.fromstring(
        package.member_bytes("content.tei.xml"),
        etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True),
    ).getroottree()
    ns = {"tei": "http://www.tei-c.org/ns/1.0"}
    work_roots = tree.xpath("/tei:TEI/tei:text/tei:body/tei:div", namespaces=ns)
    assert [node.get("corresp") for node in work_roots] == [
        f"#{member}:{scope}:{work_id}" for member, scope, work_id in ASSIGNED
    ]
    expected_apparatus = {
        "npnf110-iii.i": "Title Page.",
        "npnf110-iii.ii": "Preface to the Oxford Edition.",
        "npnf110-iii.iii": "Introductory Essay.",
        "npnf111-vii.i": "Preface to Homilies on Romans.",
        "npnf111-vii.ii": "The Argument",
        "npnf112-iv.i": "Argument.",
        "npnf114-iv.i": "Title Page.",
        "npnf114-iv.ii": "Preface to the Homilies on the Gospel of St. John.",
        "npnf114-v.i": "Title Page.",
        "npnf114-v.ii": "Preface.",
        "npnf114-v.iii": "Introduction.",
        "npnf114-v.iv": "Argument.",
    }
    for xml_id, title in expected_apparatus.items():
        nodes = tree.xpath(f"//*[@xml:id='{xml_id}']", namespaces=ns)
        assert len(nodes) == 1
        assert nodes[0].findtext("tei:head", namespaces=ns) == title

    accountability = json.loads(package.member_bytes("source-accountability.json"))
    assert accountability["assigned_work_count"] == 7
    assert accountability["feature_count"] == EXPECTED_CENSUS["elements"]
    assert accountability["attribute_count"] == EXPECTED_CENSUS["attributes"]
    assert accountability["omitted_feature_count"] == 0
    assert accountability["duplicate_feature_count"] == 0
    assert accountability["unresolved_feature_count"] == 0
    assert accountability["excluded_index_comment_count"] == 110
    assert len(accountability["document_accounting"]) == 4
    assert all(
        row["pre_root_comment_count"] == 2
        for row in accountability["document_accounting"]
    )


def test_candidate_metadata_localizes_legacy_config_conflicts(
    candidate: tuple[SourceManifest, CandidatePackage],
) -> None:
    _, package = candidate
    provenance = json.loads(package.member_bytes("provenance.json"))
    by_id = {work["work_id"]: work for work in provenance["works"]}
    romans = by_id["chrysostom-homilies-on-romans"]["contributors"]
    assert [row["name"] for row in romans] == [
        "J. B. Morris",
        "W. H. Simcox",
        "George B. Stevens",
    ]
    john = by_id["chrysostom-homilies-on-john"]["contributors"]
    assert [row["name"] for row in john] == [
        "G. T. Stupart",
        "J. G. Hickley",
        "Philip Schaff",
    ]
    hebrews = by_id["chrysostom-homilies-on-hebrews"]["contributors"]
    assert [row["name"] for row in hebrews] == [
        "T. Keble",
        "T. Keble's brother, the Vicar of Hursley",
        "Frederic Gardiner",
    ]
    assert hebrews[-1]["role"] == "reviser, introduction author, and annotator"
    for work in by_id.values():
        assert work["human_review"] == "required"
        assert work["accepted_ir"] == "not_accepted"
        assert work["publication"] == "not_ready"
    readme = package.member_bytes("README.source.md")
    assert b"CCEL permits parsing its ThML" in readme
    assert b"do not sell" in readme


def test_oracle_runtime_closure_and_all_authority_pins_are_exact() -> None:
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    policy = json.loads(source.authority_path("validation-policy").read_bytes())
    observed = tuple(
        path.relative_to(ROOT).as_posix() for path in _closure_paths(ROOT, policy)
    )
    assert observed == (
        "build/__init__.py",
        "build/tei/__init__.py",
        "build/tei/npnf_chrysostom_oracle.py",
        "ocd_kernel/__init__.py",
        "ocd_kernel/lib/__init__.py",
        "ocd_kernel/lib/path_io.py",
        "ocd_kernel/lib/storage_topology.py",
        "ocd_kernel/reconstruction/__init__.py",
        "ocd_kernel/reconstruction/contract.py",
        "ocd_kernel/tei/__init__.py",
        "ocd_kernel/tei/normalization.py",
        "ocd_kernel/tei/projection_profile.py",
        "ocd_kernel/tei/validate.py",
    )
    assert (
        _closure_digest(ROOT, policy)
        == source.record["validator"]["import_closure_sha256"]
    )
    for authority in source.record["authorities"]:
        content = source.authority_path(authority["name"]).read_bytes()
        assert authority["bytes"] == len(content)
        assert authority["sha256"] == hashlib.sha256(content).hexdigest()
    oracle_source = (ROOT / "build/tei/npnf_chrysostom_oracle.py").read_text(
        encoding="utf-8"
    )
    for forbidden in policy["forbidden_oracle_imports"]:
        assert f"import {forbidden}" not in oracle_source
        assert f"from {forbidden}" not in oracle_source


def test_independent_oracle_passes_and_binds_all_four_sources(
    candidate: tuple[SourceManifest, CandidatePackage],
) -> None:
    source, package = candidate
    report = validate(source, package, _oracle)
    assert report.status == "pass"
    assert report.candidate_sha256 == package.sha256
    assert report.source_manifest_sha256 == source.sha256
    assert report.attestation["status"] == "pass"
    assert report.attestation["findings"] == ()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _independent_copy(source: Path, destination: Path) -> None:
    destination.mkdir()
    for path in source.iterdir():
        target = destination / path.name
        target.write_bytes(path.read_bytes())
        assert not os.path.samefile(path, target)


def _reseal(candidate_path: Path, changed_member: str) -> CandidatePackage:
    manifest_path = candidate_path / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    content = (candidate_path / changed_member).read_bytes()
    member = next(row for row in manifest["members"] if row["name"] == changed_member)
    member["bytes"] = len(content)
    member["sha256"] = hashlib.sha256(content).hexdigest()
    manifest_path.write_bytes(_canonical(manifest))
    return CandidatePackage.load(candidate_path)


@pytest.mark.parametrize(
    "mutation",
    [
        "omission",
        "duplication",
        "reorder",
        "invention",
        "metadata",
        "readme",
        "closure",
    ],
)
def test_oracle_rejects_fully_resealed_adversarial_mutants(
    candidate: tuple[SourceManifest, CandidatePackage],
    mutation: str,
) -> None:
    source, package = candidate
    with tempfile.TemporaryDirectory(
        prefix=f"npnf-chrysostom-{mutation}-"
    ) as directory:
        target = Path(directory) / "candidate"
        _independent_copy(package.path, target)
        changed_member = "content.tei.xml"
        if mutation in {"omission", "duplication", "reorder", "invention"}:
            xml_path = target / changed_member
            tree = etree.fromstring(
                xml_path.read_bytes(),
                etree.XMLParser(
                    resolve_entities=False, no_network=True, huge_tree=True
                ),
            ).getroottree()
            ns = {"tei": "http://www.tei-c.org/ns/1.0"}
            body = tree.xpath("/tei:TEI/tei:text/tei:body", namespaces=ns)[0]
            if mutation == "omission":
                victim = tree.xpath("//tei:p", namespaces=ns)[100]
                victim.getparent().remove(victim)
            elif mutation == "duplication":
                victim = tree.xpath("//tei:p", namespaces=ns)[100]
                victim.addnext(etree.fromstring(etree.tostring(victim)))
            elif mutation == "reorder":
                first, second = body[0], body[1]
                body.remove(second)
                body.insert(0, second)
                assert body[1] is first
            else:
                body.append(etree.Element("{http://www.tei-c.org/ns/1.0}p"))
            xml_path.write_bytes(
                etree.tostring(
                    tree,
                    encoding="UTF-8",
                    xml_declaration=True,
                    pretty_print=False,
                )
            )
        elif mutation == "metadata":
            changed_member = "provenance.json"
            path = target / changed_member
            value = json.loads(path.read_bytes())
            value["works"][0]["contributors"][0]["role"] = "invented translator"
            path.write_bytes(_canonical(value))
        elif mutation == "readme":
            changed_member = "README.source.md"
            path = target / changed_member
            path.write_bytes(path.read_bytes() + b"\nPublication ready.\n")
        else:
            changed_member = "manifest.json"
            path = target / changed_member
            value = json.loads(path.read_bytes())
            value["converter"]["implementation_sha256"] = "0" * 64
            path.write_bytes(_canonical(value))
        mutant = (
            CandidatePackage.load(target)
            if changed_member == "manifest.json"
            else _reseal(target, changed_member)
        )
        with pytest.raises(ValueError):
            _oracle(source, mutant)
