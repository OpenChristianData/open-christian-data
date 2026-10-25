from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
import shutil
import subprocess
import sys

from lxml import etree
from tests.historical_authority_mirrors import bound_callable, prepare_historical_mirror
import pytest

from build.tei.apostolic_tradition_oracle import _oracle
from build.tei.apostolic_tradition_reconstruction import _convert
from ocd_kernel.reconstruction.contract import (
    CandidatePackage,
    SourceManifest,
    reconstruct,
    validate,
)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "sources/apostolic-tradition/apostolic-tradition.source-manifest.json"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


@pytest.fixture(scope="module")
def route(tmp_path_factory: pytest.TempPathFactory):
    work = tmp_path_factory.mktemp("apostolic-route")
    mirror, path = prepare_historical_mirror(ROOT, work / "root", "apostolic")
    manifest = SourceManifest.load(path, repository_root=mirror)
    converter = bound_callable(mirror, manifest.record["converter"], "converter")
    oracle = bound_callable(mirror, manifest.record["validator"], "validator")
    candidate = reconstruct(manifest, work / "first-package", converter)
    report = validate(manifest, candidate, oracle)
    with pytest.MonkeyPatch.context() as patch:
        patch.setitem(globals(), "_oracle", oracle)
        yield work, manifest, candidate, report


def _reseal(path: Path) -> CandidatePackage:
    package_manifest_path = path / "manifest.json"
    package_manifest = json.loads(package_manifest_path.read_bytes())
    for member in package_manifest["members"]:
        content = (path / member["name"]).read_bytes()
        member.update(bytes=len(content), sha256=_sha(content))
    package_manifest_path.write_bytes(_canonical(package_manifest))
    return CandidatePackage.load(path)


def test_complete_retained_body_validates_and_replays_in_a_fresh_process(route) -> None:
    work, manifest, candidate, report = route
    source = manifest.authority_path("retained-html").read_bytes()
    profile = json.loads(manifest.authority_path("reconstruction-profile").read_bytes())
    policy = json.loads(manifest.authority_path("validation-policy").read_bytes())
    content = candidate.member_bytes("content.tei.xml")
    tei = etree.fromstring(content, etree.XMLParser(resolve_entities=False, no_network=True))

    assert report.status == "pass"
    assert candidate.manifest["status"] == "nonaccepted"
    assert _sha(source) == profile["source_html"]["sha256"]
    assert len(tei.xpath("/t:TEI/t:text/t:body/t:ab", namespaces={"t": TEI_NS})) == 1
    assert len(tei.xpath("//t:pb", namespaces={"t": TEI_NS})) == 42
    assert len(tei.xpath("//t:ref[@target]", namespaces={"t": TEI_NS})) == profile["body"]["link_count"]
    assert len(tei.xpath("//t:table", namespaces={"t": TEI_NS})) == 3
    assert len([node for node in tei.iter() if node.get(XML_ID)]) == profile["body"]["unique_source_ids"]
    unresolved = [json.loads(line) for line in candidate.member_bytes("unresolved.jsonl").splitlines()]
    rights = next(item for item in unresolved if item["id"] == "apostolic-tradition-edition-rights")
    assert rights["status"] == "hold"
    assert policy["publication_authorized"] is False

    replay_root = work / "fresh-process"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "build.tools.reconstruct_candidate",
            "--manifest",
            "sources/apostolic-tradition/apostolic-tradition.source-manifest.json",
            "--destination",
            str(replay_root),
            "--repository-root",
            str(manifest.repository_root),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    summary = json.loads(completed.stdout)
    replay_package = CandidatePackage.load(replay_root / "package")
    assert summary["status"] == "pass"
    assert replay_package.sha256 == candidate.sha256
    assert {
        name: replay_package.member_bytes(name) for name in replay_package.member_names
    } == {name: candidate.member_bytes(name) for name in candidate.member_names}
    replay_validation = json.loads((replay_root / "validation.json").read_bytes())
    assert replay_validation["report_sha256"] == report.sha256


@pytest.mark.parametrize(
    "mutation",
    ["omit", "duplicate", "reorder", "text", "source-accountability"],
)
def test_independent_oracle_rejects_candidate_mutations(route, tmp_path: Path, mutation: str) -> None:
    _work, manifest, candidate, _report = route
    changed_path = tmp_path / mutation
    shutil.copytree(candidate.path, changed_path)

    if mutation == "source-accountability":
        account_path = changed_path / "source-accountability.json"
        account = json.loads(account_path.read_bytes())
        account["source_sha256"] = "0" * 64
        account_path.write_bytes(_canonical(account))
    else:
        tei_path = changed_path / "content.tei.xml"
        tree = etree.parse(str(tei_path), etree.XMLParser(resolve_entities=False, no_network=True))
        wrapper = tree.find(f"./{{{TEI_NS}}}text/{{{TEI_NS}}}body/{{{TEI_NS}}}ab")
        assert wrapper is not None and len(wrapper) > 2
        if mutation == "omit":
            wrapper.remove(wrapper[0])
        elif mutation == "duplicate":
            wrapper.insert(1, deepcopy(wrapper[0]))
        elif mutation == "reorder":
            first, second = wrapper[0], wrapper[1]
            wrapper.remove(first)
            wrapper.remove(second)
            wrapper.insert(0, second)
            wrapper.insert(1, first)
        else:
            wrapper[0].text = "Mutated source text"
        tei_path.write_bytes(etree.tostring(tree, encoding="UTF-8", xml_declaration=True))

    changed = _reseal(changed_path)
    with pytest.raises(ValueError, match="differs"):
        validate(manifest, changed, _oracle)
