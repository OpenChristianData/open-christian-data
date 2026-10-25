from __future__ import annotations

import hashlib
import json
from pathlib import Path
import os
import shutil
import subprocess
import sys

from lxml import etree
import pytest

from build.tei.npnf104_lib038_oracle import _oracle
from build.tei.npnf104_lib038_reconstruction import _convert
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, reconstruct, validate


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'tests/fixtures/reconstruction-runtime/npnf104-lib038.source-manifest.json'
TEI_NS = {"tei": "http://www.tei-c.org/ns/1.0"}


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


@pytest.fixture(scope="session")
def lib038_source_manifest() -> SourceManifest:
    return SourceManifest.load(MANIFEST, repository_root=ROOT)


@pytest.fixture(scope="session")
def lib038_candidate(
    tmp_path_factory: pytest.TempPathFactory,
    lib038_source_manifest: SourceManifest,
) -> CandidatePackage:
    destination = tmp_path_factory.mktemp("npnf104-lib038-candidate") / "package"
    return reconstruct(lib038_source_manifest, destination, _convert)


def _reseal(path: Path, member_name: str, content: bytes) -> CandidatePackage:
    (path / member_name).write_bytes(content)
    manifest = json.loads((path / "manifest.json").read_bytes())
    for member in manifest["members"]:
        if member["name"] == member_name:
            member["bytes"] = len(content)
            member["sha256"] = hashlib.sha256(content).hexdigest()
            break
    (path / "manifest.json").write_bytes(_canonical(manifest))
    return CandidatePackage.load(path)


def _mutation_copy(candidate: CandidatePackage, destination: Path) -> Path:
    shutil.copytree(candidate.path, destination)
    for item in destination.iterdir():
        if item.is_file() and (candidate.path / item.name).samefile(item):
            raise AssertionError(f"mutation copy unexpectedly shares {item.name}")
    return destination


def test_candidate_passes_independent_oracle_and_preserves_assigned_scope(
    lib038_source_manifest: SourceManifest,
    lib038_candidate: CandidatePackage,
) -> None:
    account = json.loads(lib038_candidate.member_bytes("source-accountability.json"))
    assert account["assigned_work_count"] == 10
    assert account["feature_count"] == 11999
    assert account["attribute_count"] == 33468
    assert account["feature_counts"]["scripRef"] == 1955
    assert len(account["crosswalk"]) == 11999
    assert len(account["comment_accounting"]) == 0
    assert account["source_census"]["assigned_scope"]["comments"] == 0
    assert account["source_census"]["complete_document"]["comments"] == 0
    assert account["source_census"]["excluded_shell_head_front_and_unassigned_roots"]["comments"] == 0
    report = validate(lib038_source_manifest, lib038_candidate, _oracle)
    assert report.status == "pass"
    assert report.findings == ()


def test_fresh_processes_are_byte_deterministic(
    tmp_path: Path,
) -> None:
    script = (
        "from pathlib import Path; import sys; "
        "from ocd_kernel.reconstruction.contract import SourceManifest,reconstruct; "
        "from build.tei.npnf104_lib038_reconstruction import _convert; "
        "root=Path(sys.argv[1]).resolve(); destination=Path(sys.argv[2]); "
        "manifest=SourceManifest.load(root/'tests/fixtures/reconstruction-runtime/npnf104-lib038.source-manifest.json',repository_root=root); "
        "candidate=reconstruct(manifest,destination,_convert); print(candidate.sha256)"
    )
    outputs: list[tuple[str, dict[str, bytes]]] = []
    for index, seed in enumerate(("17", "2147483647")):
        destination = tmp_path / f"process-{index}"
        environment = os.environ.copy()
        environment["PYTHONHASHSEED"] = seed
        completed = subprocess.run(
            [sys.executable, "-B", "-c", script, str(ROOT), str(destination)],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )
        outputs.append((completed.stdout.strip(), {item.name: item.read_bytes() for item in destination.iterdir()}))
    assert outputs[0] == outputs[1]


@pytest.mark.parametrize("mutation", ["tei-text", "tei-attribute", "crosswalk", "provenance"])
def test_oracle_rejects_resealed_mutations(
    tmp_path: Path,
    lib038_source_manifest: SourceManifest,
    lib038_candidate: CandidatePackage,
    mutation: str,
) -> None:
    destination = _mutation_copy(lib038_candidate, tmp_path / mutation)
    if mutation == "tei-text":
        root = etree.fromstring((destination / "content.tei.xml").read_bytes())
        node = root.xpath("/tei:TEI/tei:text/tei:body//tei:p", namespaces=TEI_NS)[0]
        node.text = (node.text or "") + " [mutation]"
        content = etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False)
        expected = "TEI source direct text drift"
        mutated = _reseal(destination, "content.tei.xml", content)
    elif mutation == "tei-attribute":
        root = etree.fromstring((destination / "content.tei.xml").read_bytes())
        node = root.xpath("/tei:TEI/tei:text/tei:body//*[@xml:id]", namespaces={**TEI_NS, "xml": "http://www.w3.org/XML/1998/namespace"})[0]
        node.set("type", "mutation")
        content = etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False)
        expected = "TEI source attribute drift"
        mutated = _reseal(destination, "content.tei.xml", content)
    elif mutation == "crosswalk":
        account = json.loads((destination / "source-accountability.json").read_bytes())
        account["crosswalk"][0]["direct_text_sha256"] = "0" * 64
        expected = "source accountability crosswalk drift"
        mutated = _reseal(destination, "source-accountability.json", _canonical(account))
    else:
        provenance = json.loads((destination / "provenance.json").read_bytes())
        provenance["status"] = "accepted"
        expected = "provenance metadata drift"
        mutated = _reseal(destination, "provenance.json", _canonical(provenance))
    with pytest.raises(ValueError, match=expected):
        _oracle(lib038_source_manifest, mutated)
