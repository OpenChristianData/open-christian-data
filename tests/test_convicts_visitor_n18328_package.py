"""Maintained nonaccepted package and independent source proof for N18328."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from lxml import etree
import pytest

from build.tei.convicts_visitor_n18328_package import _convert
from build.tei.convicts_visitor_n18328_package_oracle import _check
from build.tools.reconstruct_candidate import run
from cvw_app.review_contract import ReviewApplication, ReviewContractError, _load_validation_report
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'tests/fixtures/reconstruction-runtime/convicts-visitor-n18328.source-manifest.json'
CANDIDATE = ROOT / "library/works/convicts-visitor/integration/convicts-n18328-electronic-v1/candidate.tei.xml"
TEI = "{http://www.tei-c.org/ns/1.0}"


def _manifest():
    return SourceManifest.load(MANIFEST, repository_root=ROOT)


def test_work_local_converter_packages_the_exact_pinned_candidate():
    manifest = _manifest()
    members = _convert(manifest)
    assert set(members) == {
        "README.source.md", "content.tei.xml", "provenance.json",
        "source-accountability.json", "unresolved.jsonl",
    }
    assert members["content.tei.xml"] == CANDIDATE.read_bytes()
    assert sha256(members["content.tei.xml"]).hexdigest() == (
        "0d5bc4e091da8b10b26b815a420718ef082d51a3f41c25cde7d8d6b53b26eeef"
    )
    assert members["README.source.md"] == manifest.authority_path("source-credit").read_bytes()


def test_independent_lxml_oracle_rejects_source_feature_mutations():
    manifest = _manifest()
    source = manifest.authority_path("retained-tei-p5").read_bytes()
    content = CANDIDATE.read_bytes()
    profile = json.loads(manifest.authority_path("reconstruction-profile").read_text(encoding="utf-8"))
    assert _check(source, content, profile, schema_path=manifest.authority_path("tei-p5-xsd")) == []

    def changed(mutator):
        root = etree.fromstring(content, etree.XMLParser(resolve_entities=False, no_network=True))
        mutator(root)
        return etree.tostring(root, encoding="utf-8")

    changes = {
        "speaker": lambda root: setattr(next(root.iter(TEI + "speaker")), "text", "Invented speaker"),
        "verse": lambda root: setattr(next(root.iter(TEI + "l")), "text", "Invented verse"),
        "page": lambda root: next(root.iter(TEI + "pb")).set("n", "invented"),
    }
    for name, mutator in changes.items():
        altered = changed(mutator)
        assert altered != content, name
        errors = _check(source, altered, profile, schema_path=None)
        assert "candidate complete text or exact text suffix differs from source" in errors, name

    def move_note(root):
        note = next(root.iter(TEI + "note"))
        note.getparent().remove(note)
        next(root.iter(TEI + "p")).append(note)

    errors = _check(source, changed(move_note), profile, schema_path=None)
    assert "candidate complete text or exact text suffix differs from source" in errors


def test_maintained_runner_writes_genuine_package_and_validation(tmp_path):
    destination = tmp_path / "n18328"
    summary = run(
        manifest=MANIFEST.relative_to(ROOT).as_posix(),
        destination=str(destination),
        repository_root=str(ROOT),
    )
    assert summary["status"] == "pass"
    assert summary["acceptance_status"] == "nonaccepted"
    assert {path.name for path in destination.iterdir()} == {
        "package", "validation.json", "text-quality.json",
    }
    package = CandidatePackage.load(destination / "package")
    assert package.member_bytes("content.tei.xml") == CANDIDATE.read_bytes()
    validation = _load_validation_report(destination, _manifest(), package)
    assert validation.status == "pass"
    assert validation.sha256 == summary["validation_report"]["sha256"]
    quality_bytes = (destination / "text-quality.json").read_bytes()
    quality_sha256 = sha256(quality_bytes).hexdigest()
    assert quality_sha256 == summary["text_quality"]["sha256"]
    assert json.loads((destination / "validation.json").read_bytes())["text_quality_sha256"] == quality_sha256
    quality = json.loads(quality_bytes)
    assert quality["candidate_sha256"] == package.sha256
    assert quality["text_correctness"] == "not_assessed"
    assert set(package.member_names) == {
        "README.source.md", "content.tei.xml", "manifest.json",
        "provenance.json", "source-accountability.json", "unresolved.jsonl",
    }
    work_identity = next(row for row in _manifest().record["authorities"] if row["name"] == "work-identity")
    assert sha256((ROOT / "library/works/convicts-visitor/work.json").read_bytes()).hexdigest() != work_identity["sha256"]
    with pytest.raises(ReviewContractError, match="does not bind declared acquisition and work authorities"):
        ReviewApplication.from_declared_library(ROOT, [destination])
