from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Callable

from lxml import etree
import pytest

from build.tei.hodge_systematic_theology_vol_2_oracle import _oracle
from build.tei.hodge_systematic_theology_vol_2_reconstruction import _convert
from ocd_kernel.reconstruction import (
    CandidatePackage,
    SourceManifest,
    reconstruct,
    validate,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tests/fixtures/reconstruction-runtime/hodge-systematic-theology-vol-2.source-manifest.json"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
TEI = {"tei": TEI_NS}


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _clone(candidate: CandidatePackage, destination: Path) -> Path:
    shutil.copytree(candidate.path, destination)
    return destination


def _reseal(candidate_path: Path, member_name: str) -> CandidatePackage:
    manifest_path = candidate_path / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    content = (candidate_path / member_name).read_bytes()
    member = next(row for row in manifest["members"] if row["name"] == member_name)
    member.update(bytes=len(content), sha256=hashlib.sha256(content).hexdigest())
    manifest_path.write_bytes(_canonical(manifest))
    return CandidatePackage.load(candidate_path)


def _mutate_json_member(
    candidate: CandidatePackage,
    destination: Path,
    member_name: str,
    mutation: Callable[[dict[str, Any]], None],
) -> CandidatePackage:
    mutated_path = _clone(candidate, destination)
    member_path = mutated_path / member_name
    record = json.loads(member_path.read_bytes())
    mutation(record)
    member_path.write_bytes(_canonical(record))
    return _reseal(mutated_path, member_name)


@pytest.fixture(scope="module")
def verified_candidate(tmp_path_factory: pytest.TempPathFactory):
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    destination = tmp_path_factory.mktemp("hodge-vol-2-candidate") / "candidate"
    candidate = reconstruct(source, destination, _convert)
    report = validate(source, candidate, _oracle)
    assert report.status == "pass"
    return source, candidate, report


def test_volume_two_manifest_binds_its_exact_source_and_work_scope() -> None:
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    source.verify()

    retained = source.authority_path("retained-hodge-vol-2").read_bytes()
    assert len(retained) == 2_601_781
    assert hashlib.sha256(retained).hexdigest() == (
        "52a43581dcb7b75a6903c89c8e2496b8d754bdbcd6fa751ecaa4f065e933d942"
    )
    assert source.record["source_id"] == (
        "ocd-37c204-hodge-systematic-theology-vol-2-ccel-theology2"
    )
    scope = source.record["scope"]
    assert scope["assigned_roots_in_source_order"] == (
        ("hodge-vol-2", "iii", "hodge-systematic-theology-vol-2"),
        ("hodge-vol-2", "iv", "hodge-systematic-theology-vol-2"),
    )
    assert scope["excluded_top_level_roots"] == ("i", "ii", "v")
    assert scope["kind"] == "complete-source-subtrees"
    assert scope["source_member"] == "retained-hodge-vol-2"


def test_volume_two_candidate_is_independently_validated_and_nonaccepted(
    verified_candidate,
) -> None:
    source, candidate, report = verified_candidate
    tree = etree.ElementTree(
        etree.fromstring(candidate.member_bytes("content.tei.xml"))
    )
    schema = etree.XMLSchema(etree.parse(str(source.authority_path("tei-p5-xsd"))))
    schema.assertValid(tree)

    assert candidate.manifest["status"] == "nonaccepted"
    assert report.status == "pass"
    body = tree.xpath("/tei:TEI/tei:text/tei:body", namespaces=TEI)[0]
    assert [_node.get(XML_ID) for _node in body] == [
        "hodge-systematic-theology-vol-2-feature-000001",
        "hodge-systematic-theology-vol-2-feature-002765",
    ]
    assert len(tree.xpath("//tei:milestone[@unit='separator']", namespaces=TEI)) == 2
    assert len(tree.xpath("//tei:lg[@type='source-verse']", namespaces=TEI)) == 7
    assert (
        len(tree.xpath("//tei:l[@rend='class=t1' or @rend='class=t2']", namespaces=TEI))
        == 28
    )

    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    assert accountability["assigned_census"]["elements"] == 6940
    assert accountability["assigned_census"]["attributes"] == 14069
    assert accountability["assigned_census"]["tag_counts"]["hr"] == 2
    assert accountability["assigned_census"]["tag_counts"]["verse"] == 7
    assert accountability["assigned_census"]["tag_counts"]["l"] == 28
    assert [row["id"] for row in accountability["root_accounting"]] == [
        "i",
        "ii",
        "iii",
        "iv",
        "v",
    ]
    assert [row["feature_count"] for row in accountability["root_bindings"]] == [
        2764,
        4176,
    ]
    chapter_mapping = next(
        row
        for row in accountability["crosswalk"]
        if row["source_selector"] == "ThML.body/div1[3]/div2[1]"
    )
    assert chapter_mapping["source_attributes"]["title"] == (
        "Chapter I. Origin of Man."
    )
    assert next(
        disposition
        for disposition in chapter_mapping["attribute_dispositions"]
        if disposition["source_attribute"] == "title"
    ) == {
        "destination": "source-accountability-only",
        "method": "preserved-exactly-in-accountability",
        "source_attribute": "title",
        "source_value": "Chapter I. Origin of Man.",
    }
    chapter = tree.xpath(
        "/tei:TEI/tei:text/tei:body//tei:div[@xml:id='hodge-systematic-theology-vol-2-feature-000011']",
        namespaces=TEI,
    )[0]
    assert [head.text for head in chapter.xpath("./tei:head", namespaces=TEI)] == [
        "CHAPTER I.",
        "ORIGIN OF MAN.",
    ]

    provenance = json.loads(candidate.member_bytes("provenance.json"))
    config_claims = provenance["sources"]["hodge-vol-2"]["config_claims"]
    assert config_claims["status"] == "unresolved-not-adopted"
    assert config_claims["claims"]["source_edition"].endswith(
        "New York: Scribner, Armstrong, 1872-1873."
    )
    assert (
        "1872-1873"
        in tree.xpath(
            "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:note[@type='unverified-local-edition-claim']/text()",
            namespaces=TEI,
        )[0]
    )
    assert not tree.xpath(
        "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:date[@when='1872' or @when='1873']",
        namespaces=TEI,
    )


def test_oracle_rejects_resealed_verse_line_attribute_mutation(
    verified_candidate, tmp_path: Path
) -> None:
    source, candidate, _report = verified_candidate
    mutated_path = _clone(candidate, tmp_path / "line-attribute-mutation")
    tree = etree.parse(str(mutated_path / "content.tei.xml"))
    first_line = tree.xpath("//tei:lg[@type='source-verse']/tei:l", namespaces=TEI)[0]
    first_line.set("rend", "class=t2")
    (mutated_path / "content.tei.xml").write_bytes(
        etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=False)
    )
    mutated = _reseal(mutated_path, "content.tei.xml")

    with pytest.raises(ValueError, match="candidate attributes drift at source l"):
        _oracle(source, mutated)


def test_oracle_rejects_resealed_verse_line_reordering(
    verified_candidate, tmp_path: Path
) -> None:
    source, candidate, _report = verified_candidate
    mutated_path = _clone(candidate, tmp_path / "verse-line-reordering")
    tree = etree.parse(str(mutated_path / "content.tei.xml"))
    group = tree.xpath("//tei:lg[@type='source-verse']", namespaces=TEI)[0]
    lines = list(group)
    reordered = [lines[2], lines[1], lines[0], *lines[3:]]
    for line in lines:
        group.remove(line)
    for line in reordered:
        group.append(line)
    (mutated_path / "content.tei.xml").write_bytes(
        etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=False)
    )
    mutated = _reseal(mutated_path, "content.tei.xml")

    with pytest.raises(
        ValueError,
        match="candidate attributes drift at source l|candidate source text or tail drift",
    ):
        _oracle(source, mutated)


def test_oracle_rejects_resealed_source_text_mutation(
    verified_candidate, tmp_path: Path
) -> None:
    source, candidate, _report = verified_candidate
    mutated_path = _clone(candidate, tmp_path / "source-text-mutation")
    tree = etree.parse(str(mutated_path / "content.tei.xml"))
    first_paragraph = tree.xpath("/tei:TEI/tei:text/tei:body//tei:p", namespaces=TEI)[0]
    first_paragraph.text = f"{first_paragraph.text or ''} MUTATED"
    (mutated_path / "content.tei.xml").write_bytes(
        etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=False)
    )
    mutated = _reseal(mutated_path, "content.tei.xml")

    with pytest.raises(ValueError, match="candidate source text or tail drift"):
        _oracle(source, mutated)


def test_oracle_rejects_resealed_structure_mutation(
    verified_candidate, tmp_path: Path
) -> None:
    source, candidate, _report = verified_candidate
    mutated_path = _clone(candidate, tmp_path / "structure-mutation")
    tree = etree.parse(str(mutated_path / "content.tei.xml"))
    milestone = tree.xpath("//tei:milestone", namespaces=TEI)[0]
    milestone.getparent().remove(milestone)
    (mutated_path / "content.tei.xml").write_bytes(
        etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=False)
    )
    mutated = _reseal(mutated_path, "content.tei.xml")

    with pytest.raises(ValueError, match="candidate omits, duplicates, or invents source structure"):
        _oracle(source, mutated)


def test_oracle_rejects_resealed_hr_attribute_mutation(
    verified_candidate, tmp_path: Path
) -> None:
    source, candidate, _report = verified_candidate
    mutated_path = _clone(candidate, tmp_path / "hr-attribute-mutation")
    tree = etree.parse(str(mutated_path / "content.tei.xml"))
    milestone = tree.xpath("//tei:milestone", namespaces=TEI)[0]
    milestone.set("unit", "section")
    (mutated_path / "content.tei.xml").write_bytes(
        etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=False)
    )
    mutated = _reseal(mutated_path, "content.tei.xml")

    with pytest.raises(ValueError, match="candidate attributes drift at source hr"):
        _oracle(source, mutated)


def test_oracle_rejects_resealed_verse_group_membership_mutation(
    verified_candidate, tmp_path: Path
) -> None:
    source, candidate, _report = verified_candidate
    mutated_path = _clone(candidate, tmp_path / "verse-group-membership-mutation")
    tree = etree.parse(str(mutated_path / "content.tei.xml"))
    groups = tree.xpath("//tei:lg[@type='source-verse']", namespaces=TEI)
    first_line = groups[0].xpath("./tei:l", namespaces=TEI)[0]
    groups[0].remove(first_line)
    groups[1].insert(0, first_line)
    (mutated_path / "content.tei.xml").write_bytes(
        etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=False)
    )
    mutated = _reseal(mutated_path, "content.tei.xml")

    with pytest.raises(
        ValueError, match="candidate omits, duplicates, or invents source structure"
    ):
        _oracle(source, mutated)


def test_oracle_rejects_resealed_root_binding_mutation(
    verified_candidate, tmp_path: Path
) -> None:
    source, candidate, _report = verified_candidate
    mutated = _mutate_json_member(
        candidate,
        tmp_path / "root-binding-mutation",
        "source-accountability.json",
        lambda record: record["root_bindings"][0].update(work_id="other-work"),
    )

    with pytest.raises(ValueError, match="source root bindings drift"):
        _oracle(source, mutated)


def test_oracle_rejects_resealed_work_binding_mutation(
    verified_candidate, tmp_path: Path
) -> None:
    source, candidate, _report = verified_candidate
    mutated = _mutate_json_member(
        candidate,
        tmp_path / "work-binding-mutation",
        "source-accountability.json",
        lambda record: record["work_bindings"][0].update(root_ids=["iii"]),
    )

    with pytest.raises(ValueError, match="source work bindings drift"):
        _oracle(source, mutated)


def test_oracle_rejects_resealed_attribute_disposition_mutation(
    verified_candidate, tmp_path: Path
) -> None:
    source, candidate, _report = verified_candidate

    def mutate(record: dict[str, Any]) -> None:
        row = next(
            item for item in record["crosswalk"] if item["attribute_dispositions"]
        )
        row["attribute_dispositions"][0]["source_value"] = "tampered"

    mutated = _mutate_json_member(
        candidate,
        tmp_path / "attribute-disposition-mutation",
        "source-accountability.json",
        mutate,
    )

    with pytest.raises(ValueError, match="source attribute disposition drift"):
        _oracle(source, mutated)


def test_oracle_rejects_resealed_permission_provenance_mutation(
    verified_candidate, tmp_path: Path
) -> None:
    source, candidate, _report = verified_candidate

    def mutate(record: dict[str, Any]) -> None:
        record["sources"]["hodge-vol-2"]["permission_evidence"]["sha256"] = "0" * 64

    mutated = _mutate_json_member(
        candidate,
        tmp_path / "permission-provenance-mutation",
        "provenance.json",
        mutate,
    )

    with pytest.raises(ValueError, match="permission provenance drift"):
        _oracle(source, mutated)


def test_oracle_rejects_resealed_witness_provenance_mutation(
    verified_candidate, tmp_path: Path
) -> None:
    source, candidate, _report = verified_candidate

    def mutate(record: dict[str, Any]) -> None:
        record["sources"]["hodge-vol-2"]["witness_inventory"]["notes"] = "tampered"

    mutated = _mutate_json_member(
        candidate,
        tmp_path / "witness-provenance-mutation",
        "provenance.json",
        mutate,
    )

    with pytest.raises(ValueError, match="witness provenance drift"):
        _oracle(source, mutated)


def test_oracle_rejects_resealed_work_provenance_mutation(
    verified_candidate, tmp_path: Path
) -> None:
    source, candidate, _report = verified_candidate
    mutated = _mutate_json_member(
        candidate,
        tmp_path / "work-provenance-mutation",
        "provenance.json",
        lambda record: record["works"][0].update(human_review="not_required"),
    )

    with pytest.raises(ValueError, match="work provenance drift"):
        _oracle(source, mutated)


def test_fresh_process_reproduces_candidate_bytes_from_a_different_directory(
    verified_candidate, tmp_path: Path
) -> None:
    _source, candidate, report = verified_candidate
    other_cwd = tmp_path / "different-cwd"
    other_cwd.mkdir()
    destination = tmp_path / "fresh-process-candidate"
    script = """
import hashlib
import json
from pathlib import Path
import sys
from ocd_kernel.reconstruction import SourceManifest, reconstruct, validate
from build.tei.hodge_systematic_theology_vol_2_oracle import _oracle
from build.tei.hodge_systematic_theology_vol_2_reconstruction import _convert

root = Path(sys.argv[1])
manifest = SourceManifest.load(Path(sys.argv[2]), repository_root=root)
package = reconstruct(manifest, Path(sys.argv[3]), _convert)
report = validate(manifest, package, _oracle)
print(json.dumps({
    "candidate_sha256": package.sha256,
    "report_sha256": report.sha256,
    "member_hashes": {
        name: hashlib.sha256(package.member_bytes(name)).hexdigest()
        for name in package.member_names
    },
}, sort_keys=True))
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        item for item in (str(ROOT), environment.get("PYTHONPATH", "")) if item
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(ROOT), str(MANIFEST), str(destination)],
        cwd=other_cwd,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    reproduced = json.loads(result.stdout)
    expected_hashes = {
        name: hashlib.sha256(candidate.member_bytes(name)).hexdigest()
        for name in candidate.member_names
    }
    assert reproduced["candidate_sha256"] == candidate.sha256
    assert reproduced["report_sha256"] == report.sha256
    assert reproduced["member_hashes"] == expected_hashes
