from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import pytest

from build.tei.schaff_history_vol5_oracle import _oracle
from build.tei.schaff_history_vol5_reconstruction import _convert
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, reconstruct, validate


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'tests/fixtures/reconstruction-runtime/schaff_history_vol5_oracle.source-manifest.json'


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


@pytest.fixture(scope="session")
def schaff_manifest() -> SourceManifest:
    return SourceManifest.load(MANIFEST, repository_root=ROOT)


@pytest.fixture(scope="session")
def schaff_candidate(tmp_path_factory: pytest.TempPathFactory, schaff_manifest: SourceManifest) -> CandidatePackage:
    return reconstruct(schaff_manifest, tmp_path_factory.mktemp("lib058-candidate") / "package", _convert)


def _reseal(path: Path, name: str, content: bytes) -> CandidatePackage:
    (path / name).write_bytes(content)
    manifest = json.loads((path / "manifest.json").read_bytes())
    member = next(item for item in manifest["members"] if item["name"] == name)
    member["bytes"] = len(content)
    member["sha256"] = hashlib.sha256(content).hexdigest()
    (path / "manifest.json").write_bytes(_canonical(manifest))
    return CandidatePackage.load(path)


def test_manifest_binds_the_complete_retained_ccel_member(schaff_manifest: SourceManifest) -> None:
    record = schaff_manifest.record
    assert record["source_bundle"] == {"members": 1, "bytes": 2307663, "sha256": "35b199838ed7c4afa70417534d97b37e544d8f75c071426eddbd50cb593f06ab"}
    assert record["source_members"][0]["path"] == "raw/ccel/schaff/hcc5.xml"
    assert record["source_members"][0]["lines"] == 35311
    assert record["scope"]["represented_lines"] == 35311


def test_candidate_is_lossless_and_independently_validated(schaff_manifest: SourceManifest, schaff_candidate: CandidatePackage) -> None:
    accountability = json.loads(schaff_candidate.member_bytes("source-accountability.json"))
    assert accountability["physical_lines"] == accountability["represented_lines"] == 35311
    assert accountability["omitted_lines"] == accountability["duplicated_lines"] == 0
    assert accountability["source_structure"]["body_top_level"][1]["elements"] == 11574
    assert accountability["source_structure"]["content_sections"] == 2
    assert accountability["source_structure"]["content_chapters"] == 16
    assert accountability["source_structure"]["tag_counts"]["note"] == 2163
    assert len(accountability["crosswalk"]) == 35311
    report = validate(schaff_manifest, schaff_candidate, _oracle)
    assert report.status == "pass"
    assert report.findings == ()
    assert report.attestation["findings"] == ()


@pytest.mark.parametrize("member_name", ["source-accountability.json", "content.tei.xml"])
def test_oracle_rejects_resealed_mutation(tmp_path: Path, schaff_manifest: SourceManifest, schaff_candidate: CandidatePackage, member_name: str) -> None:
    destination = tmp_path / member_name.replace(".", "-")
    shutil.copytree(schaff_candidate.path, destination)
    content = (destination / member_name).read_bytes()
    if member_name == "source-accountability.json":
        value = json.loads(content)
        value["crosswalk"][100]["text_sha256"] = "0" * 64
        content = _canonical(value)
    else:
        content = content.replace(b"<?xml version='1.0'", b"<?xml version='9.9'", 1)
        assert content != (destination / member_name).read_bytes()
    mutated = _reseal(destination, member_name, content)
    with pytest.raises(ValueError, match="candidate validation failed"):
        validate(schaff_manifest, mutated, _oracle)
