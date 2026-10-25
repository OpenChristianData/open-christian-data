"""Bounded contract tests for the ticket-local Ryle Holiness route."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
from jsonschema import Draft202012Validator
from lxml import etree

from build.tei import ryle_holiness_oracle as oracle
from build.tei import ryle_holiness_reconstruction as producer
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, reconstruct, validate
from ocd_kernel.tei.validate import compiled_schema


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / 'tests/fixtures/reconstruction-runtime/puritan-ryle-holiness.source-manifest.json'


@pytest.fixture(scope="module")
def source_manifest() -> SourceManifest:
    return SourceManifest.load(MANIFEST_PATH, repository_root=ROOT)


@pytest.fixture(scope="module")
def candidate(source_manifest: SourceManifest, tmp_path_factory: pytest.TempPathFactory) -> CandidatePackage:
    destination = tmp_path_factory.mktemp("ryle-candidate") / "package"
    return reconstruct(source_manifest, destination, producer._convert)


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _reseal(package: Path, member_name: str | None = None) -> None:
    manifest_path = package / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if member_name is not None:
        for member in manifest["members"]:
            if member["name"] == member_name:
                content = (package / member_name).read_bytes()
                member["bytes"] = len(content)
                member["sha256"] = hashlib.sha256(content).hexdigest()
                break
        else:
            raise AssertionError(member_name)
    manifest_path.write_bytes(_canonical(manifest))


def _mutated_package(base: CandidatePackage, root: Path, mutation: str) -> CandidatePackage:
    package = root / mutation
    shutil.copytree(base.path, package)
    if mutation == "accountability":
        record = json.loads((package / "source-accountability.json").read_text(encoding="utf-8"))
        record["features"][100]["source_direct_text"] += "X"
        (package / "source-accountability.json").write_bytes(_canonical(record))
        _reseal(package, "source-accountability.json")
    elif mutation == "content":
        content = (package / "content.tei.xml").read_bytes()
        old = b"There is not a brick"
        assert old in content
        (package / "content.tei.xml").write_bytes(content.replace(old, b"There is not a bricK", 1))
        _reseal(package, "content.tei.xml")
    elif mutation == "ledger":
        content = (package / "content.tei.xml").read_bytes()
        old = b'type="direct-text">'
        assert old in content
        (package / "content.tei.xml").write_bytes(content.replace(old, old + b"X", 1))
        _reseal(package, "content.tei.xml")
    elif mutation == "embedded-source":
        content = (package / "content.tei.xml").read_bytes()
        needle = base64.b64encode((ROOT / "raw/ccel/ryle/holiness.xml").read_bytes())
        position = content.find(needle)
        assert position >= 0
        (package / "content.tei.xml").write_bytes(content[:position] + b"Q" + content[position + 1 :])
        _reseal(package, "content.tei.xml")
    elif mutation == "provenance":
        record = json.loads((package / "provenance.json").read_text(encoding="utf-8"))
        record["source_id"] = "wrong-source"
        (package / "provenance.json").write_bytes(_canonical(record))
        _reseal(package, "provenance.json")
    elif mutation == "manifest-binding":
        record = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
        record["source_manifest"]["sha256"] = "0" * 64
        (package / "manifest.json").write_bytes(_canonical(record))
    else:
        raise AssertionError(mutation)
    return CandidatePackage.load(package)


def test_exact_source_accounting_and_manifest_binding(source_manifest: SourceManifest) -> None:
    source_manifest.verify()
    source = source_manifest.authority_path("retained-ryle-holiness").read_bytes()
    assert len(source) == 1_302_437
    assert hashlib.sha256(source).hexdigest() == "20f9c4a6eb9109c5981a37b580376ed02f1bc93ac98dd047ac6d0578ff3521c8"
    root = producer._parse(source)
    counts, census = producer._census(root)
    profile = json.loads(source_manifest.authority_path("reconstruction-profile").read_text(encoding="utf-8"))
    assert counts == profile["element_counts"]
    assert census == profile["source_census"]
    assert len(producer._features(root)) == 5698
    policy = json.loads(source_manifest.authority_path("validation-policy").read_text(encoding="utf-8"))
    assert oracle._closure_digest(ROOT, policy) == source_manifest.record["validator"]["import_closure_sha256"]


def test_candidate_passes_independent_accounting_and_tei_schema(
    source_manifest: SourceManifest, candidate: CandidatePackage
) -> None:
    report = validate(source_manifest, candidate, oracle._oracle)
    assert report.status == "pass"
    assert report.findings == ()
    account = json.loads(candidate.member_bytes("source-accountability.json"))
    assert account["represented_element_count"] == 5666
    assert account["formatting_only_excluded_element_count"] == 32
    Draft202012Validator(json.loads(source_manifest.authority_path("source-accountability-schema").read_text(encoding="utf-8"))).validate(account)
    tei = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    assert compiled_schema().validate(etree.ElementTree(tei))
    assert [node.get("{http://www.w3.org/XML/1998/namespace}id") for node in tei.xpath("//*[local-name()='text']/*[local-name()='front']/*")] == ["i", "ii"]
    assert [node.get("{http://www.w3.org/XML/1998/namespace}id") for node in tei.xpath("//*[local-name()='text']/*[local-name()='body']/*")] == ["iii"]


@pytest.mark.parametrize(
    "mutation",
    ["accountability", "content", "ledger", "embedded-source", "provenance", "manifest-binding"],
)
def test_meaningful_mutations_are_rejected(
    source_manifest: SourceManifest,
    candidate: CandidatePackage,
    tmp_path: Path,
    mutation: str,
) -> None:
    mutated = _mutated_package(candidate, tmp_path, mutation)
    with pytest.raises(ValueError):
        validate(source_manifest, mutated, oracle._oracle)


def test_fresh_processes_are_deterministic(
    source_manifest: SourceManifest, tmp_path: Path
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    script = """
import hashlib, json, sys
from pathlib import Path
from ocd_kernel.reconstruction import SourceManifest, reconstruct, validate
from build.tei.ryle_holiness_reconstruction import _convert
from build.tei.ryle_holiness_oracle import _oracle
root = Path(sys.argv[1]).resolve()
manifest = SourceManifest.load(sys.argv[2], repository_root=root)
out = Path(sys.argv[3]).resolve()
candidate = reconstruct(manifest, out, _convert)
report = validate(manifest, candidate, _oracle)
print(json.dumps({
    "candidate": candidate.sha256,
    "validation": report.sha256,
    "members": {name: hashlib.sha256((candidate.path / name).read_bytes()).hexdigest() for name in candidate.member_names},
}, sort_keys=True))
"""
    values = []
    for workdir, destination in ((first, first / "package"), (second, second / "package")):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT)
        env["PYTHONHASHSEED"] = "random"
        completed = subprocess.run(
            [sys.executable, "-c", script, str(ROOT), str(MANIFEST_PATH), str(destination)],
            cwd=workdir,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        values.append(json.loads(completed.stdout))
    assert values[0] == values[1]
