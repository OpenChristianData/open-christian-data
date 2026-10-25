from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import pytest

from build.tei.luthers_large_catechism_oracle import _oracle
from build.tei.luthers_large_catechism_reconstruction import _convert
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, reconstruct, validate


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'tests/fixtures/reconstruction-runtime/luthers_large_catechism_oracle.source-manifest.json'


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


@pytest.fixture(scope="session")
def catechism_manifest() -> SourceManifest:
    return SourceManifest.load(MANIFEST, repository_root=ROOT)


@pytest.fixture(scope="session")
def catechism_candidate(
    tmp_path_factory: pytest.TempPathFactory,
    catechism_manifest: SourceManifest,
) -> CandidatePackage:
    return reconstruct(catechism_manifest, tmp_path_factory.mktemp("lib077-candidate") / "package", _convert)


def _reseal(path: Path, name: str, content: bytes) -> CandidatePackage:
    (path / name).write_bytes(content)
    manifest = json.loads((path / "manifest.json").read_bytes())
    member = next(item for item in manifest["members"] if item["name"] == name)
    member["bytes"] = len(content)
    member["sha256"] = hashlib.sha256(content).hexdigest()
    (path / "manifest.json").write_bytes(_canonical(manifest))
    return CandidatePackage.load(path)


def test_manifest_binds_the_complete_retained_gutenberg_member(
    catechism_manifest: SourceManifest,
) -> None:
    record = catechism_manifest.record
    assert record["source_bundle"] == {
        "members": 1,
        "bytes": 288656,
        "sha256": "0e5df44eea431ef1ebaf222b2802a2fd61cbe1468bea0923085bc95797dc0b43",
    }
    assert record["source_members"][0]["path"] == "raw/gutenberg/pg1722.txt"
    assert record["source_members"][0]["lines"] == 4886
    assert record["scope"]["represented_lines"] == 4886


def test_candidate_is_lossless_and_independently_validated(
    catechism_manifest: SourceManifest,
    catechism_candidate: CandidatePackage,
) -> None:
    accountability = json.loads(catechism_candidate.member_bytes("source-accountability.json"))
    assert accountability["physical_lines"] == accountability["represented_lines"] == 4886
    assert accountability["omitted_lines"] == accountability["duplicated_lines"] == 0
    assert len(accountability["crosswalk"]) == 4886
    assert [item["line"] for item in accountability["crosswalk"] if item["kind"] == "part"] == [409, 2571, 3003, 3772]
    report = validate(catechism_manifest, catechism_candidate, _oracle)
    assert report.status == "pass"
    assert report.findings == ()
    assert report.attestation["findings"] == ()


@pytest.mark.parametrize("member_name", ["source-accountability.json", "content.tei.xml"])
def test_oracle_rejects_resealed_mutation(
    tmp_path: Path,
    catechism_manifest: SourceManifest,
    catechism_candidate: CandidatePackage,
    member_name: str,
) -> None:
    destination = tmp_path / member_name.replace(".", "-")
    shutil.copytree(catechism_candidate.path, destination)
    content = (destination / member_name).read_bytes()
    if member_name == "source-accountability.json":
        value = json.loads(content)
        value["crosswalk"][100]["text_sha256"] = "0" * 64
        content = _canonical(value)
    else:
        content = content.replace(b"Part First.", b"Part Xirst.", 1)
        assert content != (destination / member_name).read_bytes()
    mutated = _reseal(destination, member_name, content)
    with pytest.raises(ValueError, match="candidate validation failed"):
        validate(catechism_manifest, mutated, _oracle)

