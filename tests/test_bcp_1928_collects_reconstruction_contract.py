from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import pytest

from build.tei.bcp_1928_oracle import _oracle
from build.tei.bcp_1928_reconstruction import _convert
from ocd_kernel.reconstruction.contract import (
    CandidatePackage,
    SourceManifest,
    reconstruct,
    validate,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'tests/fixtures/reconstruction-runtime/bcp-1928-collects.source-manifest.json'


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


@pytest.fixture(scope="session")
def bcp_source_manifest() -> SourceManifest:
    return SourceManifest.load(MANIFEST, repository_root=ROOT)


@pytest.fixture(scope="session")
def bcp_candidate(
    tmp_path_factory: pytest.TempPathFactory,
    bcp_source_manifest: SourceManifest,
) -> CandidatePackage:
    destination = tmp_path_factory.mktemp("bcp-1928-candidate") / "package"
    return reconstruct(bcp_source_manifest, destination, _convert)


def _reseal(path: Path, member_name: str, content: bytes) -> CandidatePackage:
    (path / member_name).write_bytes(content)
    manifest = json.loads((path / "manifest.json").read_bytes())
    for member in manifest["members"]:
        if member["name"] == member_name:
            member["bytes"] = len(content)
            member["sha256"] = hashlib.sha256(content).hexdigest()
            break
    else:
        raise AssertionError(f"candidate member not found: {member_name}")
    (path / "manifest.json").write_bytes(_canonical(manifest))
    return CandidatePackage.load(path)


def test_manifest_binds_retained_scope_and_unresolved_claims(
    bcp_source_manifest: SourceManifest,
) -> None:
    record = bcp_source_manifest.record
    assert record["source_bundle"] == {
        "members": 100,
        "bytes": 1042052,
        "sha256": "92aa35e04b6b64c583e444d300b56ad98a8b56228fa8d9582763b8dc0f6f9c06",
    }
    assert len(record["source_members"]) == 100
    assert record["scope"]["unbound_manual_claims"] == ("trinity23", "trinity24")


def test_candidate_validates_against_independent_source_oracle(
    bcp_source_manifest: SourceManifest,
    bcp_candidate: CandidatePackage,
) -> None:
    accountability = json.loads(bcp_candidate.member_bytes("source-accountability.json"))
    assert len(accountability["records"]) == 100
    assert accountability["pages_without_collect"] == ["Trinity23.html", "Trinity24.html"]
    report = validate(bcp_source_manifest, bcp_candidate, _oracle)
    assert report.status == "pass"
    assert report.findings == ()
    assert report.attestation["findings"] == ()


@pytest.mark.parametrize("member_name", ["source-accountability.json", "content.tei.xml"])
def test_oracle_rejects_resealed_text_mutation(
    tmp_path: Path,
    bcp_source_manifest: SourceManifest,
    bcp_candidate: CandidatePackage,
    member_name: str,
) -> None:
    destination = tmp_path / member_name.replace(".", "-")
    shutil.copytree(bcp_candidate.path, destination)
    content = (destination / member_name).read_bytes()
    if member_name == "source-accountability.json":
        accountability = json.loads(content)
        accountability["records"][0]["text"] += " mutation"
        content = _canonical(accountability)
    else:
        content = content.replace(b"ALMIGHTY", b"ALMIGHtY", 1)
        assert content != (destination / member_name).read_bytes()
    mutated = _reseal(destination, member_name, content)
    with pytest.raises(ValueError, match="candidate validation failed"):
        validate(bcp_source_manifest, mutated, _oracle)

