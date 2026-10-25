"""Focused LIB-055 route tests for 37c-267 Rutherford Letters."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

from lxml import etree
import pytest

from build.tei.ccel_puritan_lib055_rutherford_letters_oracle import _oracle
from build.tei.ccel_puritan_lib055_rutherford_letters_reconstruction import (
    SOURCE_BYTES,
    SOURCE_PATH,
    SOURCE_SHA256,
    _convert,
)
from ocd_kernel.reconstruction.contract import (
    CandidatePackage,
    SourceManifest,
    reconstruct,
    validate,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'tests/fixtures/reconstruction-runtime/ccel_puritan_lib055_rutherford_letters_oracle.source-manifest.json'
PROFILE = ROOT / "sources/structured-text/rutherford-letters/lib055/source-feature-profile.json"
POLICY = ROOT / "sources/structured-text/rutherford-letters/lib055/validation-policy.json"
NS = {"tei": "http://www.tei-c.org/ns/1.0"}


@pytest.fixture(scope="module")
def route():
    manifest = SourceManifest.load(MANIFEST, repository_root=ROOT)
    return manifest, _convert(manifest)


def test_manifest_binds_exact_source_envelope_and_unresolved_boundary():
    manifest = SourceManifest.load(MANIFEST, repository_root=ROOT)
    record = manifest.record
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    policy = json.loads(POLICY.read_text(encoding="utf-8"))

    assert record["ticket"] == "37c-267"
    assert record["owner_route"] == "LIB-055"
    assert record["work_id"] == "rutherford-letters"
    assert record["scope"]["member_order"] == (SOURCE_PATH,)
    assert record["scope"]["top_level_div1_ids"] == ("i", "ii", "iii", "iv", "v", "vi")
    assert [item["source_selector"] for item in record["scope"]["explicit_exclusions"]] == [
        "ThML.body/table/colgroup",
        "ThML.body/table/colgroup/col",
    ]
    source = manifest.authority_path("retained-source").read_bytes()
    assert len(source) == SOURCE_BYTES
    assert __import__("hashlib").sha256(source).hexdigest() == SOURCE_SHA256
    assert profile["document"]["element_count"] == 1171
    assert profile["document"]["body_element_count_including_wrapper"] == 1112
    assert profile["document"]["source_tag_counts"]["table"] == 1
    assert profile["document"]["source_tag_counts"]["colgroup"] == 1
    assert "explicit colgroup/col presentation dispositions" in policy["scope"]
    assert {row["status"] for row in policy["unresolved_records"]} == {"unresolved"}


def test_candidate_is_complete_faithful_and_nonaccepted(route, tmp_path):
    manifest, produced = route
    assert set(produced) == {
        "README.source.md",
        "content.tei.xml",
        "provenance.json",
        "source-accountability.json",
        "unresolved.jsonl",
    }
    candidate = reconstruct(manifest, tmp_path / "candidate", _convert)
    report = validate(manifest, candidate, _oracle)
    assert report.status == "pass"
    assert candidate.manifest["status"] == "nonaccepted"

    tei = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    assert [node.get("{http://www.w3.org/XML/1998/namespace}id") for node in tei.xpath(
        "./tei:text/tei:body/tei:div", namespaces=NS
    )] == ["i", "ii", "iii", "iv", "v", "vi"]
    assert len(tei.xpath(".//tei:table", namespaces=NS)) == 1
    assert len(tei.xpath(".//tei:row", namespaces=NS)) == 74
    assert len(tei.xpath(".//tei:ref[@type='scripture']", namespaces=NS)) == 53
    accounting = json.loads(candidate.member_bytes("source-accountability.json"))
    assert len(accounting["elements"]) == 1171
    assert len(accounting["exclusions"]) == 4
    assert accounting["source_member"] == {
        "path": SOURCE_PATH,
        "bytes": SOURCE_BYTES,
        "sha256": SOURCE_SHA256,
    }


def _reseal_copy(candidate: CandidatePackage, destination: Path, member: str, update):
    shutil.copytree(candidate.path, destination)
    changed = update((destination / member).read_bytes())
    (destination / member).write_bytes(changed)
    record = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    for item in record["members"]:
        path = destination / item["name"]
        item["bytes"] = path.stat().st_size
        item["sha256"] = __import__("hashlib").sha256(path.read_bytes()).hexdigest()
    (destination / "manifest.json").write_text(
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return CandidatePackage.load(destination)


@pytest.mark.parametrize("member,mutation", [("content.tei.xml", "tei"), ("source-accountability.json", "account")])
def test_independent_oracle_rejects_source_mutation(route, tmp_path, member, mutation):
    manifest, _ = route
    baseline = reconstruct(manifest, tmp_path / "baseline", _convert)

    def mutate(value: bytes) -> bytes:
        if mutation == "tei":
            tree = etree.fromstring(value)
            body = tree.find("./tei:text/tei:body", namespaces=NS)
            assert body is not None
            body.remove(body[0])
            return etree.tostring(tree, encoding="UTF-8", xml_declaration=True)
        account = json.loads(value)
        account["elements"].pop()
        return (json.dumps(account, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()

    mutated = _reseal_copy(baseline, tmp_path / f"mutated-{mutation}", member, mutate)
    with pytest.raises(ValueError):
        validate(manifest, mutated, _oracle)


def test_fresh_process_reconstruction_is_byte_deterministic(route, tmp_path):
    manifest, _ = route
    first = tmp_path / "fresh-one"
    second = tmp_path / "fresh-two"
    command = [
        sys.executable,
        "-B",
        "build/tools/reconstruct_candidate.py",
        "--manifest",
        MANIFEST.relative_to(ROOT).as_posix(),
        "--destination",
        str(first),
        "--repository-root",
        str(ROOT),
    ]
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
    command[command.index(str(first))] = str(second)
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
    left = CandidatePackage.load(first / "package")
    right = CandidatePackage.load(second / "package")
    assert {name: left.member_bytes(name) for name in left.member_names} == {
        name: right.member_bytes(name) for name in right.member_names
    }
    assert left.sha256 == right.sha256
