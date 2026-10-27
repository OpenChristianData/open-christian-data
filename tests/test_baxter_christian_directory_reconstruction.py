from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from lxml import etree
import pytest

from build.tei.baxter_christian_directory_oracle import (
    _closure_digest,
    _closure_paths,
    _oracle,
)
from build.tei.baxter_christian_directory_reconstruction import _convert
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, reconstruct, validate
from build.lib.tei_xsd import compiled_tei_schema


ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(
    r"D:\Library\Open Christian Data\raw\clean-ready-acquisition-to-tei\master-2\14"
    r"\baxter-christian-directory\A26892.xml"
)
MANIFEST = (
    ROOT / 'tests/fixtures/reconstruction-runtime/baxter_christian_directory_oracle.source-manifest.json'
)
SOURCE_SHA256 = "1b90e060921164cb2486d938c653640537cb710e8b1889c48a0e10f5e515035e"
TEI = {"tei": "http://www.tei-c.org/ns/1.0"}
SOURCE_LOCAL_GOVERNED_TEXT = (
    MANIFEST,
    ROOT / "sources/structured-text/baxter-christian-directory/README.md",
    ROOT / "sources/structured-text/baxter-christian-directory/baxter-christian-directory.reconstruction-profile.json",
    ROOT / "sources/structured-text/baxter-christian-directory/baxter-christian-directory.validation-policy.json",
    ROOT / "build/tei/baxter_christian_directory_reconstruction.py",
    ROOT / "build/tei/baxter_christian_directory_oracle.py",
    Path(__file__).resolve(),
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def test_baxter_source_local_governed_text_materializes_as_canonical_lf() -> None:
    record = json.loads(MANIFEST.read_bytes())
    authorities = {item["name"]: item for item in record["authorities"]}

    for path in SOURCE_LOCAL_GOVERNED_TEXT:
        content = path.read_bytes()
        assert content.endswith(b"\n"), path
        assert b"\r" not in content, path

    for name in (
        "source-local-attribution-readme",
        "reconstruction-profile",
        "validation-policy",
    ):
        authority = authorities[name]
        content = ROOT.joinpath(authority["path"]).read_bytes()
        assert len(content) == authority["bytes"]
        assert _sha(content) == authority["sha256"]
    assert _sha(
        ROOT.joinpath(record["converter"]["implementation_path"]).read_bytes()
    ) == record["converter"]["implementation_sha256"]
    assert _sha(
        ROOT.joinpath(record["validator"]["implementation_path"]).read_bytes()
    ) == record["validator"]["implementation_sha256"]


def test_manifest_binds_complete_retained_support_boundary() -> None:
    record = json.loads(MANIFEST.read_bytes())
    retained = {
        item["name"]: {
            key: item[key] for key in ("path", "role", "bytes", "sha256")
        }
        for item in record["authorities"]
        if item["path"].startswith(
            "raw/clean-ready-acquisition-to-tei/master-2/14/baxter-christian-directory/"
        )
    }
    assert retained == {
        "retained-tei-p5": {
            "path": "raw/clean-ready-acquisition-to-tei/master-2/14/baxter-christian-directory/A26892.xml",
            "role": "primary-source",
            "bytes": 9_504_938,
            "sha256": SOURCE_SHA256,
        },
        "source-http-headers": {
            "path": "raw/clean-ready-acquisition-to-tei/master-2/14/baxter-christian-directory/A26892.xml.http-headers.txt",
            "role": "source-retrieval-evidence",
            "bytes": 929,
            "sha256": "cc225d8b0111e41b2634a2484f9d04bd7eb9a1a100379b92822638d177857fdb",
        },
        "upstream-cc0-license": {
            "path": "raw/clean-ready-acquisition-to-tei/master-2/14/baxter-christian-directory/LICENSE.CC0-1.0.txt",
            "role": "source-rights-evidence",
            "bytes": 6_555,
            "sha256": "36ffd9dc085d529a7e60e1276d73ae5a030b020313e6c5408593a6ae2af39673",
        },
        "upstream-cc0-license-http-headers": {
            "path": "raw/clean-ready-acquisition-to-tei/master-2/14/baxter-christian-directory/LICENSE.CC0-1.0.txt.http-headers.txt",
            "role": "source-rights-retrieval-evidence",
            "bytes": 924,
            "sha256": "2bca163d63a53703dbccf40cf7169769e025f874b726b0ac185cd4e23501437f",
        },
        "upstream-readme": {
            "path": "raw/clean-ready-acquisition-to-tei/master-2/14/baxter-christian-directory/README.upstream.md",
            "role": "source-rights-and-version-evidence",
            "bytes": 91_021,
            "sha256": "cc1028ec01adb240704f77244d4925951095eb6b91270f543bb1b9d2c7833d4f",
        },
        "upstream-readme-http-headers": {
            "path": "raw/clean-ready-acquisition-to-tei/master-2/14/baxter-christian-directory/README.upstream.md.http-headers.txt",
            "role": "source-rights-version-retrieval-evidence",
            "bytes": 926,
            "sha256": "9e3c431f97be6a7534638b0674d936d6f0016022198acdeea3e80f0735e66ee8",
        },
        "upstream-commit": {
            "path": "raw/clean-ready-acquisition-to-tei/master-2/14/baxter-christian-directory/upstream-commit.json",
            "role": "source-version-evidence",
            "bytes": 98_243,
            "sha256": "b40420be1878bbab914cebc10b60cb1582a49a2742712088e822e4e6563e201b",
        },
        "upstream-contents": {
            "path": "raw/clean-ready-acquisition-to-tei/master-2/14/baxter-christian-directory/upstream-contents.json",
            "role": "source-member-inventory-evidence",
            "bytes": 2_204,
            "sha256": "341bfc39e55edc03b88b1b0885334fa0bfebff0491f9a9b8a89d87a10d64762c",
        },
    }
    assert [item["role"] for item in retained.values()].count("primary-source") == 1


def _clone_candidate(candidate: CandidatePackage, target: Path) -> Path:
    target.mkdir()
    for name in candidate.member_names:
        (target / name).write_bytes(candidate.member_bytes(name))
    return target


def _reseal_member(path: Path, member_name: str, content: bytes) -> CandidatePackage:
    member_path = path / member_name
    member_path.write_bytes(content)
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    member = next(item for item in manifest["members"] if item["name"] == member_name)
    member.update(bytes=len(content), sha256=_sha(content))
    manifest_path.write_bytes(_canonical(manifest))
    return CandidatePackage.load(path)


def _assert_oracle_rejects(source: SourceManifest, candidate: CandidatePackage) -> None:
    with pytest.raises(ValueError, match="candidate validation failed"):
        validate(source, candidate, _oracle)


@pytest.fixture(scope="module")
def verified_candidate(tmp_path_factory: pytest.TempPathFactory):
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    candidate = reconstruct(
        source, tmp_path_factory.mktemp("baxter-candidate") / "package", _convert
    )
    report = validate(source, candidate, _oracle)
    assert report.status == "pass"
    return source, candidate, report


def test_exact_retained_source_identity_rights_and_complete_census() -> None:
    content = SOURCE.read_bytes()
    tree = etree.fromstring(
        content,
        etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True),
    )
    elements = list(tree.iter())

    assert len(content) == 9_504_938
    assert _sha(content) == SOURCE_SHA256
    assert tree.xpath("string(/tei:TEI/tei:teiHeader//tei:idno[@type='DLPS'])", namespaces=TEI) == "A26892"
    assert tree.xpath("string(/tei:TEI/tei:teiHeader//tei:titleStmt/tei:author)", namespaces=TEI) == "Baxter, Richard, 1615-1691."
    assert tree.xpath("string(/tei:TEI/tei:teiHeader//tei:sourceDesc//tei:date)", namespaces=TEI) == "1673."
    availability = " ".join(tree.xpath("string(/tei:TEI/tei:teiHeader//tei:availability)", namespaces=TEI).split())
    assert "Creative Commons 0 1.0 Universal" in availability
    assert len(elements) == 111_974
    assert sum(len(element.attrib) for element in elements) == 50_129
    assert sum(element.text is not None for element in elements) == 98_708
    assert sum(element.tail is not None for element in elements) == 111_973
    assert sum(len((element.text or "") + (element.tail or "")) for element in elements) == 7_580_767


def test_candidate_is_byte_exact_nonaccepted_and_fully_accounted(
    verified_candidate,
) -> None:
    _, candidate, report = verified_candidate
    source_bytes = SOURCE.read_bytes()

    assert candidate.manifest["status"] == "nonaccepted"
    assert candidate.member_bytes("content.tei.xml") == source_bytes
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    assert accountability["projection"] == "exact-source-bytes-v1"
    assert accountability["source_content_bytes"] == accountability["candidate_content_bytes"] == len(source_bytes)
    assert accountability["source_content_sha256"] == accountability["candidate_content_sha256"] == SOURCE_SHA256
    assert accountability["omitted_elements"] == 0
    assert accountability["duplicated_elements"] == 0
    assert accountability["unresolved_elements"] == 0
    expected_feature_counts = {
        "TEI": 1,
        "body": 2,
        "div": 502,
        "floatingText": 1,
        "front": 1,
        "g": 12_906,
        "gap": 9_556,
        "head": 582,
        "hi": 61_780,
        "item": 957,
        "list": 149,
        "note": 5_329,
        "p": 8_896,
        "pb": 1_258,
        "text": 1,
    }
    assert {
        name: accountability["element_counts"][name]
        for name in expected_feature_counts
    } == expected_feature_counts
    unresolved = [
        json.loads(line)
        for line in candidate.member_bytes("unresolved.jsonl").splitlines()
    ]
    assert [row["id"] for row in unresolved] == [
        "baxter-a26892-imperfect-print-witness",
        "baxter-a26892-keying-and-print-collation",
        "baxter-a26892-human-rights-editorial-publication",
    ]
    assert [row["status"] for row in unresolved] == ["unresolved"] * 3
    assert report.findings == ()


def test_producer_independent_oracle_rejects_resealed_text_mutation(
    verified_candidate, tmp_path: Path
) -> None:
    source, candidate, _ = verified_candidate
    mutated = _clone_candidate(candidate, tmp_path / "mutated")
    content_path = mutated / "content.tei.xml"
    content = content_path.read_bytes()
    resealed = _reseal_member(
        mutated,
        "content.tei.xml",
        content.replace(b"A Christian Directory", b"A Christian Direct0ry", 1),
    )

    _assert_oracle_rejects(source, resealed)


@pytest.mark.parametrize("mutation", ["omit", "alter", "extra"])
def test_oracle_rejects_unresolved_ledger_mutations(
    verified_candidate, tmp_path: Path, mutation: str
) -> None:
    source, candidate, _ = verified_candidate
    target = _clone_candidate(candidate, tmp_path / f"unresolved-{mutation}")
    rows = [json.loads(line) for line in candidate.member_bytes("unresolved.jsonl").splitlines()]
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
        ("provenance.json", b'"date":"1673"', b'"date":"1674"'),
        (
            "source-accountability.json",
            b'"omitted_elements":0',
            b'"omitted_elements":1',
        ),
        ("README.source.md", b"A26892", b"A2689X"),
    ],
)
def test_oracle_rejects_complete_nontext_member_mutations(
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
        (("converter", "version"), "wrong-version"),
        (("converter", "implementation_sha256"), "0" * 64),
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
    target = _clone_candidate(
        candidate, tmp_path / ("manifest-" + "-".join(field_path))
    )
    manifest_path = target / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    owner = manifest
    for key in field_path[:-1]:
        owner = owner[key]
    owner[field_path[-1]] = replacement
    manifest_path.write_bytes(_canonical(manifest))

    mutated = CandidatePackage.load(target)
    if field_path in {("source_id",), ("source_manifest", "sha256")}:
        # Shared source binding is checked before the work-specific oracle.
        with pytest.raises(
            ValueError, match="^candidate source manifest binding mismatch$"
        ):
            validate(source, mutated, _oracle)
    else:
        _assert_oracle_rejects(source, mutated)


def test_oracle_import_closure_is_complete_and_manifest_bound() -> None:
    expected = {
        ROOT / "build/tei/baxter_christian_directory_oracle.py",
        ROOT / "ocd_kernel/__init__.py",
        ROOT / "ocd_kernel/reconstruction/__init__.py",
        ROOT / "ocd_kernel/reconstruction/contract.py",
    }
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)

    assert set(_closure_paths()) == expected
    assert source.record["validator"]["import_closure_sha256"] == _closure_digest()


def test_candidate_is_tei_p5_xsd_valid_and_keeps_structural_features(
    verified_candidate,
) -> None:
    _, candidate, _ = verified_candidate
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    tree = etree.fromstring(candidate.member_bytes("content.tei.xml"), parser)
    schema = compiled_tei_schema(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd")

    assert schema.validate(tree), str(schema.error_log)
    assert len(tree.xpath("//tei:front", namespaces=TEI)) == 1
    assert len(tree.xpath("//tei:floatingText", namespaces=TEI)) == 1
    assert len(tree.xpath("//tei:list", namespaces=TEI)) == 149
    assert len(tree.xpath("//tei:note", namespaces=TEI)) == 5_329
    assert len(tree.xpath("//tei:pb", namespaces=TEI)) == 1_258
    assert len(tree.xpath("//tei:gap", namespaces=TEI)) == 9_556
    assert len(tree.xpath("//tei:g", namespaces=TEI)) == 12_906
    assert any(element.tail for element in tree.iter())
    assert "FINIS." in "".join(tree.xpath("//tei:trailer//text()", namespaces=TEI))


def test_repeated_page_facsimile_milestones_preserve_physical_ordinal_identity(
    verified_candidate,
) -> None:
    _, candidate, _ = verified_candidate
    tree = etree.fromstring(
        candidate.member_bytes("content.tei.xml"),
        etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True),
    )
    milestones = tree.xpath("//tei:pb", namespaces=TEI)
    assert [item.get("facs") for item in milestones] == [
        f"tcp:64451:{page}" for page in range(1, 630) for _ in range(2)
    ]
    assert milestones[0].attrib == {"facs": "tcp:64451:1"}
    assert milestones[1].attrib == {
        "facs": "tcp:64451:1",
        "rendition": "simple:additions",
    }
    assert milestones[-2].attrib == {"n": "214", "facs": "tcp:64451:629"}
    assert milestones[-1].attrib == {"facs": "tcp:64451:629"}


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
        "from build.tei.baxter_christian_directory_reconstruction import _convert;"
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
    assert all(fresh.member_bytes(name) == candidate.member_bytes(name) for name in candidate.member_names)
