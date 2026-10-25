from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

from jsonschema import Draft202012Validator
from lxml import etree
import pytest

from build.tei.luther_galatians_oracle import (
    _closure as oracle_closure,
    _oracle,
    _stable,
)
from build.tei.luther_galatians_reconstruction import (
    CHAPTER_LINES,
    _closure as producer_closure,
    _counts,
    _records,
    _convert,
)
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "raw/gutenberg/pg1549.txt"
SOURCE_DIR = ROOT / "sources/structured-text/luther-commentary-on-galatians"
MANIFEST = ROOT / 'tests/fixtures/reconstruction-runtime/puritan-luther-commentary-on-galatians.source-manifest.json'
PROFILE = ROOT / 'tests/fixtures/reconstruction-runtime/puritan-luther-commentary-on-galatians.reconstruction-profile.json'
POLICY = SOURCE_DIR / "luther-commentary-on-galatians.validation-policy.json"
WORK_ID = "luther-commentary-on-galatians"
SOURCE_SHA256 = "ed00941bbe9e65b12c6619ea8a756ac053c44ec0a0c88761a83b8dff8d9a59bd"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture(scope="module")
def verified_candidate(tmp_path_factory: pytest.TempPathFactory):
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    source.verify()
    destination = tmp_path_factory.mktemp("luther-galatians") / "handoff"
    from build.tools.reconstruct_candidate import run

    handoff = run(manifest=MANIFEST.relative_to(ROOT).as_posix(), destination=str(destination), repository_root=str(ROOT))
    candidate = CandidatePackage.load(destination / "package")
    sidecar = json.loads((destination / "validation.json").read_bytes())
    assert handoff["status"] == "pass"
    assert handoff["acceptance_status"] == "nonaccepted"
    assert handoff["publication_status"] == "not-authorized"
    assert sidecar["status"] == "pass"
    assert sidecar["candidate_sha256"] == candidate.sha256
    return source, candidate, sidecar, destination


def _reseal(package_dir: Path, member_name: str) -> CandidatePackage:
    manifest_path = package_dir / "manifest.json"
    record = json.loads(manifest_path.read_bytes())
    member_data = (package_dir / member_name).read_bytes()
    for member in record["members"]:
        if member["name"] == member_name:
            member["bytes"] = len(member_data)
            member["sha256"] = _sha(member_data)
            break
    else:
        raise AssertionError(f"candidate does not contain {member_name}")
    manifest_path.write_bytes(_stable(record))
    return CandidatePackage.load(package_dir)


def test_source_manifest_binds_exact_work_source_and_independent_code() -> None:
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    source.verify()
    config = json.loads(source.authority_path("source-config").read_bytes())
    raw = SOURCE.read_bytes()
    rows = _records(raw)
    profile = json.loads(PROFILE.read_bytes())
    policy = json.loads(POLICY.read_bytes())

    assert config["resource_id"] == WORK_ID
    assert config["source_file"] == "raw/gutenberg/pg1549.txt"
    assert len(raw) == 504_403
    assert _sha(raw) == SOURCE_SHA256
    assert len(rows) == 9_150
    assert _counts(rows) == profile["required_counts"]
    assert profile["required_counts"]["chapter_heading_lines"] == list(CHAPTER_LINES)
    assert profile["required_counts"]["singular_verse_carrier_count"] == 216
    assert profile["required_counts"]["plural_verse_carrier_count"] == 14
    assert profile["required_counts"]["verse_carrier_count"] == 230
    assert "assignment specifies 217" in profile["assignment_target_217"]
    assert policy["separate_decisions"] == ["human-acceptance", "rights-clearance", "release-selection", "publication"]

    producer = producer_closure(ROOT, ROOT / "build/tei/luther_galatians_reconstruction.py")
    oracle = oracle_closure(ROOT, ROOT / "build/tei/luther_galatians_oracle.py", tuple(policy["forbidden_import_prefixes"]))
    assert _sha(_stable(list(producer))) == profile["producer_import_closure_sha256"]
    assert _sha(_stable(list(oracle))) == source.record["validator"]["import_closure_sha256"]
    assert "build/tei/luther_galatians_reconstruction.py" not in {item["path"] for item in oracle}


def test_candidate_is_schema_valid_nonaccepted_and_accounts_for_complete_envelope(verified_candidate) -> None:
    source, candidate, report, _destination = verified_candidate
    assert report["status"] == "pass"
    assert report["findings"] == []
    assert candidate.manifest["status"] == "nonaccepted"
    assert set(candidate.member_names) == {
        "manifest.json", "README.source.md", "content.tei.xml", "provenance.json",
        "source-accountability.json", "unresolved.jsonl",
    }
    package_schema = json.loads(source.authority_path("candidate-package-schema").read_bytes())
    Draft202012Validator(package_schema).validate(json.loads(candidate.member_bytes("manifest.json")))
    tei = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    assert len(tei.xpath("./t:text/t:body/t:div", namespaces={"t": TEI_NS})) == 9

    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    assert accountability["physical_line_count"] == 9_150
    assert accountability["represented_line_count"] == 9_150
    assert accountability["omitted_line_count"] == accountability["duplicate_line_count"] == 0
    assert len(accountability["lines"]) == 9_150
    assert [x["line"] for x in accountability["lines"]] == list(range(1, 9_151))
    assert all(x["disposition"] == "represented" for x in accountability["lines"])
    verse_nodes = tei.xpath(".//t:ab[@type='verse-carrier']", namespaces={"t": TEI_NS})
    assert len(verse_nodes) == 230
    assert sum("VERSES " not in (node.text or "").lstrip() for node in verse_nodes) == 216
    assert all(node.get("n") is None for node in verse_nodes)
    assert [node.get("n") for node in tei.xpath("./t:text/t:body/t:div[@type='chapter']", namespaces={"t": TEI_NS})] == [str(i) for i in range(1, 7)]
    unresolved = [json.loads(line) for line in candidate.member_bytes("unresolved.jsonl").decode("utf-8").splitlines()]
    count_note = next(item for item in unresolved if item["id"] == "verse-carrier-count-semantics")
    assert count_note["status"] == "unresolved"
    assert "216 singular VERSE and 14 plural VERSES" in count_note["scope"]
    assert next(item for item in unresolved if item["id"] == "rights-clearance")["status"] == "unresolved"


def test_candidate_reproduces_identically_in_a_fresh_process(verified_candidate, tmp_path: Path) -> None:
    _source, candidate, report, destination = verified_candidate
    second = tmp_path / "fresh-process"
    code = (
        "import json,sys; from build.tools.reconstruct_candidate import run; "
        "print(json.dumps(run(manifest=sys.argv[1],destination=sys.argv[2],repository_root=sys.argv[3]),sort_keys=True))"
    )
    completed = subprocess.run(
        [sys.executable, "-B", "-c", code, MANIFEST.relative_to(ROOT).as_posix(), str(second), str(ROOT)],
        cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8",
    )
    replay = json.loads(completed.stdout)
    replay_candidate = CandidatePackage.load(second / "package")
    assert replay_candidate.sha256 == candidate.sha256
    first_sidecar_bytes = (destination / "validation.json").read_bytes()
    assert replay["digests"]["candidate"] == candidate.sha256
    assert replay["digests"]["validation_report"] == report["report_sha256"]
    assert replay["digests"]["validation_sidecar"] == _sha(first_sidecar_bytes)


@pytest.mark.parametrize("mutation", ["text", "omission", "reordering", "invented-verse-identity"])
def test_independent_oracle_rejects_source_mapping_mutations(verified_candidate, tmp_path: Path, mutation: str) -> None:
    source, original, _report, _destination = verified_candidate
    mutated_dir = tmp_path / mutation
    shutil.copytree(original.path, mutated_dir)
    tei_path = mutated_dir / "content.tei.xml"
    root = etree.fromstring(tei_path.read_bytes())
    line_a = root.xpath(".//*[@xml:id='luther-galatians-line-00173']", namespaces={"xml": "http://www.w3.org/XML/1998/namespace"})[0]
    if mutation == "text":
        line_a.text = (line_a.text or "") + " invented"
    elif mutation == "omission":
        line_a.getparent().remove(line_a)
    elif mutation == "reordering":
        line_b = root.xpath(".//*[@xml:id='luther-galatians-line-00174']", namespaces={"xml": "http://www.w3.org/XML/1998/namespace"})[0]
        parent = line_a.getparent()
        parent.remove(line_b)
        parent.insert(parent.index(line_a), line_b)
    else:
        verse = root.xpath(".//*[@xml:id='luther-galatians-line-00169']", namespaces={"xml": "http://www.w3.org/XML/1998/namespace"})[0]
        verse.set("n", "1")
    tei_path.write_bytes(etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False))
    candidate = _reseal(mutated_dir, "content.tei.xml")
    with pytest.raises(ValueError):
        _oracle(source, candidate)
