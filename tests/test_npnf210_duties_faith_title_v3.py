"""Verify source-visible title repair for the two Ambrose prose works."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

from lxml import etree
import pytest

from build.tei.npnf_ambrose_duties_faith_title_v3_oracle import _oracle
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from tests.runtime_candidate_baselines import current_runtime_baseline


ROOT = Path("\\\\?\\" + str(Path(__file__).resolve().parents[1]))
WORKS = {
    "ambrose-of-milan-on-duties-of-clergy": 21,
    "ambrose-of-milan-exposition-of-christian-faith": 45,
}
NS = {"tei": "http://www.tei-c.org/ns/1.0"}


def _paths(work_id: str) -> tuple[Path, Path, Path]:
    manifest = Path(f"sources/structured-text/{work_id}/npnf210-duties-faith-title-v3.source-manifest.json")
    package = Path(f"D:/Library/Open Christian Data/candidate-reviews/npnf210-work-{work_id}-title-v3-20260926")
    previous = Path(f"D:/Library/Open Christian Data/candidate-reviews/npnf210-work-{work_id}-heading-repair-v2-20260926")
    return manifest, package, previous


@pytest.fixture(scope="module", autouse=True)
def current_title_baselines(tmp_path_factory):
    cases = json.loads((ROOT / "tests/fixtures/reconstruction-runtime/next-binding-npnf210-title.json").read_bytes())
    retained_paths = {work_id: _paths(work_id) for work_id in WORKS}
    current_paths = {}
    for case in cases:
        work_id = case["work_id"]
        _, package, previous = retained_paths[work_id]
        _, candidate = current_runtime_baseline(
            root=ROOT, original_manifest=case["original"], runtime_manifest=case["manifest"],
            retained_package=package / "package", retained_sha256=case["retained_package_sha256"],
            destination=tmp_path_factory.mktemp("ambrose-title-current") / "candidate")
        current_paths[work_id] = (Path(case["manifest"]), candidate.path.parent, previous)
    with pytest.MonkeyPatch.context() as patch:
        patch.setitem(globals(), "_paths", lambda work_id: current_paths[work_id])
        yield


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _files(path: Path) -> dict[str, str]:
    return {member.name: _sha(member.read_bytes()) for member in sorted(path.iterdir()) if member.is_file()}


@pytest.mark.parametrize("work_id,removed", WORKS.items())
def test_source_and_only_redundant_heads_change(work_id: str, removed: int) -> None:
    manifest_path, package_path, previous_path = _paths(work_id)
    manifest = SourceManifest.load(ROOT / manifest_path, repository_root=ROOT)
    manifest.verify()
    candidate = CandidatePackage.load(package_path / "package")
    assert _oracle(manifest, candidate)["status"] == "pass"
    old = etree.fromstring((previous_path / "package/content.tei.xml").read_bytes())
    new = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    old_text, new_text = old.find("tei:text", NS), new.find("tei:text", NS)
    heads = old_text.xpath(".//tei:div/tei:head", namespaces=NS)
    assert len(heads) == removed
    assert not new_text.xpath(".//tei:div/tei:head", namespaces=NS)
    for head in heads:
        head.getparent().remove(head)
    assert etree.tostring(old_text, method="c14n") == etree.tostring(new_text, method="c14n")
    accounting = json.loads(candidate.member_bytes("source-accountability.json"))
    suppressed = [row for row in accounting["crosswalk"] if any(item["source_attribute"] == "title" and item["method"] == "redundant-explicit-content" for item in row["attribute_dispositions"])]
    assert len(suppressed) >= removed


@pytest.mark.parametrize("work_id", WORKS)
def test_clean_process_reproduces_package(work_id: str, tmp_path: Path) -> None:
    manifest_path, package_path, _ = _paths(work_id)
    target = tmp_path / "candidate"
    process = subprocess.run(
        [sys.executable, "-m", "build.tools.reconstruct_candidate", "--repository-root", str(ROOT), "--manifest", manifest_path.as_posix(), "--destination", str(target)],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    assert json.loads(process.stdout)["status"] == "pass"
    assert _files(target / "package") == _files(package_path / "package")
    assert _sha((target / "validation.json").read_bytes()) == _sha((package_path / "validation.json").read_bytes())


def test_resealed_faith_terminal_text_mutation_rejected(tmp_path: Path) -> None:
    work_id = "ambrose-of-milan-exposition-of-christian-faith"
    manifest_path, package_path, _ = _paths(work_id)
    target = tmp_path / "mutated"
    target.mkdir()
    for member in (package_path / "package").iterdir():
        (target / member.name).write_bytes(member.read_bytes())
    xml = target / "content.tei.xml"
    tree = etree.parse(str(xml))
    paragraph = tree.xpath("//tei:div[@xml:id='npnf-ambrose-iv.iv.vii.xx']/tei:p[1]", namespaces=NS)[0]
    paragraph.text = (paragraph.text or "") + " invented"
    xml.write_bytes(etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=False) + b"\n")
    package_manifest = target / "manifest.json"
    record = json.loads(package_manifest.read_bytes())
    member = next(item for item in record["members"] if item["name"] == "content.tei.xml")
    member["bytes"] = len(xml.read_bytes())
    member["sha256"] = _sha(xml.read_bytes())
    package_manifest.write_bytes((json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))
    manifest = SourceManifest.load(ROOT / manifest_path, repository_root=ROOT)
    with pytest.raises(ValueError, match="direct text|source-kind|crosswalk"):
        _oracle(manifest, CandidatePackage.load(target))
