from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

from lxml import etree
import pytest

from build.tei.npnf2_lib046_oracle import (
    ASSIGNED as ORACLE_ASSIGNED,
    EXPECTED_CENSUS as ORACLE_CENSUS,
    _closure_digest,
    _closure_paths,
    _oracle,
)
from build.tei.npnf2_lib046_reconstruction import (
    ASSIGNED,
    EXPECTED_CENSUS,
    SOURCES,
    _convert,
)
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, reconstruct, validate


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'tests/fixtures/reconstruction-runtime/npnf2-lib046.source-manifest.json'
TEI_NS = "http://www.tei-c.org/ns/1.0"
TEI = {"tei": TEI_NS}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _reseal(path: Path, member_name: str) -> CandidatePackage:
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    content = (path / member_name).read_bytes()
    record = next(item for item in manifest["members"] if item["name"] == member_name)
    record.update(bytes=len(content), sha256=_sha(content))
    manifest_path.write_bytes(_canonical(manifest))
    return CandidatePackage.load(path)


def _clone(candidate: CandidatePackage, path: Path) -> Path:
    shutil.copytree(candidate.path, path)
    return path


@pytest.fixture(scope="module")
def verified_candidate(tmp_path_factory: pytest.TempPathFactory):
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    output = tmp_path_factory.mktemp("npnf2-lib046-candidate")
    candidate = reconstruct(source, output / "candidate", _convert)
    report = validate(source, candidate, _oracle)
    record = {
        "contract": "ocd-validation-report-v1",
        "status": report.status,
        "candidate_sha256": report.candidate_sha256,
        "source_manifest_sha256": report.source_manifest_sha256,
        "attestation": dict(report.attestation),
        "findings": list(report.findings),
    }
    assert _sha(_canonical(record)) == report.sha256
    validation_path = output / "validation.json"
    validation_path.write_bytes(_canonical({**record, "report_sha256": report.sha256}))
    return source, candidate, validation_path


def test_exact_source_and_three_root_order() -> None:
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    assert SOURCES == (
        (
            "npnf208",
            "raw/ccel/npnf2/npnf208.xml",
            3_303_323,
            "95cf3dafefccec80e0949a03c7f1f605da293302d0dc7a8bd62a4e711a0c5532",
        ),
    )
    assert ASSIGNED == ORACLE_ASSIGNED == (
        ("npnf208", "vii", "basil-of-caesarea-on-the-holy-spirit"),
        ("npnf208", "viii", "basil-of-caesarea-hexaemeron"),
        ("npnf208", "ix", "basil-of-caesarea-letters"),
    )
    assert EXPECTED_CENSUS == ORACLE_CENSUS == {
        "elements": 14_341,
        "attributes": 30_629,
        "text_nodes": 10_388,
        "tail_nodes": 10_481,
        "characters": 1_733_532,
        "non_ascii_characters": 41_065,
        "notes": 2_592,
        "page_breaks": 326,
        "scripture_refs": 1_281,
    }
    source.verify()
    retained = source.authority_path("retained-npnf208").read_bytes()
    assert len(retained) == SOURCES[0][2]
    assert _sha(retained) == SOURCES[0][3]


def test_candidate_is_p5_valid_and_independently_verified(verified_candidate) -> None:
    source, candidate, validation_path = verified_candidate
    tree = etree.parse(str(candidate.path / "content.tei.xml"))
    schema = etree.XMLSchema(
        etree.parse(str(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd"))
    )
    schema.assertValid(tree)
    assert validate(source, candidate, _oracle).status == "pass"
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    assert accountability["assigned_census"] == EXPECTED_CENSUS
    assert accountability["feature_count"] == 14_341
    assert accountability["attribute_count"] == 30_629
    assert [item["work_id"] for item in accountability["work_bindings"]] == [
        item[2] for item in ASSIGNED
    ]
    assert [item["source_root_id"] for item in accountability["work_bindings"]] == [
        "vii",
        "viii",
        "ix",
    ]
    assert [item["work_id"] for item in accountability["work_bindings"]] == [
        "basil-of-caesarea-on-the-holy-spirit",
        "basil-of-caesarea-hexaemeron",
        "basil-of-caesarea-letters",
    ]
    assert validation_path.is_file()


def test_provenance_preserves_credit_and_attribution_caveat(verified_candidate) -> None:
    _source, candidate, _validation = verified_candidate
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    evidence = provenance["sources"]["npnf208"][
        "retained_title_page_and_preface_credit_evidence"
    ]
    evidence_text = " ".join(evidence.values()).casefold()
    assert "philip schaff" in evidence_text
    assert "henry wace" in evidence_text
    assert "blomfield jackson" in evidence_text
    unresolved = candidate.member_bytes("unresolved.jsonl").decode().splitlines()
    unresolved_ids = {json.loads(line)["id"] for line in unresolved}
    assert "npnf2-lib046-work-specific-credit-allocation" in unresolved_ids
    assert "npnf2-lib046-rights-human-acceptance-publication" in unresolved_ids


def test_oracle_rejects_resealed_text_mutation(verified_candidate, tmp_path: Path) -> None:
    source, candidate, _validation = verified_candidate
    target = _clone(candidate, tmp_path / "text-mutation")
    tree = etree.parse(str(target / "content.tei.xml"))
    paragraph = tree.xpath("//tei:body/tei:div[1]//tei:p", namespaces=TEI)[0]
    paragraph.text = (paragraph.text or "") + " invented text"
    (target / "content.tei.xml").write_bytes(
        etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=False)
    )
    mutated = _reseal(target, "content.tei.xml")
    with pytest.raises(ValueError, match="TEI direct text or tail drift"):
        _oracle(source, mutated)


def test_oracle_rejects_resealed_root_swap(verified_candidate, tmp_path: Path) -> None:
    source, candidate, _validation = verified_candidate
    target = _clone(candidate, tmp_path / "root-swap")
    tree = etree.parse(str(target / "content.tei.xml"))
    body = tree.xpath("//tei:body", namespaces=TEI)[0]
    first, second, third = body[:]
    body.remove(first)
    body.remove(second)
    body.remove(third)
    body.extend([second, first, third])
    (target / "content.tei.xml").write_bytes(
        etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=False)
    )
    mutated = _reseal(target, "content.tei.xml")
    with pytest.raises(ValueError):
        _oracle(source, mutated)


def test_oracle_rejects_resealed_evidence_mutation(verified_candidate, tmp_path: Path) -> None:
    source, candidate, _validation = verified_candidate
    target = _clone(candidate, tmp_path / "evidence-mutation")
    path = target / "provenance.json"
    provenance = json.loads(path.read_bytes())
    provenance["sources"]["npnf208"]["display_credit_names"].append("Invented Editor")
    path.write_bytes(_canonical(provenance))
    mutated = _reseal(target, "provenance.json")
    with pytest.raises(ValueError, match="source metadata, rights, credit, or state drift"):
        _oracle(source, mutated)


def test_oracle_closure_is_source_local_and_excludes_converter() -> None:
    policy = json.loads(
        (ROOT / "sources/structured-text/npnf2-lib046/npnf2-lib046.validation-policy.json").read_bytes()
    )
    paths = {path.relative_to(ROOT).as_posix() for path in _closure_paths(ROOT, policy)}
    assert "build/tei/npnf2_lib046_oracle.py" in paths
    assert "build/tei/npnf2_lib046_reconstruction.py" not in paths
    manifest = json.loads(MANIFEST.read_bytes())
    assert _closure_digest(ROOT, policy) == manifest["validator"]["import_closure_sha256"]
