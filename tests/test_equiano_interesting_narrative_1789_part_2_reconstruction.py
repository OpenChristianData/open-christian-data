from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from lxml import etree
import pytest

from build.tei.equiano_interesting_narrative_1789_part_2_oracle import (
    _closure_digest,
    _closure_paths,
    _oracle,
)
from build.tei.equiano_interesting_narrative_1789_part_2_reconstruction import (
    _convert,
    _transform_source,
)
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, reconstruct, validate


ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(
    r"D:\Library\Open Christian Data\raw\clean-ready-acquisition-to-tei\master-2\15"
    r"\equiano-interesting-narrative-1789-part-2\K053415.002.xml"
)
SOURCE_SHA256 = "f8898fcc3e788196168593f3c6bdd12e3ef9cbcba9328091917073ffa305c5ed"
MANIFEST = ROOT / "tests/fixtures/reconstruction-runtime/equiano-interesting-narrative-1789-part-2.source-manifest.json"
TEI = {"tei": "http://www.tei-c.org/ns/1.0"}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def _clone_candidate(candidate: CandidatePackage, target: Path) -> Path:
    target.mkdir()
    for name in candidate.member_names:
        (target / name).write_bytes(candidate.member_bytes(name))
    return target


def _reseal_member(path: Path, member_name: str, content: bytes) -> CandidatePackage:
    (path / member_name).write_bytes(content)
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    member = next(item for item in manifest["members"] if item["name"] == member_name)
    member.update(bytes=len(content), sha256=_sha(content))
    manifest_path.write_bytes(_canonical(manifest))
    return CandidatePackage.load(path)


def _assert_oracle_rejects(source: SourceManifest, candidate: CandidatePackage) -> None:
    with pytest.raises(ValueError, match="^candidate validation failed$"):
        validate(source, candidate, _oracle)


@pytest.fixture(scope="module")
def verified_candidate(tmp_path_factory: pytest.TempPathFactory):
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    candidate = reconstruct(source, tmp_path_factory.mktemp("equiano-p2-candidate") / "package", _convert)
    report = validate(source, candidate, _oracle)
    assert report.status == "pass"
    return source, candidate, report


def test_source_bound_transform_is_valid_tei_and_keeps_part_two_structure() -> None:
    source_bytes = SOURCE.read_bytes()
    assert len(source_bytes) == 232_557
    assert _sha(source_bytes) == SOURCE_SHA256
    candidate_bytes = _transform_source(source_bytes)
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    source = etree.fromstring(source_bytes, parser)
    candidate = etree.fromstring(candidate_bytes, parser)
    schema = etree.XMLSchema(
        etree.parse(str(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd"))
    )
    assert schema.validate(candidate), str(schema.error_log)
    assert "".join(candidate.xpath("//tei:text", namespaces=TEI)[0].itertext()) == "".join(
        source.xpath("/ETS/EEBO/TEXT")[0].itertext()
    )
    assert candidate.xpath(
        "/tei:TEI/tei:text/tei:front/tei:div/@type | /tei:TEI/tei:text/tei:body/tei:div/@type",
        namespaces=TEI,
    ) == ["frontispiece", "chapter", "chapter", "chapter", "chapter", "chapter", "chapter"]
    assert candidate.xpath(
        "/tei:TEI/tei:text/tei:body/tei:div[@type='chapter']/@n",
        namespaces=TEI,
    ) == ["7", "8", "9", "10", "11", "12"]
    assert candidate.xpath(
        "//tei:floatingText/tei:body/tei:div[@type!='letter']/@type", namespaces=TEI
    ) == ["grant", "order", "petition", "petition"]
    assert len(candidate.xpath("//tei:floatingText/tei:body/tei:div[@type='letter']", namespaces=TEI)) == 5
    assert candidate.xpath("string(//tei:div[@type='poem']/tei:head)", namespaces=TEI) == (
        "MISCELLANEOUS VERSES, OR, Reflections on the State of my Mind during my "
        "first Convictions, of the Necessity of believing the Truth, and experiencing "
        "the inestimable Benefits of Christianity."
    )
    assert len(candidate.xpath("//tei:pb", namespaces=TEI)) == 269
    assert len(candidate.xpath("//tei:gap[@reason='illegible']", namespaces=TEI)) == 36
    assert len(candidate.xpath("//tei:note", namespaces=TEI)) == 6
    assert len(candidate.xpath("//tei:l", namespaces=TEI)) == 124
    assert len(candidate.xpath("//tei:lg", namespaces=TEI)) == 28
    assert source.xpath("string(/ETS/TEMPHEAD/REVDESCR/CHANGE/DATE)") == "2007-10-04"
    source_change = candidate.xpath(
        "/tei:TEI/tei:teiHeader/tei:revisionDesc/tei:change[1]", namespaces=TEI
    )
    assert len(source_change) == 1
    assert source_change[0].get("when") == "2007-10-04"
    assert "".join(source_change[0].itertext()) == (
        "Proofed and reviewed by Simon Charles; responsibility MURP."
    )
    assert candidate.xpath("string(//tei:trailer[last()])", namespaces=TEI) == "THE END."


def test_sealed_candidate_is_nonaccepted_and_fully_accounted(verified_candidate) -> None:
    _, candidate, report = verified_candidate
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    assert candidate.manifest["status"] == "nonaccepted"
    assert accountability["source_content_bytes"] == 232_557
    assert accountability["source_content_sha256"] == SOURCE_SHA256
    assert accountability["source_text_characters"] == 214_999
    assert accountability["source_text_sha256"] == "89e98b362a30972739ca1a4d88c5f14dd13c82ace195ae06106fcf7b6d9102af"
    assert accountability["candidate_text_sha256"] == accountability["source_text_sha256"]
    assert accountability["omitted_source_text_characters"] == 0
    assert accountability["duplicated_source_text_characters"] == 0
    assert accountability["unresolved_source_elements"] == 0
    assert accountability["candidate_element_counts"]["floatingText"] == 9
    assert accountability["candidate_element_counts"]["l"] == 124
    assert report.findings == ()


def test_oracle_rejects_resealed_text_mutation(verified_candidate, tmp_path: Path) -> None:
    source, candidate, _ = verified_candidate
    target = _clone_candidate(candidate, tmp_path / "mutated-text")
    content = candidate.member_bytes("content.tei.xml")
    assert b"MISCELLANEOUS VERSES" in content
    resealed = _reseal_member(target, "content.tei.xml", content.replace(b"MISCELLANEOUS VERSES", b"MISCELLANEOUS VERS3S", 1))
    _assert_oracle_rejects(source, resealed)


@pytest.mark.parametrize("mutation", ["omit", "alter", "extra"])
def test_oracle_rejects_unresolved_ledger_mutations(verified_candidate, tmp_path: Path, mutation: str) -> None:
    source, candidate, _ = verified_candidate
    target = _clone_candidate(candidate, tmp_path / f"unresolved-{mutation}")
    rows = [json.loads(line) for line in candidate.member_bytes("unresolved.jsonl").splitlines()]
    if mutation == "omit": rows.pop(1)
    elif mutation == "alter": rows[1]["status"] = "resolved"
    else: rows.append(dict(rows[0]))
    _assert_oracle_rejects(source, _reseal_member(target, "unresolved.jsonl", b"".join(_canonical(row) for row in rows)))


@pytest.mark.parametrize(("member_name", "old", "new"), [
    ("provenance.json", b'"date":"1789"', b'"date":"1788"'),
    ("source-accountability.json", b'"omitted_source_text_characters":0', b'"omitted_source_text_characters":1'),
    ("README.source.md", b"K053415.002", b"K053415.00X"),
])
def test_oracle_rejects_nontext_member_mutations(verified_candidate, tmp_path: Path, member_name: str, old: bytes, new: bytes) -> None:
    source, candidate, _ = verified_candidate
    target = _clone_candidate(candidate, tmp_path / member_name.replace(".", "-"))
    content = candidate.member_bytes(member_name)
    assert old in content
    _assert_oracle_rejects(source, _reseal_member(target, member_name, content.replace(old, new, 1)))


@pytest.mark.parametrize(("field_path", "replacement"), [
    (("status",), "accepted"), (("source_id",), "wrong-source"),
    (("source_manifest", "sha256"), "0" * 64),
    (("source_manifest", "path"), "sources/structured-text/equiano-interesting-narrative-1789-part-2/equiano-interesting-narrative-1789-part-2.source-manifest.json"),
    (("converter", "version"), "wrong-version"),
    (("package_schema", "sha256"), "0" * 64),
])
def test_oracle_rejects_candidate_manifest_binding_mutations(verified_candidate, tmp_path: Path, field_path: tuple[str, ...], replacement: str) -> None:
    source, candidate, _ = verified_candidate
    target = _clone_candidate(candidate, tmp_path / ("manifest-" + "-".join(field_path)))
    manifest_path = target / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    owner = manifest
    for key in field_path[:-1]: owner = owner[key]
    owner[field_path[-1]] = replacement
    manifest_path.write_bytes(_canonical(manifest))
    mutated = CandidatePackage.load(target)
    if field_path in {
        ("source_id",),
        ("source_manifest", "sha256"),
        ("source_manifest", "path"),
    }:
        # Shared source binding is checked before the work-specific oracle.
        with pytest.raises(
            ValueError, match="^candidate source manifest binding mismatch$"
        ):
            validate(source, mutated, _oracle)
    else:
        _assert_oracle_rejects(source, mutated)


def test_oracle_import_closure_is_complete_and_manifest_bound() -> None:
    expected = {ROOT / "build/tei/equiano_interesting_narrative_1789_part_2_oracle.py", ROOT / "ocd_kernel/__init__.py", ROOT / "ocd_kernel/reconstruction/__init__.py", ROOT / "ocd_kernel/reconstruction/contract.py"}
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    assert set(_closure_paths()) == expected
    assert source.record["validator"]["import_closure_sha256"] == _closure_digest()


def test_fresh_process_from_different_cwd_is_byte_identical(verified_candidate, tmp_path: Path) -> None:
    _, candidate, _ = verified_candidate
    output = tmp_path / "fresh-package"
    env = os.environ.copy(); env["PYTHONPATH"] = str(ROOT)
    command = ("from pathlib import Path;from ocd_kernel.reconstruction import SourceManifest,reconstruct;from build.tei.equiano_interesting_narrative_1789_part_2_reconstruction import _convert;" + f"r=Path({str(ROOT)!r});m=Path({str(MANIFEST)!r});" + "s=SourceManifest.load(m,repository_root=r);reconstruct(s,Path(__import__('sys').argv[1]),_convert)")
    run = subprocess.run([sys.executable, "-c", command, str(output)], cwd=tmp_path, env=env, check=False, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    fresh = CandidatePackage.load(output)
    assert fresh.sha256 == candidate.sha256
    assert all(fresh.member_bytes(name) == candidate.member_bytes(name) for name in candidate.member_names)
