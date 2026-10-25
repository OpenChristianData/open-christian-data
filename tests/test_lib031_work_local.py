"""Source-local LIB-031 package, mutation, and reproduction checks."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from lxml import etree
import pytest

from build.tei.lib031_work_local_oracle import _verify
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from tests.runtime_candidate_baselines import current_runtime_baseline

ROOT = Path(__file__).resolve().parents[1]
REVIEW_ROOT = Path(r"D:\Library\Open Christian Data\candidate-reviews")
WORKS = (
    "bounds-essentials-of-prayer",
    "bounds-necessity-of-prayer",
    "bounds-power-through-prayer",
    "bounds-prayer-and-praying-men",
    "bounds-purpose-in-prayer",
    "bounds-reality-of-prayer",
    "bounds-weapon-of-prayer",
    "finney-lectures-on-revivals",
    "finney-systematic-theology",
    "pascal-pensees",
)
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
TEI_NS = "http://www.tei-c.org/ns/1.0"


def _runtime_case(work_id: str):
    cases = json.loads((ROOT / "tests/fixtures/reconstruction-runtime/next-binding-lib031-work-local.json").read_bytes())
    matches = [case for case in cases if case["work_id"] == work_id]
    assert len(matches) == 1
    return matches[0]


@pytest.fixture(scope="module")
def runtime_baselines(tmp_path_factory):
    result = {}
    for work_id in WORKS:
        case = _runtime_case(work_id)
        result[work_id] = current_runtime_baseline(
            root=ROOT, original_manifest=case["original"], runtime_manifest=case["manifest"],
            retained_package=_candidate(work_id).path,
            retained_sha256=case["retained_package_sha256"],
            destination=tmp_path_factory.mktemp("lib031-runtime") / "candidate",
        )
    return result


def _candidate(work_id: str) -> CandidatePackage:
    path = REVIEW_ROOT / f"lib031-work-{work_id}-20260926-v6" / "package"
    return CandidatePackage.load(path)


def _mutated(candidate: CandidatePackage, target: Path, mutate) -> CandidatePackage:
    target.mkdir()
    members = {name: candidate.member_bytes(name) for name in candidate.member_names}
    tree = etree.fromstring(members["content.tei.xml"])
    mutate(tree, json.loads(members["source-accountability.json"]))
    members["content.tei.xml"] = etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=False) + b"\n"
    manifest = json.loads(members["manifest.json"])
    for item in manifest["members"]:
        if item["name"] == "content.tei.xml":
            item["bytes"] = len(members["content.tei.xml"])
            item["sha256"] = hashlib.sha256(members["content.tei.xml"]).hexdigest()
    members["manifest.json"] = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    for name, content in members.items():
        (target / name).write_bytes(content)
    return CandidatePackage.load(target)


def _mapped(tree: etree._Element, row: dict[str, object]) -> etree._Element:
    target_id = str(row["tei_selector"])[1:]
    found = tree.xpath("//*[@xml:id=$target_id]", namespaces={"xml": "http://www.w3.org/XML/1998/namespace"}, target_id=target_id)
    assert len(found) == 1
    return found[0]


def test_all_ten_final_packages_are_source_bound_and_nonaccepted(runtime_baselines) -> None:
    total = 0
    for work_id in WORKS:
        manifest, candidate = runtime_baselines[work_id]
        _verify(manifest, candidate)
        sidecar = json.loads((candidate.path.parent / "validation.json").read_bytes())
        assert candidate.manifest["status"] == "nonaccepted"
        assert candidate.manifest["source_manifest"]["sha256"] == manifest.sha256
        assert sidecar["status"] == "pass"
        assert sidecar["candidate_sha256"] == candidate.sha256
        accounting = json.loads(candidate.member_bytes("source-accountability.json"))
        assert accounting["work_id"] == work_id
        total += len(accounting["body_crosswalk"])
    assert total == 19465


def test_source_heading_demotion_is_rejected(tmp_path: Path, runtime_baselines) -> None:
    work_id = "bounds-power-through-prayer"
    manifest, candidate = runtime_baselines[work_id]

    def demote(tree: etree._Element, accounting: dict[str, object]) -> None:
        row = next(row for row in accounting["body_crosswalk"] if row["source_tag"] == "h2")
        _mapped(tree, row).tag = f"{{{TEI_NS}}}p"

    changed = _mutated(candidate, tmp_path / "heading", demote)
    with pytest.raises(ValueError, match="source division heading lost"):
        _verify(manifest, changed)


def test_local_link_retarget_is_rejected(tmp_path: Path, runtime_baselines) -> None:
    work_id = "pascal-pensees"
    manifest, candidate = runtime_baselines[work_id]

    def retarget(tree: etree._Element, accounting: dict[str, object]) -> None:
        row = next(row for row in accounting["body_crosswalk"] if row["source_tag"] == "a")
        _mapped(tree, row).set("target", "#pascal-pensees")

    changed = _mutated(candidate, tmp_path / "link", retarget)
    with pytest.raises(ValueError, match="source link target changed"):
        _verify(manifest, changed)


@pytest.mark.parametrize("work_id", ["bounds-power-through-prayer", "pascal-pensees"])
def test_clean_process_reproduces_every_package_file(work_id: str, tmp_path: Path, runtime_baselines) -> None:
    manifest = ROOT / _runtime_case(work_id)["manifest"]
    destination = tmp_path / work_id
    subprocess.run(
        [sys.executable, "-m", "build.tools.reconstruct_candidate", "--manifest", str(manifest.relative_to(ROOT)), "--destination", str(destination), "--repository-root", str(ROOT)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    expected_root = runtime_baselines[work_id][1].path.parent
    for relative in ["package/README.source.md", "package/content.tei.xml", "package/manifest.json", "package/provenance.json", "package/source-accountability.json", "package/unresolved.jsonl", "validation.json"]:
        assert (destination / relative).read_bytes() == (expected_root / relative).read_bytes()
