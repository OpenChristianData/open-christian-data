"""Exact retained ASV route: baseline, source/TEI mutations, and independence."""

from copy import deepcopy
import ast
import hashlib
import json
from pathlib import Path

from lxml import etree
import pytest

from build.tei.asv_reconstruction import convert
from build.tei.asv_oracle import check_content, oracle
from ocd_kernel.reconstruction import SourceManifest, reconstruct, validate
from ocd_kernel.reconstruction.contract import CandidatePackage
from ocd_kernel.library.acquisitions import acquisition_for_edition
from ocd_kernel.library.identities import load_editions, load_work

WORKTREE = Path(__file__).resolve().parents[1]
NS = {"t": "http://www.tei-c.org/ns/1.0"}


@pytest.fixture(scope="module")
def bound():
    manifest = SourceManifest.load(
        WORKTREE / "tests/fixtures/reconstruction-runtime/asv.source-manifest.json",
        repository_root=WORKTREE,
    )
    result = convert(manifest)
    source = manifest.authority_path("asv-source").read_bytes()
    return manifest, source, result


def test_actual_package_passes_full_validation(bound, tmp_path):
    manifest, _, _ = bound
    candidate = reconstruct(manifest, tmp_path / "package", convert)
    report = validate(manifest, candidate, oracle)
    assert report.status == "pass"
    assert not report.findings


def _reseal_candidate(candidate, *, member_name=None, member_bytes=None, manifest_update=None):
    record = json.loads((candidate.path / "manifest.json").read_text(encoding="utf-8"))
    if member_name is not None:
        member_path = candidate.path / member_name
        member_path.write_bytes(member_bytes)
        member = next(item for item in record["members"] if item["name"] == member_name)
        member["bytes"] = len(member_bytes)
        member["sha256"] = hashlib.sha256(member_bytes).hexdigest()
    if manifest_update is not None:
        manifest_update(record)
    payload = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    (candidate.path / "manifest.json").write_bytes(payload)
    return CandidatePackage.load(candidate.path)


def test_stale_source_manifest_binding_rejected_after_package_reseal(bound, tmp_path):
    manifest, _, _ = bound
    candidate = reconstruct(manifest, tmp_path / "stale-binding", convert)
    stale = _reseal_candidate(
        candidate,
        manifest_update=lambda record: record["source_manifest"].update(sha256="0" * 64),
    )
    stale.verify_integrity()
    with pytest.raises(ValueError, match="candidate source manifest binding mismatch"):
        validate(manifest, stale, oracle)


def test_semantically_wrong_tei_rejected_after_member_reseal(bound, tmp_path):
    manifest, _, _ = bound
    candidate = reconstruct(manifest, tmp_path / "resealed-content", convert)
    tei_path = candidate.path / "content.tei.xml"
    original = tei_path.read_bytes()
    assert b"In the beginning" in original
    tampered = original.replace(b"In the beginning", b"At the beginning", 1)
    resealed = _reseal_candidate(candidate, member_name="content.tei.xml", member_bytes=tampered)
    resealed.verify_integrity()
    with pytest.raises(ValueError, match="source text conservation"):
        validate(manifest, resealed, oracle)


def test_declared_work_route_matches_exact_non_ocr_source(bound):
    manifest, _, _ = bound
    work_path = WORKTREE / "library/works/asv/work.json"
    work = load_work(work_path)
    editions = load_editions(work_path)
    assert work["work_id"] == manifest.record["work_id"] == "asv"
    assert work["title"] == "ASV: American Standard Version (1901)"
    assert "creators" not in work or not work["creators"]
    assert len(editions) == 1
    _, acquisition = acquisition_for_edition(
        WORKTREE, "asv", "retained-json", "scrollmapper-retained-json"
    )
    declared_primary = {
        (item["path"], item["bytes"], item["sha256"])
        for item in manifest.record["authorities"]
        if item["role"] == "primary-source"
    }
    acquired_primary = {
        (item["path"], item["bytes"], item["sha256"])
        for item in acquisition["retained_files"]
    }
    assert acquisition["route"] == "born-digital"
    assert acquired_primary == declared_primary


@pytest.mark.parametrize("mutation,reason", [
    ("omit", "order/attachment/omission"), ("duplicate", "already defined"),
    ("reorder", "order/attachment/omission"), ("wrong-parent", "order/attachment/omission"),
    ("invent", "text conservation"), ("trim", "text conservation"),
    ("number", "source numbering"), ("title", "text conservation"),
    ("metadata", "header meaning or metadata drift"), ("attribute", "attributes/topology"),
])
def test_actual_tei_mutations_rejected(bound, mutation, reason):
    _, source, result = bound
    root = etree.fromstring(result["content.tei.xml"])
    chapters = root.xpath("./t:text/t:body/t:div/t:div", namespaces=NS)
    first = chapters[0][0]
    if mutation == "omit":
        chapters[0].remove(first)
    elif mutation == "duplicate":
        chapters[0].append(deepcopy(first))
    elif mutation == "reorder":
        chapters[0].remove(first)
        chapters[0].insert(1, first)
        assert chapters[0][0].get("n") == "2"
    elif mutation == "wrong-parent":
        chapters[1].append(first)
    elif mutation == "invent":
        first.text += " invented"
    elif mutation == "trim":
        assert first.text != first.text.rstrip()
        first.text = first.text.rstrip()
    elif mutation == "number":
        first.set("n", "999")
    elif mutation == "title":
        root.xpath(".//t:head", namespaces=NS)[0].text = "Wrong book"
    elif mutation == "metadata":
        root.xpath(".//t:title", namespaces=NS)[0].text = "Another translation"
    else:
        first.set("type", "paragraph")
    changed = etree.tostring(root)
    assert changed != result["content.tei.xml"]
    with pytest.raises((ValueError, etree.XMLSyntaxError), match=reason):
        check_content(source, changed, result["source-accountability.json"])


@pytest.mark.parametrize("mutation,reason", [("field", "unknown source object"), ("duplicate", "duplicate source key"), ("identity", "wrong ASV identity"), ("accounting", "incomplete source accounting")])
def test_source_and_accounting_mutations_rejected(bound, mutation, reason):
    _, source, result = bound
    accounting = result["source-accountability.json"]
    if mutation == "duplicate":
        source = source.replace(b'"translation":', b'"translation":"duplicate", "translation":', 1)
    elif mutation == "accounting":
        record = json.loads(accounting)
        record["fields"].pop()
        accounting = json.dumps(record).encode()
    else:
        record = json.loads(source)
        if mutation == "field":
            record["books"][0]["unaccounted"] = "lost prose"
        else:
            record["translation"] = "Wrong source"
        source = json.dumps(record).encode()
    with pytest.raises(ValueError, match=reason):
        check_content(source, result["content.tei.xml"], accounting)


def test_oracle_has_no_producer_dependency():
    code = (WORKTREE / "build/tei/asv_oracle.py").read_text(encoding="utf-8")
    syntax = ast.parse(code)
    for node in ast.walk(syntax):
        if isinstance(node, ast.ImportFrom):
            assert node.module is not None
            assert "asv_reconstruction" not in node.module
            assert not node.module.startswith("build.")
        elif isinstance(node, ast.Import):
            assert all("asv_reconstruction" not in alias.name for alias in node.names)
    assert "_inventory" not in code


def test_public_manifest_rejects_wrong_caller_root():
    with pytest.raises(ValueError, match="outside repository root"):
        SourceManifest.load(WORKTREE / "sources/bible-text/asv/asv.source-manifest.json", repository_root=WORKTREE / "raw")
