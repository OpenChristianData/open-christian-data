from __future__ import annotations

import ast
import copy
import hashlib
import itertools
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from jsonschema import Draft202012Validator
from lxml import etree
import pytest

from ocd_kernel.reconstruction.contract import CandidatePackage, validate
from build.lib.tei_xsd import compiled_tei_schema


ROOT = Path(__file__).resolve().parents[1]
RAW = Path("D:/Library/Open Christian Data/raw/gutenberg")
SOURCE_ROOT = ROOT / "sources/gutenberg-theology-systematics"
SOURCES = {
    "dabney-systematic-theology": ("syllabusnotesof00dabn_djvu.txt", 2_440_828, "2db4ddb5b9684e64797a2a963c55fef5b859affbd140291a758c464e24d4658a", 36_714),
    "miley-systematic-theology-vol-1": ("systematictheolo01mile_djvu.txt", 1_684_078, "ae20e73d6895a4f88d207e2f9991107252bc59875166c6eb7435e862abbd22f3", 28_411),
    "miley-systematic-theology-vol-2": ("systematictheolo02mile_djvu.txt", 1_658_840, "c6d86e0e335345d358b97c961ec660f3a8c7c06c4e53ca218802e159945416f0", 30_722),
    "shedd-dogmatic-theology-vol-1": ("dogmatictheology01sheduoft_djvu.txt", 1_309_299, "bb27e8a8bd3b3eb603bd822982786dc83817cca574b79c97ef10d00c129ce58a", 22_524),
    "shedd-dogmatic-theology-vol-2": ("dogmatictheology02sheduoft_djvu.txt", 1_989_151, "18a47d3f1dc36cbada22bb9ad017414af33762af65e2d253c773654c2764c534", 35_767),
    "shedd-dogmatic-theology-vol-3": ("dogmatictheology03shed_0_djvu.txt", 1_103_532, "3fa48483098ff8372c30d4e96b1dca986bd745ae1f4f309f124b750290f7b62a", 22_818),
}
NS = {"tei": "http://www.tei-c.org/ns/1.0"}
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _manifest(work_id: str) -> Path:
    return SOURCE_ROOT / work_id / "source-manifest.json"


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def _resealed_source_id_manifest(work_id: str, repository_root: Path) -> Path:
    record = json.loads(_manifest(work_id).read_bytes())
    record["source_id"] = f"resealed-{work_id}"
    for authority in record["authorities"]:
        if authority["role"] == "primary-source":
            continue
        source = ROOT / authority["path"]
        destination = repository_root / authority["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    for binding_name in ("converter", "validator"):
        source = ROOT / record[binding_name]["implementation_path"]
        destination = repository_root / record[binding_name]["implementation_path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    for package_file in ("build/__init__.py", "build/tei/__init__.py"):
        destination = repository_root / package_file
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / package_file, destination)
    path = repository_root / _manifest(work_id).relative_to(ROOT)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical(record))
    return path


@pytest.mark.parametrize("work_id", tuple(SOURCES))
def test_exact_external_witness_identity_and_line_census(work_id: str) -> None:
    from build.tei.lib015_gutenberg_theology_reconstruction import inspect_witness

    filename, byte_count, digest, line_count = SOURCES[work_id]
    witness = inspect_witness(work_id, RAW / filename)
    assert witness.byte_count == byte_count
    assert witness.sha256 == digest
    assert len(witness.lines) == line_count
    assert witness.content.endswith(b"\n")
    assert b"\r" not in witness.content


@pytest.mark.parametrize("work_id", tuple(SOURCES))
def test_candidate_is_lossless_dual_schema_valid_nonaccepted_and_oracle_accepted(work_id: str, tmp_path: Path) -> None:
    from build.tei.lib015_gutenberg_theology_oracle import _oracle
    from build.tei.lib015_gutenberg_theology_reconstruction import build_candidate, load_source_manifest

    filename, byte_count, digest, line_count = SOURCES[work_id]
    manifest = load_source_manifest(_manifest(work_id), repository_root=ROOT, witness_path=RAW / filename)
    candidate = build_candidate(manifest, tmp_path / "candidate")
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    Draft202012Validator(json.loads((SOURCE_ROOT / "source-accountability.schema.json").read_bytes())).validate(accountability)
    compiled_tei_schema(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd").assertValid(etree.ElementTree(etree.fromstring(candidate.member_bytes("content.tei.xml"))))
    assert candidate.manifest["status"] == "nonaccepted"
    assert accountability["source_bytes"] == byte_count
    assert accountability["source_sha256"] == digest
    assert accountability["physical_lines"] == accountability["represented_lines"] == line_count
    assert accountability["omitted_lines"] == accountability["duplicated_lines"] == 0
    assert len(accountability["crosswalk"]) == line_count
    assert accountability["crosswalk"][0]["byte_start"] == 0
    assert accountability["crosswalk"][-1]["byte_end"] == byte_count
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    assert provenance["candidate_status"] == "nonaccepted"
    assert provenance["publication_authorized"] is False
    assert provenance["technical_validation_is_human_acceptance"] is False
    report = validate(manifest, candidate, _oracle)  # type: ignore[arg-type]
    assert report.status == "pass"
    assert report.findings == ()
    assert report.attestation["source_sha256"] == digest


@pytest.mark.parametrize("work_id", tuple(SOURCES))
def test_oracle_rejects_coupled_source_id_manifest_reseal(work_id: str, tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    manifest_path = _resealed_source_id_manifest(work_id, repository_root)
    script = """
from pathlib import Path
import sys

from build.tei.lib015_gutenberg_theology_oracle import _oracle
from build.tei.lib015_gutenberg_theology_reconstruction import build_candidate, load_source_manifest
from ocd_kernel.reconstruction.contract import validate

repository_root = Path(sys.argv[1])
manifest_path = Path(sys.argv[2])
witness_path = Path(sys.argv[3])
candidate_path = Path(sys.argv[4])
expected_source_id = sys.argv[5]
manifest = load_source_manifest(manifest_path, repository_root=repository_root, witness_path=witness_path)
candidate = build_candidate(manifest, candidate_path)
assert candidate.manifest["source_id"] == expected_source_id
try:
    validate(manifest, candidate, _oracle)
except ValueError as exc:
    assert "source identity drift" in str(exc)
else:
    raise AssertionError("coupled source_id reseal was accepted")
"""
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            script,
            str(repository_root),
            str(manifest_path),
            str(RAW / SOURCES[work_id][0]),
            str(tmp_path / "candidate"),
            f"resealed-{work_id}",
        ],
        cwd=repository_root,
        env={**os.environ, "PYTHONPATH": os.pathsep.join((str(repository_root), str(ROOT)))},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_oracle_has_no_producer_dependency_and_scope_is_lib015_only() -> None:
    path = ROOT / "build/tei/lib015_gutenberg_theology_oracle.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert "build.tei.lib015_gutenberg_theology_reconstruction" not in imports
    assert "_convert" not in source
    assert set(SOURCES) == {
        "dabney-systematic-theology", "miley-systematic-theology-vol-1", "miley-systematic-theology-vol-2",
        "shedd-dogmatic-theology-vol-1", "shedd-dogmatic-theology-vol-2", "shedd-dogmatic-theology-vol-3",
    }


def _reseal(path: Path, name: str, content: bytes) -> CandidatePackage:
    (path / name).write_bytes(content)
    manifest = json.loads((path / "manifest.json").read_bytes())
    member = next(item for item in manifest["members"] if item["name"] == name)
    member["bytes"] = len(content)
    member["sha256"] = hashlib.sha256(content).hexdigest()
    (path / "manifest.json").write_bytes(_canonical(manifest))
    return CandidatePackage.load(path)


@pytest.fixture(scope="module")
def mutation_bundle(tmp_path_factory: pytest.TempPathFactory) -> tuple[object, CandidatePackage]:
    from build.tei.lib015_gutenberg_theology_reconstruction import build_candidate, load_source_manifest

    work_id = "shedd-dogmatic-theology-vol-3"
    root = tmp_path_factory.mktemp("lib015-mutation")
    manifest = load_source_manifest(_manifest(work_id), repository_root=ROOT, witness_path=RAW / SOURCES[work_id][0])
    return manifest, build_candidate(manifest, root / "candidate")


@pytest.mark.parametrize("mutation", ["omission", "duplication", "reordering", "text", "uncertainty", "scope", "metadata", "front-matter", "back-matter", "extra-header-claim", "leaf-child-invention", "container-attribute-invention", "root-attribute-invention", "title-statement-text-invention", "provenance", "unresolved", "crosswalk", "manifest-source", "manifest-converter", "package-extra-member"])
def test_oracle_rejects_resealed_fidelity_and_binding_mutations(mutation: str, tmp_path: Path, mutation_bundle: tuple[object, CandidatePackage]) -> None:
    from build.tei.lib015_gutenberg_theology_oracle import _oracle

    manifest, candidate = mutation_bundle
    path = tmp_path / mutation
    shutil.copytree(candidate.path, path)
    if mutation in {"omission", "duplication", "reordering", "text", "uncertainty", "scope", "metadata", "front-matter", "back-matter", "extra-header-claim", "leaf-child-invention", "container-attribute-invention", "root-attribute-invention", "title-statement-text-invention"}:
        root = etree.fromstring((path / "content.tei.xml").read_bytes())
        nodes = root.xpath("./tei:text/tei:body/tei:div/tei:ab", namespaces=NS)
        if mutation == "omission":
            nodes[100].getparent().remove(nodes[100])
        elif mutation == "duplication":
            duplicate = copy.deepcopy(nodes[100]); duplicate.set(XML_ID, "invented-duplicate"); nodes[100].addnext(duplicate)
        elif mutation == "reordering":
            parent = nodes[100].getparent(); parent.remove(nodes[100]); parent.insert(102, nodes[100])
        elif mutation == "text":
            nodes[100].text = (nodes[100].text or "") + " invented"
        elif mutation == "uncertainty":
            nodes[100].set("ana", "#source-line #accepted-reading")
        elif mutation == "scope":
            nodes[0].getparent().set(XML_ID, "another-work-retained-lines")
        elif mutation == "metadata":
            root.xpath("./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title", namespaces=NS)[0].text = "Accepted edition"
        elif mutation == "front-matter":
            text_node = root.xpath("./tei:text", namespaces=NS)[0]
            front = etree.Element("{http://www.tei-c.org/ns/1.0}front")
            div = etree.SubElement(front, "{http://www.tei-c.org/ns/1.0}div")
            etree.SubElement(div, "{http://www.tei-c.org/ns/1.0}p").text = "Invented accepted front matter"
            text_node.insert(0, front)
        elif mutation == "back-matter":
            text_node = root.xpath("./tei:text", namespaces=NS)[0]
            back = etree.SubElement(text_node, "{http://www.tei-c.org/ns/1.0}back")
            div = etree.SubElement(back, "{http://www.tei-c.org/ns/1.0}div")
            etree.SubElement(div, "{http://www.tei-c.org/ns/1.0}p").text = "Invented accepted back matter"
        elif mutation == "extra-header-claim":
            revision = root.xpath("./tei:teiHeader/tei:revisionDesc", namespaces=NS)[0]
            etree.SubElement(revision, "{http://www.tei-c.org/ns/1.0}change").text = "Human acceptance granted"
        elif mutation == "leaf-child-invention":
            paragraph = root.xpath("./tei:teiHeader/tei:fileDesc/tei:publicationStmt/tei:availability/tei:p", namespaces=NS)[0]
            etree.SubElement(paragraph, "{http://www.tei-c.org/ns/1.0}note").text = "Publication authorized"
        elif mutation == "container-attribute-invention":
            root.xpath("./tei:text", namespaces=NS)[0].set("{http://www.w3.org/XML/1998/namespace}lang", "en")
        elif mutation == "root-attribute-invention":
            root.set("{http://www.w3.org/XML/1998/namespace}lang", "en")
        else:
            root.xpath("./tei:teiHeader/tei:fileDesc/tei:titleStmt", namespaces=NS)[0].text = " "
        mutated = _reseal(path, "content.tei.xml", etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False))
    elif mutation == "provenance":
        value = json.loads((path / "provenance.json").read_bytes()); value["publication_authorized"] = True
        mutated = _reseal(path, "provenance.json", _canonical(value))
    elif mutation == "unresolved":
        lines = (path / "unresolved.jsonl").read_bytes().splitlines(); value = json.loads(lines[1]); value["detail"] = "accepted"; lines[1] = _canonical(value).rstrip(b"\n")
        mutated = _reseal(path, "unresolved.jsonl", b"\n".join(lines) + b"\n")
    elif mutation == "crosswalk":
        value = json.loads((path / "source-accountability.json").read_bytes()); value["crosswalk"][100]["target"] = "#wrong"; value["crosswalk_sha256"] = hashlib.sha256(_canonical(value["crosswalk"])).hexdigest()
        mutated = _reseal(path, "source-accountability.json", _canonical(value))
    elif mutation in {"manifest-source", "manifest-converter"}:
        value = json.loads((path / "manifest.json").read_bytes())
        if mutation == "manifest-source":
            value["source_manifest"]["sha256"] = "0" * 64
        else:
            value["converter"]["id"] = "invented-converter"
        (path / "manifest.json").write_bytes(_canonical(value))
        mutated = CandidatePackage.load(path)
    else:
        invented = b"invented package member\n"
        (path / "invented.txt").write_bytes(invented)
        value = json.loads((path / "manifest.json").read_bytes())
        value["members"].append({"bytes": len(invented), "name": "invented.txt", "sha256": hashlib.sha256(invented).hexdigest()})
        value["members"] = sorted(value["members"], key=lambda item: item["name"])
        (path / "manifest.json").write_bytes(_canonical(value))
        with pytest.raises(ValueError, match="exactly six flat members"):
            CandidatePackage.load(path)
        return
    with pytest.raises(ValueError):
        validate(manifest, mutated, _oracle)  # type: ignore[arg-type]


def test_mutated_or_wrong_scope_witness_fails_closed(tmp_path: Path) -> None:
    from build.tei.lib015_gutenberg_theology_reconstruction import inspect_witness

    work_id = "shedd-dogmatic-theology-vol-3"
    content = bytearray((RAW / SOURCES[work_id][0]).read_bytes())
    content[100] ^= 1
    mutated = tmp_path / "mutated.txt"
    mutated.write_bytes(content)
    with pytest.raises(ValueError, match="identity drift"):
        inspect_witness(work_id, mutated)
    with pytest.raises(ValueError, match="outside LIB-015"):
        inspect_witness("hooker-ecclesiastical-polity", RAW / SOURCES[work_id][0])


@pytest.mark.parametrize("work_id", tuple(SOURCES))
def test_fresh_process_different_cwd_packages_are_byte_identical(work_id: str, tmp_path: Path) -> None:
    filename = SOURCES[work_id][0]
    outputs = [tmp_path / "first", tmp_path / "second"]
    for output, cwd in zip(outputs, [ROOT, tmp_path], strict=True):
        subprocess.run([sys.executable, "-B", "-m", "build.tei.lib015_gutenberg_theology_reconstruction", "--repository-root", str(ROOT), "--manifest", str(_manifest(work_id)), "--witness", str(RAW / filename), "--output", str(output)], cwd=cwd, env={**os.environ, "PYTHONPATH": str(ROOT)}, check=True, capture_output=True, text=True)
    names = ["README.source.md", "content.tei.xml", "manifest.json", "provenance.json", "source-accountability.json", "unresolved.jsonl"]
    assert sorted(path.name for path in outputs[0].iterdir()) == sorted(path.name for path in outputs[1].iterdir()) == sorted(names)
    for name in names:
        assert (outputs[0] / name).read_bytes() == (outputs[1] / name).read_bytes()


def test_hooker_blocker_recomputes_all_18_simple_cohorts_and_creates_no_candidate() -> None:
    evidence_path = SOURCE_ROOT / "hooker-ecclesiastical-polity/LIB-015.hooker-blocked-source-evidence.json"
    evidence = json.loads(evidence_path.read_bytes())
    members = evidence["retained_members_in_likely_volume_order"]
    contents = {Path(item["path"]).name: (RAW / Path(item["path"]).name).read_bytes() for item in members}
    for item in members:
        content = contents[Path(item["path"]).name]
        assert len(content) == item["bytes"]
        assert content.count(b"\n") == item["physical_lines"]
        assert hashlib.sha256(content).hexdigest() == item["sha256"]
        content.decode("utf-8", errors="strict")
    observed = set()
    for order in itertools.permutations(contents):
        for separator in (b"", b"\n", b"\r\n"):
            observed.add(hashlib.sha256(separator.join(contents[name] for name in order)).hexdigest())
    assert len(observed) == 18
    assert observed == set(evidence["exhaustive_simple_cohort_probe"]["observed_sha256"])
    assert evidence["frozen_claim_sha256"] not in observed
    assert evidence["status"] == "blocked"
    assert evidence["tei_candidate_created"] is False
    assert evidence["publication_authorized"] is False
    assert not (SOURCE_ROOT / "hooker-ecclesiastical-polity/source-manifest.json").exists()
