from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap

from lxml import etree
import pytest

from build.tei.hodge_systematic_theology_vol_1_oracle import (
    _closure_digest,
    _closure_paths,
    _oracle,
)
from build.tei.hodge_systematic_theology_vol_1_reconstruction import (
    ASSIGNED_ROOTS,
    SOURCE_BYTES,
    SOURCE_PATH,
    SOURCE_SHA256,
    TOP_LEVEL_IDS,
    _convert,
)
from ocd_kernel.reconstruction import (
    CandidatePackage,
    SourceManifest,
    reconstruct,
    validate,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = (
    ROOT / "tests/fixtures/reconstruction-runtime/hodge-systematic-theology-vol-1.source-manifest.json"
)
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
    output = tmp_path_factory.mktemp("hodge-vol-1-candidate")
    candidate = reconstruct(source, output / "candidate", _convert)
    report = validate(source, candidate, _oracle)
    report_record = {
        "attestation": dict(report.attestation),
        "candidate_sha256": report.candidate_sha256,
        "contract": "ocd-validation-report-v1",
        "findings": list(report.findings),
        "source_manifest_sha256": report.source_manifest_sha256,
        "status": report.status,
    }
    assert _sha(_canonical(report_record)) == report.sha256
    return source, candidate, report


def test_exact_source_binding_envelope_and_independent_accounting() -> None:
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    retained = source.authority_path("retained-hodge-vol-1").read_bytes()
    assert SOURCE_PATH == "raw/ccel/hodge/theology1.xml"
    assert len(retained) == SOURCE_BYTES == 2_243_559
    assert _sha(retained) == SOURCE_SHA256
    assert ASSIGNED_ROOTS == (
        ("hodge-vol-1", "iii", "hodge-systematic-theology-vol-1"),
        ("hodge-vol-1", "iv", "hodge-systematic-theology-vol-1"),
    )
    assert TOP_LEVEL_IDS == ("i", "ii", "iii", "iv", "v")
    config = json.loads(source.authority_path("work-config").read_bytes())
    assert config["source_hash"] == f"sha256:{SOURCE_SHA256}"
    assert config["source_url"] == "https://www.ccel.org/ccel/hodge/theology1.xml"
    source.verify()


def test_candidate_is_p5_valid_and_independently_verified(verified_candidate) -> None:
    source, candidate, report = verified_candidate
    tree = etree.parse(str(candidate.path / "content.tei.xml"))
    schema = etree.XMLSchema(
        etree.parse(str(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd"))
    )
    schema.assertValid(tree)
    assert report.status == "pass"
    assert validate(source, candidate, _oracle).status == "pass"
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    assert accountability["assigned_census"]["elements"] == 6632
    assert accountability["assigned_census"]["attributes"] == 12864
    assert accountability["assigned_census"]["notes"] == 610
    assert accountability["assigned_census"]["page_breaks"] == 647
    assert accountability["assigned_census"]["scripture_refs"] == 623
    assert accountability["feature_count"] == 6632
    assert len(accountability["crosswalk"]) == 6632
    assert [item["id"] for item in accountability["root_accounting"]] == list(TOP_LEVEL_IDS)
    assert [item["disposition"] for item in accountability["root_accounting"]] == [
        "source-evidence-outside-work-projection",
        "source-evidence-outside-work-projection",
        "assigned-work-root-represented",
        "assigned-work-root-represented",
        "source-evidence-outside-work-projection",
    ]
    assert [item["feature_count"] for item in accountability["root_bindings"]] == [
        1696,
        4936,
    ]
    member = accountability["member_accounting"][0]
    assert member["complete_document_census"]["elements"] == 10943
    assert member["complete_document_census"]["attributes"] == 19073
    assert member["excluded_scope_census"]["elements"] == 4311
    assert member["assigned_scope_census"] == accountability["assigned_census"]


def test_oracle_rejects_resealed_text_mutation(verified_candidate, tmp_path: Path) -> None:
    source, candidate, _report = verified_candidate
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


def test_oracle_rejects_resealed_root_reordering(
    verified_candidate, tmp_path: Path
) -> None:
    source, candidate, _report = verified_candidate
    target = _clone(candidate, tmp_path / "root-reordering")
    tree = etree.parse(str(target / "content.tei.xml"))
    body = tree.xpath("//tei:body", namespaces=TEI)[0]
    first, second = body[:2]
    body.remove(first)
    body.remove(second)
    body.extend([second, first])
    (target / "content.tei.xml").write_bytes(
        etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=False)
    )
    mutated = _reseal(target, "content.tei.xml")
    with pytest.raises(ValueError):
        _oracle(source, mutated)


def test_oracle_rejects_resealed_accounting_mutation(
    verified_candidate, tmp_path: Path
) -> None:
    source, candidate, _report = verified_candidate
    target = _clone(candidate, tmp_path / "accounting-mutation")
    path = target / "source-accountability.json"
    accountability = json.loads(path.read_bytes())
    accountability["omitted_feature_count"] = 1
    path.write_bytes(_canonical(accountability))
    mutated = _reseal(target, "source-accountability.json")
    with pytest.raises(ValueError, match="source-accountability drift"):
        _oracle(source, mutated)


def test_oracle_rejects_resealed_provenance_mutation(
    verified_candidate, tmp_path: Path
) -> None:
    source, candidate, _report = verified_candidate
    target = _clone(candidate, tmp_path / "provenance-mutation")
    path = target / "provenance.json"
    provenance = json.loads(path.read_bytes())
    provenance["sources"]["hodge-vol-1"]["config_claims"]["title"] = "Invented title"
    path.write_bytes(_canonical(provenance))
    mutated = _reseal(target, "provenance.json")
    with pytest.raises(ValueError, match="provenance metadata or state drift"):
        _oracle(source, mutated)


def test_oracle_closure_is_entry_local_and_excludes_producer() -> None:
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    policy = json.loads(source.authority_path("validation-policy").read_bytes())
    paths = {path.relative_to(ROOT).as_posix() for path in _closure_paths(ROOT, policy)}
    assert "build/tei/hodge_systematic_theology_vol_1_oracle.py" in paths
    assert "build/tei/hodge_systematic_theology_vol_1_reconstruction.py" not in paths
    assert "build/parsers/ccel_hodge_systematic.py" not in paths
    assert _closure_digest(ROOT, policy) == source.record["validator"][
        "import_closure_sha256"
    ]


def test_fresh_process_different_cwd_is_byte_deterministic(
    verified_candidate, tmp_path: Path
) -> None:
    source, candidate, _report = verified_candidate
    other_cwd = tmp_path / "different-cwd"
    other_cwd.mkdir()
    destination_a = tmp_path / "subprocess-a"
    destination_b = tmp_path / "subprocess-b"
    script = textwrap.dedent(
        """
        import hashlib
        import json
        from pathlib import Path
        import sys
        from ocd_kernel.reconstruction import SourceManifest, reconstruct, validate
        from build.tei.hodge_systematic_theology_vol_1_oracle import _oracle
        from build.tei.hodge_systematic_theology_vol_1_reconstruction import _convert

        root = Path(sys.argv[1])
        manifest = SourceManifest.load(Path(sys.argv[2]), repository_root=root)
        outputs = []
        for destination in (Path(sys.argv[3]), Path(sys.argv[4])):
            package = reconstruct(manifest, destination, _convert)
            report = validate(manifest, package, _oracle)
            outputs.append({
                "candidate_sha256": package.sha256,
                "validation_sha256": report.sha256,
                "members": {
                    name: hashlib.sha256(package.member_bytes(name)).hexdigest()
                    for name in package.member_names
                },
            })
        print(json.dumps(outputs, sort_keys=True))
        """
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        item for item in (str(ROOT), environment.get("PYTHONPATH", "")) if item
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(ROOT),
            str(MANIFEST),
            str(destination_a),
            str(destination_b),
        ],
        cwd=other_cwd,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    subprocess_runs = json.loads(result.stdout)
    expected_members = {
        name: _sha(candidate.member_bytes(name)) for name in candidate.member_names
    }
    assert len(subprocess_runs) == 2
    assert subprocess_runs[0] == subprocess_runs[1]
    assert subprocess_runs[0]["candidate_sha256"] == candidate.sha256
    assert subprocess_runs[0]["members"] == expected_members
