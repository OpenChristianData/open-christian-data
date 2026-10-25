from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from lxml import etree
import pytest

from build.tei.sum_saving_knowledge_oracle import _closure as _oracle_closure, _oracle
from build.tei.sum_saving_knowledge_reconstruction import _convert, _producer_closure
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, reconstruct, validate

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'tests/fixtures/reconstruction-runtime/sum_saving_knowledge_oracle.source-manifest.json'
SOURCE = ROOT / "raw/westminster-standard-org/sum-of-saving-knowledge.html"
NS = {"t": "http://www.tei-c.org/ns/1.0"}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory):
    manifest = SourceManifest.load(MANIFEST, repository_root=ROOT)
    candidate = reconstruct(manifest, tmp_path_factory.mktemp("37c300") / "candidate", _convert)
    report = validate(manifest, candidate, _oracle)
    return manifest, candidate, report


def test_retained_html_scope_accounting_and_validation(built) -> None:
    manifest, candidate, report = built
    assert manifest.record["work_id"] == "sum-of-saving-knowledge"
    assert len(SOURCE.read_bytes()) == 135684
    assert _sha(SOURCE.read_bytes()) == "6aa4907f6994d61ce3afeeea9b063cabf667b087185bc1cf7f7fd71fc19fee83"
    accounting = json.loads(candidate.member_bytes("source-accountability.json"))
    assert accounting["represented_column_count"] == 6
    assert accounting["excluded_column_count"] == 7
    assert len(accounting["text_columns"]) == 13
    assert accounting["legacy_json_used_as_authority"] is False
    assert report.status == "pass" and report.findings == ()
    assert candidate.manifest["status"] == "nonaccepted"


def test_all_work_text_is_readable_and_key_structure_survives(built) -> None:
    _manifest, candidate, _report = built
    root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    body = root.xpath("/t:TEI/t:text/t:body", namespaces=NS)[0]
    assert len(body) == 6
    headings = [" ".join(" ".join(n.itertext()).split()) for n in body.xpath(".//t:div[@type='source-heading']/t:head", namespaces=NS)]
    assert len(headings) == 19
    assert headings.count("Head I.") == 1
    assert "Warrants to Believe" in headings
    assert headings.count("Section 1") == 2
    assert "The Evidences of True Faith" in headings
    assert len(body.xpath(".//t:p[starts-with(@rend,'source-heading-')]", namespaces=NS)) == 0
    assert len(body.xpath(".//t:div[@type='source-heading']/t:head", namespaces=NS)) == 19
    assert len(body.xpath(".//t:list[@type='ordered']/t:item", namespaces=NS)) == 4
    assert len(body.xpath(".//t:ref", namespaces=NS)) == 4
    assert len(body.xpath(".//t:lb", namespaces=NS)) == 26


@pytest.mark.parametrize("mutation", ["omit", "reorder", "invent", "flatten-heading", "move-heading"])
def test_independent_oracle_rejects_resealed_mutations(built, tmp_path: Path, mutation: str) -> None:
    manifest, candidate, _report = built
    target = tmp_path / mutation
    shutil.copytree(candidate.path, target)
    path = target / "content.tei.xml"
    root = etree.fromstring(path.read_bytes())
    paragraphs = root.xpath("/t:TEI/t:text/t:body//t:p", namespaces=NS)
    if mutation == "omit":
        paragraphs[0].getparent().remove(paragraphs[0])
    elif mutation == "reorder":
        flows = root.xpath("/t:TEI/t:text/t:body//t:div[@type='source-flow']", namespaces=NS)
        pair = next((flows[i:i + 2] for i in range(len(flows) - 1) if flows[i].getparent() is flows[i + 1].getparent()), None)
        assert pair is not None
        parent = pair[0].getparent()
        parent.remove(pair[1]); parent.insert(parent.index(pair[0]), pair[1])
    elif mutation == "invent":
        paragraphs[0].text = (paragraphs[0].text or "") + " invented"
    elif mutation == "flatten-heading":
        heading = root.xpath("/t:TEI/t:text/t:body//t:div[@type='source-heading']/t:head[normalize-space(.)='Head I.']", namespaces=NS)[0]
        heading.tag = f"{{{NS['t']}}}p"
    else:
        heading = root.xpath("/t:TEI/t:text/t:body//t:div[@type='source-heading']/t:head[normalize-space(.)='Head I.']", namespaces=NS)[0]
        first_div = heading.getparent()
        other_div = root.xpath("/t:TEI/t:text/t:body//t:div[@type='source-heading'][not(t:head[normalize-space(.)='Head I.'])]", namespaces=NS)[0]
        other_heading = other_div[0]
        first_div.remove(heading); other_div.remove(other_heading)
        first_div.append(other_heading); other_div.append(heading)
    path.write_bytes(etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False))
    package_record = json.loads((target / "manifest.json").read_bytes())
    member = next(row for row in package_record["members"] if row["name"] == "content.tei.xml")
    member.update(bytes=path.stat().st_size, sha256=_sha(path.read_bytes()))
    (target / "manifest.json").write_text(json.dumps(package_record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        validate(manifest, CandidatePackage.load(target), _oracle)


def test_second_process_reproduces_identical_candidate(built, tmp_path: Path) -> None:
    _manifest, candidate, _report = built
    destination = tmp_path / "fresh"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    code = (
        "from pathlib import Path; from ocd_kernel.reconstruction import SourceManifest,reconstruct; "
        "from build.tei.sum_saving_knowledge_reconstruction import _convert; "
        f"r=Path({str(ROOT)!r}); m=SourceManifest.load(Path({str(MANIFEST)!r}),repository_root=r); "
        f"p=reconstruct(m,Path({str(destination)!r}),_convert); print(p.sha256)"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == candidate.sha256
    for name in candidate.member_names:
        assert (destination / name).read_bytes() == candidate.member_bytes(name)


def test_current_route_and_metadata_bindings_are_source_bound() -> None:
    manifest = SourceManifest.load(MANIFEST, repository_root=ROOT)
    assert manifest.record["ticket_id"] == "LIB-089"
    assert manifest.record["work_id"] == "sum-of-saving-knowledge"
    assert manifest.record["source_id"] == "westminsterstandard-sum-of-saving-knowledge-retained-html"
    assert manifest.record["retained_source_path"] == SOURCE.relative_to(ROOT).as_posix()

    source_authority = next(
        authority
        for authority in manifest.record["authorities"]
        if authority["name"] == "retained-html"
    )
    assert source_authority["bytes"] == len(SOURCE.read_bytes())
    assert source_authority["sha256"] == _sha(SOURCE.read_bytes())

    profile = json.loads(manifest.authority_path("reconstruction-profile").read_bytes())
    policy = json.loads(manifest.authority_path("validation-policy").read_bytes())
    assert profile["source_sha256"] == source_authority["sha256"]
    assert policy["source_sha256"] == source_authority["sha256"]
    assert profile["column_dispositions"].count("represented-contents") == 1
    assert profile["column_dispositions"].count("excluded-back-navigation") == 4
    assert profile["column_dispositions"].count("excluded-empty-spacer") == 3
    assert policy["coverage"].startswith("All six populated work-text columns")

    converter = manifest.record["converter"]
    validator = manifest.record["validator"]
    assert converter["callable"] == "_convert"
    assert validator["callable"] == "_oracle"
    assert converter["implementation_sha256"] == _sha(
        (ROOT / converter["implementation_path"]).read_bytes()
    )
    assert validator["implementation_sha256"] == _sha(
        (ROOT / validator["implementation_path"]).read_bytes()
    )
    assert manifest.record["producer_import_closure_sha256"] == _producer_closure(ROOT)
    assert validator["import_closure_sha256"] == _oracle_closure(ROOT)
    assert manifest.record["producer_import_closure_sha256"] != validator["import_closure_sha256"]

    metadata = json.loads(
        (ROOT / "metadata/source-evidence/catalog/sum-of-saving-knowledge.json").read_bytes()
    )
    assert metadata["subject"] == {"id": "sum-of-saving-knowledge", "kind": "catalog"}
    for dimension in metadata["dimensions"].values():
        assert dimension["status"] == "inspected"
        for field in dimension["fields"]:
            for binding in field["evidence"].get("bindings", []):
                if binding.get("role") == "primary":
                    assert binding["path"] == manifest.record["retained_source_path"]
                    assert binding["bytes"] == source_authority["bytes"]
                    assert binding["sha256"] == source_authority["sha256"]
    language = next(
        field
        for field in metadata["dimensions"]["textual_form"]["fields"]
        if field["claim_id"] == "textual_form:observed.language"
    )
    assert language["evidence"]["classification"] == "supported"
    assert language["evidence"]["value"] == "en-US"
    assert language["scope"]["event_role"] == "retained_html_root_language_declaration"
    assert language["adoption"]["destination"] == "source_evidence_only"
    assert b'<html lang="en-US"' in SOURCE.read_bytes()

    edition = metadata["dimensions"]["edition"]["fields"]
    for field in edition:
        assert field["adoption"]["destination"] == "source_evidence_only"
    assert any(
        field["claim_id"] == "edition:observed.source_edition"
        and field["adoption"]["classification"] == "not_selected"
        for field in edition
    )


def test_fresh_no_write_workcatalog_route_is_verified(tmp_path: Path) -> None:
    manifest = SourceManifest.load(MANIFEST, repository_root=ROOT)
    handoff = tmp_path / "candidate-handoff"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "build/tools/reconstruct_candidate.py"),
            "--manifest",
            MANIFEST.relative_to(ROOT).as_posix(),
            "--destination",
            str(handoff),
            "--repository-root",
            str(ROOT),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    summary = json.loads(result.stdout)
    assert summary["acceptance_status"] == "nonaccepted"
    assert summary["validation_report"]["status"] == "pass"

    from tests.runtime_candidate_baselines import current_runtime_catalog

    catalog_outputs = tuple(
        ROOT / relative
        for relative in (
            "reports/publish/work_catalog.json",
            "reports/publish/work_catalog.md",
            "reports/publish/work_catalog.html",
        )
    )
    before = {path: _sha(path.read_bytes()) for path in catalog_outputs}
    catalog = current_runtime_catalog(
        root=ROOT, manifest=MANIFEST, work_ids=("sum-of-saving-knowledge",),
        reconstruction_evidence={
            (manifest.record["source_id"], manifest.record["work_id"]): (
                handoff / "package",
                handoff / "validation.json",
            )
        },
        data_resource_allowlist=["data/doctrinal-documents/sum-of-saving-knowledge.json"],
    )
    after = {path: _sha(path.read_bytes()) for path in catalog_outputs}
    assert before == after

    work = next(work for work in catalog.works if work["work_id"] == "sum-of-saving-knowledge")
    state = work["reconstruction_state"]
    assert state["retained_source"] == "manifest_bound"
    assert state["tei_candidate"] == "verified"
    assert state["validation"] == "verified"
    assert state["human_review"] == "required"
    assert state["accepted_ir"] == "not_accepted"
    assert state["publication"] == "not_ready"
    assert state["routes"] == [
        {
            "association": "source_hash+exact_id",
            "candidate_verification": "verified",
            "manifest": MANIFEST.relative_to(ROOT).as_posix(),
            "scope": "work",
            "source_id": "westminsterstandard-sum-of-saving-knowledge-retained-html",
            "validation_verification": "verified",
            "verification": "verified",
        }
    ]


@pytest.mark.parametrize("member", [
    "build/tei/sum_saving_knowledge_reconstruction.py",
    "ocd_kernel/reconstruction/contract.py",
    "ocd_kernel/reconstruction/__init__.py",
])
def test_producer_closure_detects_repository_dependency_mutation(tmp_path: Path, member: str) -> None:
    members = (
        "build/tei/sum_saving_knowledge_reconstruction.py",
        "ocd_kernel/reconstruction/contract.py",
        "ocd_kernel/reconstruction/__init__.py",
    )
    for logical in members:
        target = tmp_path / logical
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / logical).read_bytes())
    before = _producer_closure(tmp_path)
    assert before == _producer_closure(ROOT)
    target = tmp_path / member
    target.write_bytes(target.read_bytes() + b"\n# dependency mutation\n")
    assert _producer_closure(tmp_path) != before


def test_producer_closure_does_not_substitute_oracle_bytes(tmp_path: Path) -> None:
    for logical in (
        "build/tei/sum_saving_knowledge_reconstruction.py",
        "ocd_kernel/reconstruction/contract.py",
        "ocd_kernel/reconstruction/__init__.py",
    ):
        target = tmp_path / logical
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / logical).read_bytes())
    before = _producer_closure(tmp_path)
    oracle = tmp_path / "build/tei/sum_saving_knowledge_oracle.py"
    oracle.write_bytes(b"# unrelated oracle mutation\n")
    assert _producer_closure(tmp_path) == before
