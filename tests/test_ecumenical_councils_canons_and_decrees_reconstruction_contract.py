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

from build.tei.ecumenical_councils_canons_and_decrees_oracle import (
    ASSIGNED as ORACLE_ASSIGNED,
    EXPECTED_CENSUS as ORACLE_CENSUS,
    _closure_digest,
    _closure_paths,
    _oracle,
)
from build.tei.ecumenical_councils_canons_and_decrees_reconstruction import (
    ASSIGNED,
    EXPECTED_CENSUS,
    SOURCES,
    TOP_LEVEL_IDS,
    _convert,
)
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, reconstruct, validate


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'tests/fixtures/reconstruction-runtime/puritan-ecumenical-councils-canons-and-decrees.source-manifest.json'
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
    output = tmp_path_factory.mktemp("ecumenical-councils-candidate")
    candidate = reconstruct(source, output / "candidate", _convert)
    report = validate(source, candidate, _oracle)
    report_record = {
        "contract": "ocd-validation-report-v1",
        "status": report.status,
        "candidate_sha256": report.candidate_sha256,
        "source_manifest_sha256": report.source_manifest_sha256,
        "attestation": dict(report.attestation),
        "findings": list(report.findings),
    }
    assert _sha(_canonical(report_record)) == report.sha256
    return source, candidate, report


def test_exact_source_and_seven_root_order() -> None:
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    assert SOURCES == (
        (
            "npnf214",
            "raw/ccel/npnf2/npnf214.xml",
            3_196_008,
            "4ae3cb29edcb7b8e58bb9246049243c464b6839f88f6730f98b80122770b9bb4",
        ),
    )
    assert ASSIGNED == ORACLE_ASSIGNED == (
        ("npnf214", "vii", "ecumenical-councils-canons-and-decrees"),
        ("npnf214", "ix", "ecumenical-councils-canons-and-decrees"),
        ("npnf214", "x", "ecumenical-councils-canons-and-decrees"),
        ("npnf214", "xi", "ecumenical-councils-canons-and-decrees"),
        ("npnf214", "xii", "ecumenical-councils-canons-and-decrees"),
        ("npnf214", "xiii", "ecumenical-councils-canons-and-decrees"),
        ("npnf214", "xvi", "ecumenical-councils-canons-and-decrees"),
    )
    assert EXPECTED_CENSUS == ORACLE_CENSUS == {
        "elements": 7_502,
        "attributes": 14_097,
        "text_nodes": 5_803,
        "tail_nodes": 6_027,
        "characters": 1_182_705,
        "non_ascii_characters": 15_505,
        "notes": 257,
        "page_breaks": 312,
        "scripture_refs": 57,
    }
    source.verify()
    retained = source.authority_path("retained-npnf214").read_bytes()
    assert len(retained) == SOURCES[0][2]
    assert _sha(retained) == SOURCES[0][3]
    config = json.loads(source.authority_path("work-config").read_bytes())
    assert config["source_file"] == SOURCES[0][1]
    assert config["source_hash"] == "sha256:" + SOURCES[0][3]
    assert [item["id"] for item in config["source_roots"]] == [
        item[1] for item in ASSIGNED
    ]
    assert [item["selector"] for item in config["source_roots"]] == [
        "ThML.body/div1[7]",
        "ThML.body/div1[9]",
        "ThML.body/div1[10]",
        "ThML.body/div1[11]",
        "ThML.body/div1[12]",
        "ThML.body/div1[13]",
        "ThML.body/div1[16]",
    ]
    config_policy = json.loads(source.authority_path("work-config").read_bytes())
    assert config_policy["validation_policy"]["tei_topology"]["root_attributes"] == {
        "xml:id": "ecumenical-councils-canons-and-decrees-candidate"
    }


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
    assert accountability["assigned_census"] == EXPECTED_CENSUS
    assert accountability["feature_count"] == EXPECTED_CENSUS["elements"]
    assert accountability["attribute_count"] == EXPECTED_CENSUS["attributes"]
    assert len(accountability["crosswalk"]) == EXPECTED_CENSUS["elements"]
    assert [item["source_root_id"] for item in accountability["work_bindings"]] == [
        item[1] for item in ASSIGNED
    ]
    assert [item["feature_count"] for item in accountability["work_bindings"]] == [
        1_846,
        725,
        1_199,
        1_415,
        536,
        389,
        1_392,
    ]
    member = accountability["member_accounting"][0]
    assert member["complete_document_census"]["elements"] == 21_890
    assert member["assigned_scope_census"] == EXPECTED_CENSUS
    assert member["excluded_scope_census"]["elements"] == 14_388
    assert len(accountability["top_level_division_accounting"]["npnf214"]) == 18
    assert len(accountability["direct_div2_accounting"]["npnf214"]) == 162


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


def test_oracle_rejects_resealed_evidence_mutation(
    verified_candidate, tmp_path: Path
) -> None:
    source, candidate, _report = verified_candidate
    target = _clone(candidate, tmp_path / "evidence-mutation")
    path = target / "provenance.json"
    provenance = json.loads(path.read_bytes())
    provenance["sources"]["npnf214"]["display_credit_names"].append(
        "Invented Editor"
    )
    path.write_bytes(_canonical(provenance))
    mutated = _reseal(target, "provenance.json")
    with pytest.raises(ValueError, match="source metadata, rights, credit, or state drift"):
        _oracle(source, mutated)


def test_oracle_closure_is_entry_local_and_excludes_producer() -> None:
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    config = json.loads(source.authority_path("work-config").read_bytes())
    policy = config["validation_policy"]
    paths = {
        path.relative_to(ROOT).as_posix() for path in _closure_paths(ROOT, policy)
    }
    assert (
        "build/tei/ecumenical_councils_canons_and_decrees_oracle.py" in paths
    )
    assert (
        "build/tei/ecumenical_councils_canons_and_decrees_reconstruction.py"
        not in paths
    )
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
        from build.tei.ecumenical_councils_canons_and_decrees_oracle import _oracle
        from build.tei.ecumenical_councils_canons_and_decrees_reconstruction import _convert

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
