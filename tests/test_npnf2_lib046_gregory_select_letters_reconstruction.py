from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

from lxml import etree
import pytest

from build.tei.npnf2_lib046_gregory_select_letters_oracle import (
    EXPECTED_CENSUS,
    EXPECTED_DOCUMENT_CENSUS,
    _closure_digest,
    _closure_paths,
    _oracle,
)
from build.tei.npnf2_lib046_gregory_select_letters_reconstruction import (
    SOURCE_BYTES,
    SOURCE_SHA256,
    _convert,
)
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, reconstruct, validate
from build.lib.tei_xsd import compiled_tei_schema


pytestmark = [
    pytest.mark.slow,
    pytest.mark.xdist_group(name="npnf2-lib046-gregory-select-letters"),
]

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'tests/fixtures/reconstruction-runtime/gregory-select-letters.source-manifest.json'
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
    member = next(item for item in manifest["members"] if item["name"] == member_name)
    member.update(bytes=len(content), sha256=_sha(content))
    manifest_path.write_bytes(_canonical(manifest))
    return CandidatePackage.load(path)


def _clone(candidate: CandidatePackage, path: Path) -> Path:
    shutil.copytree(candidate.path, path)
    return path


@pytest.fixture(scope="module")
def verified_candidate(tmp_path_factory: pytest.TempPathFactory):
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    output = tmp_path_factory.mktemp("npnf2-lib046-gregory-candidate")
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


def test_exact_source_identity_and_assigned_root_order() -> None:
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    source.verify()
    retained = source.authority_path("retained-npnf207")
    content = retained.read_bytes()
    assert len(content) == SOURCE_BYTES
    assert _sha(content) == SOURCE_SHA256
    tree = etree.parse(str(retained))
    body = tree.getroot().find("ThML.body")
    assert body is not None
    assert [node.get("id") for node in body] == ["i", "ii", "iii", "iv", "v"]
    assigned = body.find("./div1[@id='iv']")
    assert assigned is not None
    assert assigned.get("title") == "Select Letters of Saint Gregory Nazianzen."
    assert [node.get("id") for node in assigned.findall("div2")] == [
        "iv.i",
        "iv.ii",
        "iv.iii",
        "iv.iv",
    ]
    assert "Proofed" in "".join(tree.xpath("/ThML/ThML.head/electronicEdInfo/DC/DC.Subject[@scheme='ccel']/text()"))


def test_candidate_is_p5_valid_and_independently_verified(verified_candidate) -> None:
    source, candidate, validation_path = verified_candidate
    tree = etree.parse(str(candidate.path / "content.tei.xml"))
    schema = compiled_tei_schema(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd")
    schema.assertValid(tree)
    report = validate(source, candidate, _oracle)
    assert report.status == "pass"
    assert validation_path.is_file()
    assert report.attestation["source_sha256"] == SOURCE_SHA256
    assert report.attestation["xsd_sha256"]
    assert report.attestation["policy_sha256"]


def test_accounting_and_provenance_cover_full_member_and_scope(verified_candidate) -> None:
    _source, candidate, _validation = verified_candidate
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    assert accountability["assigned_census"] == EXPECTED_CENSUS
    assert accountability["complete_document_census"] == EXPECTED_DOCUMENT_CENSUS
    assert accountability["feature_count"] == EXPECTED_CENSUS["elements"]
    assert accountability["attribute_count"] == EXPECTED_CENSUS["attributes"]
    assert accountability["omitted_feature_count"] == 0
    assert accountability["duplicate_feature_count"] == 0
    assert len(accountability["crosswalk"]) == EXPECTED_CENSUS["elements"]
    assert [item["id"] for item in accountability["top_level_division_accounting"]] == [
        "i",
        "ii",
        "iii",
        "iv",
        "v",
    ]
    assert [item["id"] for item in accountability["direct_div2_accounting"]] == [
        "iv.i",
        "iv.ii",
        "iv.iii",
        "iv.iv",
    ]
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    assert provenance["status"] == "nonaccepted"
    assert provenance["publication_state"] == "not_ready"
    assert provenance["scope"]["source_root_id"] == "iv"
    assert provenance["sources"]["npnf207"]["display_credit_names"] == [
        "Philip Schaff",
        "Henry Wace",
        "Charles Gordon Browne",
        "James Edward Swallow",
    ]
    assert "Charles Gordon Browne" in provenance["sources"]["npnf207"]["retained_title_page_and_preface_credit_evidence"]["iii.i-p6"]
    assert candidate.member_bytes("README.source.md").startswith(b"# LIB-046 retained source")


def test_oracle_rejects_resealed_text_mutation(verified_candidate, tmp_path: Path) -> None:
    source, candidate, _validation = verified_candidate
    target = _clone(candidate, tmp_path / "text-mutation")
    tree = etree.parse(str(target / "content.tei.xml"))
    paragraph = tree.xpath("//tei:p", namespaces=TEI)[-1]
    paragraph.text = (paragraph.text or "") + " invented text"
    (target / "content.tei.xml").write_bytes(
        etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=False)
    )
    mutated = _reseal(target, "content.tei.xml")
    with pytest.raises(ValueError, match="TEI direct text drift"):
        _oracle(source, mutated)


def test_oracle_rejects_resealed_child_reordering(verified_candidate, tmp_path: Path) -> None:
    source, candidate, _validation = verified_candidate
    target = _clone(candidate, tmp_path / "reordered")
    tree = etree.parse(str(target / "content.tei.xml"))
    work = tree.xpath("//tei:body/tei:div", namespaces=TEI)[0]
    divisions = [child for child in work if etree.QName(child).localname == "div"]
    assert len(divisions) == 4
    first, second = divisions[:2]
    work.remove(first)
    work.remove(second)
    work.insert(1, second)
    work.insert(2, first)
    (target / "content.tei.xml").write_bytes(
        etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=False)
    )
    mutated = _reseal(target, "content.tei.xml")
    with pytest.raises(ValueError, match="source root order|TEI attribute drift|TEI direct text drift|child count drift"):
        _oracle(source, mutated)


def test_oracle_rejects_resealed_accountability_invention(verified_candidate, tmp_path: Path) -> None:
    source, candidate, _validation = verified_candidate
    target = _clone(candidate, tmp_path / "accountability-mutation")
    path = target / "source-accountability.json"
    account = json.loads(path.read_bytes())
    account["crosswalk"][0]["source_xml_id"] = "invented-source-id"
    path.write_bytes(_canonical(account))
    mutated = _reseal(target, "source-accountability.json")
    with pytest.raises(ValueError, match="source-accountability"):
        _oracle(source, mutated)


def test_oracle_closure_is_local_and_excludes_converter() -> None:
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    policy = json.loads(source.authority_path("validation-policy").read_bytes())
    paths = {path.relative_to(ROOT).as_posix() for path in _closure_paths(ROOT, policy)}
    assert "build/tei/npnf2_lib046_gregory_select_letters_oracle.py" in paths
    assert "build/tei/npnf2_lib046_gregory_select_letters_reconstruction.py" not in paths
    assert _closure_digest(ROOT, policy) == source.record["validator"]["import_closure_sha256"]


def test_fresh_process_different_cwd_reproduces_every_package_member(
    verified_candidate, tmp_path: Path
) -> None:
    _source, candidate, _validation = verified_candidate
    destination = tmp_path / "fresh-process-candidate"
    script = (
        "import sys; from pathlib import Path; "
        "root=Path(sys.argv[1]).resolve(); sys.path.insert(0,str(root)); "
        "from ocd_kernel.reconstruction import SourceManifest,reconstruct; "
        "from build.tei.npnf2_lib046_gregory_select_letters_reconstruction import _convert; "
        "source=SourceManifest.load(Path(sys.argv[2]),repository_root=root); "
        "reconstruct(source,Path(sys.argv[3]),_convert)"
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(ROOT), str(MANIFEST), str(destination)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    fresh = CandidatePackage.load(destination)
    assert fresh.member_names == candidate.member_names
    assert all(
        fresh.member_bytes(name) == candidate.member_bytes(name)
        for name in candidate.member_names
    )
