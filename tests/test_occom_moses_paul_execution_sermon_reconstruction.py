from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from lxml import etree
import pytest

from build.tei.occom_moses_paul_execution_sermon_oracle import (
    _closure_digest,
    _closure_paths,
    _oracle,
)
from build.tei.occom_moses_paul_execution_sermon_reconstruction import _convert
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, reconstruct, validate
from build.lib.tei_xsd import compiled_tei_schema


ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(
    r"D:\Library\Open Christian Data\raw\clean-ready-acquisition-to-tei\master-2\15"
    r"\occom-moses-paul-execution-sermon\N09814.xml"
)
MANIFEST = (
    ROOT / "tests/fixtures/reconstruction-runtime/occom-moses-paul-execution-sermon.source-manifest.json"
)
SOURCE_SHA256 = "56d612750fed73102ec0daa1afbbd9182cfe3660275f957fb535fd86d11a3d1a"
WORK_ID = "occom-moses-paul-execution-sermon"
PAGE_MILESTONES_SHA256 = (
    "e114466b2a7f7ce8088c1b8dbf5591260befb5c56445ac39fd3c3d9cd48ec155"
)
TEI = {"tei": "http://www.tei-c.org/ns/1.0"}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


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


def _assert_oracle_rejects(
    source: SourceManifest, candidate: CandidatePackage
) -> None:
    with pytest.raises(ValueError, match="^candidate validation failed$"):
        validate(source, candidate, _oracle)


@pytest.fixture(scope="module")
def verified_candidate(tmp_path_factory: pytest.TempPathFactory):
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    candidate = reconstruct(
        source, tmp_path_factory.mktemp("occom-candidate") / "package", _convert
    )
    report = validate(source, candidate, _oracle)
    assert report.status == "pass"
    return source, candidate, report


def test_exact_retained_source_identity_and_complete_census() -> None:
    content = SOURCE.read_bytes()
    tree = etree.fromstring(
        content,
        etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True),
    )
    elements = list(tree.iter())

    assert len(content) == 79_299
    assert _sha(content) == SOURCE_SHA256
    assert tree.xpath(
        "string(/tei:TEI/tei:teiHeader//tei:idno[@type='TCP'])", namespaces=TEI
    ) == "N09814"
    assert tree.xpath(
        "string(/tei:TEI/tei:teiHeader//tei:titleStmt/tei:author)", namespaces=TEI
    ) == "Occom, Samson, 1723-1792."
    assert "execution of Moses Paul" in tree.xpath(
        "string(/tei:TEI/tei:teiHeader//tei:titleStmt/tei:title)", namespaces=TEI
    )
    assert len(elements) == 418
    assert sum(len(element.attrib) for element in elements) == 276
    assert sum(element.text is not None for element in elements) == 233
    assert sum(element.tail is not None for element in elements) == 417
    assert sum(
        len((element.text or "") + (element.tail or "")) for element in elements
    ) == 67_353


def test_candidate_is_byte_exact_nonaccepted_and_fully_accounted(
    verified_candidate,
) -> None:
    source, candidate, report = verified_candidate
    source_bytes = SOURCE.read_bytes()
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))

    assert candidate.manifest["status"] == "nonaccepted"
    assert source.record["work_id"] == WORK_ID
    assert candidate.member_bytes("content.tei.xml") == source_bytes
    assert accountability["source_content_bytes"] == 79_299
    assert accountability["candidate_content_bytes"] == 79_299
    assert accountability["source_content_sha256"] == SOURCE_SHA256
    assert accountability["candidate_content_sha256"] == SOURCE_SHA256
    assert accountability["omitted_elements"] == 0
    assert accountability["duplicated_elements"] == 0
    assert accountability["unresolved_elements"] == 0
    assert len(accountability["page_milestones"]) == 32
    assert accountability["unique_facsimile_targets"] == 18
    assert accountability["page_milestones_sha256"] == PAGE_MILESTONES_SHA256
    assert accountability["page_milestones"][3:7] == [
        {
            "ordinal": 4,
            "n": None,
            "facs": "unknown:012494_0003_0F8A901D6B213E98",
        },
        {
            "ordinal": 5,
            "n": None,
            "facs": "unknown:012494_0003_0F8A901D6B213E98",
        },
        {
            "ordinal": 6,
            "n": "6",
            "facs": "unknown:012494_0004_0F8A901D938350C8",
        },
        {
            "ordinal": 7,
            "n": "7",
            "facs": "unknown:012494_0004_0F8A901D938350C8",
        },
    ]
    assert {
        name: accountability["element_counts"][name]
        for name in ("TEI", "div", "floatingText", "g", "gap", "l", "lg", "pb")
    } == {
        "TEI": 1,
        "div": 6,
        "floatingText": 2,
        "g": 156,
        "gap": 17,
        "l": 8,
        "lg": 2,
        "pb": 32,
    }
    unresolved = [
        json.loads(line)
        for line in candidate.member_bytes("unresolved.jsonl").splitlines()
    ]
    assert [row["status"] for row in unresolved] == ["unresolved"] * 3
    assert report.findings == ()


def test_oracle_rejects_resealed_text_mutation(
    verified_candidate, tmp_path: Path
) -> None:
    source, candidate, _ = verified_candidate
    target = _clone_candidate(candidate, tmp_path / "mutated-text")
    content = candidate.member_bytes("content.tei.xml")
    assert b"execution of Moses Paul" in content
    resealed = _reseal_member(
        target,
        "content.tei.xml",
        content.replace(b"execution of Moses Paul", b"execution of Moses Pau1", 1),
    )

    _assert_oracle_rejects(source, resealed)


def test_oracle_rejects_resealed_facsimile_ordinal_mutation(
    verified_candidate, tmp_path: Path
) -> None:
    source, candidate, _ = verified_candidate
    target = _clone_candidate(candidate, tmp_path / "mutated-facsimile-order")
    content = candidate.member_bytes("content.tei.xml")
    first = b"unknown:012494_0000_0F8A901693B1A428"
    second = b"unknown:012494_0001_0F8A9016C980C510"
    assert content.count(first) == 1
    assert content.count(second) == 1
    swapped = content.replace(first, b"__OCCOM_FACSIMILE_SWAP__", 1)
    swapped = swapped.replace(second, first, 1)
    swapped = swapped.replace(b"__OCCOM_FACSIMILE_SWAP__", second, 1)
    resealed = _reseal_member(target, "content.tei.xml", swapped)

    _assert_oracle_rejects(source, resealed)


@pytest.mark.parametrize("mutation", ["omit", "alter", "extra"])
def test_oracle_rejects_unresolved_ledger_mutations(
    verified_candidate, tmp_path: Path, mutation: str
) -> None:
    source, candidate, _ = verified_candidate
    target = _clone_candidate(candidate, tmp_path / f"unresolved-{mutation}")
    rows = [
        json.loads(line)
        for line in candidate.member_bytes("unresolved.jsonl").splitlines()
    ]
    if mutation == "omit":
        rows.pop(1)
    elif mutation == "alter":
        rows[1]["status"] = "resolved"
    else:
        rows.append(dict(rows[0]))
    resealed = _reseal_member(
        target, "unresolved.jsonl", b"".join(_canonical(row) for row in rows)
    )

    _assert_oracle_rejects(source, resealed)


@pytest.mark.parametrize(
    ("member_name", "old", "new"),
    [
        ("provenance.json", b'"date":"1772"', b'"date":"1773"'),
        (
            "source-accountability.json",
            b'"omitted_elements":0',
            b'"omitted_elements":1',
        ),
        ("README.source.md", b"N09814", b"N0981X"),
    ],
)
def test_oracle_rejects_nontext_member_mutations(
    verified_candidate,
    tmp_path: Path,
    member_name: str,
    old: bytes,
    new: bytes,
) -> None:
    source, candidate, _ = verified_candidate
    target = _clone_candidate(candidate, tmp_path / member_name.replace(".", "-"))
    content = candidate.member_bytes(member_name)
    assert old in content
    resealed = _reseal_member(target, member_name, content.replace(old, new, 1))

    _assert_oracle_rejects(source, resealed)


@pytest.mark.parametrize(
    ("field_path", "replacement"),
    [
        (("status",), "accepted"),
        (("source_id",), "wrong-source"),
        (("source_manifest", "sha256"), "0" * 64),
        (("source_manifest", "path"), "sources/structured-text/occom-moses-paul-execution-sermon/occom-moses-paul-execution-sermon.source-manifest.json"),
        (("converter", "version"), "wrong-version"),
        (("package_schema", "sha256"), "0" * 64),
    ],
)
def test_oracle_rejects_candidate_manifest_binding_mutations(
    verified_candidate,
    tmp_path: Path,
    field_path: tuple[str, ...],
    replacement: str,
) -> None:
    source, candidate, _ = verified_candidate
    target = _clone_candidate(candidate, tmp_path / ("manifest-" + "-".join(field_path)))
    manifest_path = target / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    owner = manifest
    for key in field_path[:-1]:
        owner = owner[key]
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
    expected = {
        ROOT / "build/tei/occom_moses_paul_execution_sermon_oracle.py",
        ROOT / "ocd_kernel/__init__.py",
        ROOT / "ocd_kernel/reconstruction/__init__.py",
        ROOT / "ocd_kernel/reconstruction/contract.py",
    }
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)

    assert set(_closure_paths()) == expected
    assert source.record["validator"]["import_closure_sha256"] == _closure_digest()


def test_candidate_is_tei_p5_valid_and_keeps_source_structure(
    verified_candidate,
) -> None:
    _, candidate, _ = verified_candidate
    tree = etree.fromstring(
        candidate.member_bytes("content.tei.xml"),
        etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True),
    )
    schema = compiled_tei_schema(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd")

    assert schema.validate(tree), str(schema.error_log)
    assert len(tree.xpath("//tei:floatingText", namespaces=TEI)) == 2
    assert len(tree.xpath("//tei:div[@type='address']", namespaces=TEI)) == 2
    assert len(tree.xpath("//tei:lg", namespaces=TEI)) == 2
    assert len(tree.xpath("//tei:l", namespaces=TEI)) == 8
    assert len(tree.xpath("//tei:pb", namespaces=TEI)) == 32
    assert len(tree.xpath("//tei:gap", namespaces=TEI)) == 17
    assert len(tree.xpath("//tei:g", namespaces=TEI)) == 156
    assert "".join(tree.itertext()).count("ſ") == 1_594


def test_fresh_process_from_different_cwd_is_byte_identical(
    verified_candidate, tmp_path: Path
) -> None:
    _, candidate, _ = verified_candidate
    output = tmp_path / "fresh-package"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    command = (
        "from pathlib import Path;"
        "from ocd_kernel.reconstruction import SourceManifest,reconstruct;"
        "from build.tei.occom_moses_paul_execution_sermon_reconstruction import _convert;"
        f"r=Path({str(ROOT)!r});"
        f"m=Path({str(MANIFEST)!r});"
        "s=SourceManifest.load(m,repository_root=r);"
        "reconstruct(s,Path(__import__('sys').argv[1]),_convert)"
    )
    run = subprocess.run(
        [sys.executable, "-c", command, str(output)],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert run.returncode == 0, run.stderr
    fresh = CandidatePackage.load(output)
    assert fresh.sha256 == candidate.sha256
    assert all(
        fresh.member_bytes(name) == candidate.member_bytes(name)
        for name in candidate.member_names
    )
