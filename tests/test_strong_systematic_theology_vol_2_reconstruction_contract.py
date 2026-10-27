from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from jsonschema import Draft202012Validator
from lxml import etree
import pytest

from build.tei.strong_systematic_theology_vol_2_oracle import (
    _digest,
    _import_closure,
    _oracle,
    _stable_json,
)
from build.tei.strong_systematic_theology_vol_2_reconstruction import (
    CHAPTERS,
    CONTENTS_RANGE,
    FRONT_MATTER_RANGE,
    PARTS,
    PART_HEADING_LINE_RANGES,
    TITLE_PAGE_RANGE,
    VOLUME_RANGE,
    _expected_counts,
    _line_id,
    _records,
    _convert,
)
from ocd_kernel.reconstruction import (
    CandidatePackage,
    SourceManifest,
    reconstruct,
    validate,
)
from build.lib.tei_xsd import compiled_tei_schema


ROOT = Path(__file__).resolve().parents[1]
SOURCE_RELATIVE = Path("raw/gutenberg/pg44555.txt")
SOURCE_PATH = ROOT / SOURCE_RELATIVE
SOURCE_DIR = ROOT / "sources/strong-systematic-theology-vol-2"
RETAINED_MANIFEST = SOURCE_DIR / "strong-systematic-theology-vol-2.source-manifest.l374-v2.json"
MANIFEST = ROOT / "tests/fixtures/reconstruction-runtime/strong-vol2.source-manifest.json"
POLICY = SOURCE_DIR / "strong-systematic-theology-vol-2.validation-policy.json"
RETAINED_PROFILE = SOURCE_DIR / "strong-systematic-theology-vol-2.reconstruction-profile.l374-v2.json"
PROFILE = MANIFEST.with_name("strong-vol2.reconstruction-profile.json")
PRODUCER = ROOT / "build/tei/strong_systematic_theology_vol_2_reconstruction.py"
ORACLE = ROOT / "build/tei/strong_systematic_theology_vol_2_oracle.py"
TEI_NS = "http://www.tei-c.org/ns/1.0"
NS = {"tei": TEI_NS}
XML_NS = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML_NS}}}id"
SOURCE_BYTES = 2_079_512
SOURCE_SHA256 = "5ce7076c9be952ce37da19ebc2fbb1eb2013b274036dd28696df6fbb69ba48b9"
EXPECTED_MEMBERS = {
    "manifest.json",
    "content.tei.xml",
    "source-accountability.json",
    "provenance.json",
    "unresolved.jsonl",
    "README.source.md",
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def test_runtime_fixture_preserves_retained_authorities_and_only_updates_shared_runtime_closures() -> None:
    raw = RETAINED_MANIFEST.read_bytes()
    assert _sha(raw) == "bc1ef4f02f95798c753d0ee582a8f3103e1769f0a7409bf62708fcd5a2873970"
    expected = json.loads(raw)
    policy = json.loads(POLICY.read_bytes())
    expected["validator"]["import_closure_sha256"] = _digest(_stable_json(
        _import_closure(ROOT, ORACLE, tuple(policy["forbidden_import_prefixes"]))))
    original_profile = RETAINED_PROFILE.read_bytes()
    assert _sha(original_profile) == "762fae17fe32e076c4d0e787ba513f20be01b7d075e75373f8981e66b48ca454"
    expected_profile = json.loads(original_profile)
    expected_profile["producer_import_closure_sha256"] = _digest(_stable_json(
        _import_closure(ROOT, PRODUCER, tuple(policy["producer_forbidden_import_prefixes"]))))
    profile_bytes = PROFILE.read_bytes()
    assert json.loads(profile_bytes) == expected_profile
    authority = next(item for item in expected["authorities"] if item["name"] == "reconstruction-profile")
    authority.update(path=PROFILE.relative_to(ROOT).as_posix(),
                     bytes=len(profile_bytes), sha256=_sha(profile_bytes))
    assert json.loads(MANIFEST.read_bytes()) == expected


def _reseal(path: Path, name: str) -> CandidatePackage:
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    content = (path / name).read_bytes()
    member = next(item for item in manifest["members"] if item["name"] == name)
    member.update(bytes=len(content), sha256=_sha(content))
    manifest_path.write_bytes(_canonical(manifest))
    return CandidatePackage.load(path)


def _write_tei(path: Path, root: etree._Element) -> None:
    path.write_bytes(
        etree.tostring(
            root,
            encoding="UTF-8",
            xml_declaration=True,
            pretty_print=False,
        )
    )


@pytest.fixture(scope="module")
def verified_candidate(tmp_path_factory: pytest.TempPathFactory):
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    candidate = reconstruct(
        source,
        tmp_path_factory.mktemp("lib076-candidate") / "candidate",
        _convert,
    )
    report = validate(source, candidate, _oracle)
    record = {
        "contract": "ocd-validation-report-v1",
        "status": report.status,
        "candidate_sha256": report.candidate_sha256,
        "source_manifest_sha256": report.source_manifest_sha256,
        "attestation": dict(report.attestation),
        "findings": list(report.findings),
    }
    assert report.sha256 == _sha(_canonical(record))
    return source, candidate, report


def test_non_ocr_source_boundary_and_exact_profile() -> None:
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    source.verify()
    config = json.loads(source.authority_path("source-config").read_bytes())
    retained = source.authority_path("retained-source").read_bytes()
    rows = _records(retained)
    profile = json.loads(PROFILE.read_bytes())

    assert config["source_type"] == "gutenberg_txt"
    assert config["source_format"] == "plain text (UTF-8)"
    assert config["source_file"] == SOURCE_RELATIVE.as_posix()
    assert len(retained) == SOURCE_BYTES
    assert _sha(retained) == SOURCE_SHA256
    assert len(rows) == 34_523
    assert profile["required_counts"] == _expected_counts(rows)
    assert profile["required_counts"]["body_prose_group_count"] == 2_362
    assert profile["required_counts"]["contents_entry_count"] == 175
    assert profile["required_counts"]["mapped_heading_count"] == 167
    assert profile["required_counts"]["mapped_heading_line_count"] == 174
    assert profile["required_counts"]["mapped_heading_line_ranges"][-1] == [34_036, 34_036]
    assert PART_HEADING_LINE_RANGES == ((295, 295), (8225, 8225), (24652, 24653))


def test_candidate_is_p5_valid_and_accounted(verified_candidate) -> None:
    source, candidate, report = verified_candidate
    assert set(candidate.member_names) == EXPECTED_MEMBERS
    assert candidate.manifest["status"] == "nonaccepted"
    assert report.status == "pass"
    assert report.findings == ()

    package_schema = json.loads(
        source.authority_path("candidate-package-schema").read_bytes()
    )
    Draft202012Validator(package_schema).validate(
        json.loads(candidate.member_bytes("manifest.json"))
    )
    tei = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    schema = compiled_tei_schema(source.authority_path("tei-p5-xsd"))
    schema.assertValid(etree.ElementTree(tei))

    rows = _records(SOURCE_PATH.read_bytes())
    expected_ids = [
        _line_id(number)
        for number in range(VOLUME_RANGE[0], VOLUME_RANGE[1] + 1)
        if str(rows[number - 1]["text"])
    ]
    actual_ids = [
        node.get(XML_ID)
        for node in tei.xpath("//*[@xml:id]", namespaces={"xml": XML_NS})
    ]
    assert actual_ids == expected_ids
    assert len(actual_ids) == 30_162

    part_vi_head = tei.xpath(
        "./tei:text/tei:body/tei:div[@type='part'][3]/tei:head",
        namespaces=NS,
    )[0]
    assert [part_vi_head.get(XML_ID)] + [
        child.get(XML_ID)
        for child in part_vi_head
        if child.tag == f"{{{TEI_NS}}}seg"
    ] == [_line_id(24652), _line_id(24653)]


def test_accountability_and_nonaccepted_boundaries(verified_candidate) -> None:
    source, candidate, _report = verified_candidate
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    unresolved = [
        json.loads(line)
        for line in candidate.member_bytes("unresolved.jsonl").decode("utf-8").splitlines()
    ]

    assert accountability["source_classification"] == {
        "source_type": "gutenberg_txt",
        "source_format": "plain text (UTF-8)",
        "ocr_classification": "non-ocr-retained-gutenberg-witness",
    }
    assert accountability["source_member"] == {
        "path": SOURCE_RELATIVE.as_posix(),
        "bytes": SOURCE_BYTES,
        "sha256": SOURCE_SHA256,
    }
    assert accountability["physical_line_count"] == 34_523
    assert accountability["represented_line_count"] == 30_162
    assert accountability["evidence_only_line_count"] == 4_361
    assert accountability["omitted_line_count"] == 0
    assert accountability["duplicate_line_count"] == 0
    assert len(accountability["lines"]) == 34_523
    for number, item in enumerate(accountability["lines"], 1):
        assert item["line"] == number
        if VOLUME_RANGE[0] <= number <= VOLUME_RANGE[1] and item["text"]:
            assert item["disposition"] == "represented"
            assert item["tei_selector"] == f"#{_line_id(number)}"
        else:
            assert item["disposition"] == "evidence-only"
            assert item["tei_selector"] is None

    assert provenance["status"] == "nonaccepted"
    assert provenance["publication"] == "not_ready"
    assert provenance["source_sha256"] == SOURCE_SHA256
    assert {item["id"] for item in unresolved} == {
        "strong-systematic-theology-vol-2-edition-identity",
        "strong-systematic-theology-vol-2-textual-form",
        "strong-systematic-theology-vol-2-rights",
        "strong-systematic-theology-vol-2-source-envelope",
        "strong-systematic-theology-vol-2-human-acceptance",
    }
    assert source.record["source_id"] == "strong-systematic-theology-vol-2-pg44555-retained"


def test_oracle_closure_is_independent_and_source_local() -> None:
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    policy = json.loads(POLICY.read_bytes())
    oracle_closure = _import_closure(
        ROOT,
        ORACLE,
        tuple(policy["forbidden_import_prefixes"]),
    )
    producer_closure = _import_closure(
        ROOT,
        PRODUCER,
        tuple(policy["producer_forbidden_import_prefixes"]),
    )
    oracle_paths = {item["path"] for item in oracle_closure}
    producer_paths = {item["path"] for item in producer_closure}

    assert ORACLE.relative_to(ROOT).as_posix() in oracle_paths
    assert PRODUCER.relative_to(ROOT).as_posix() not in oracle_paths
    assert PRODUCER.relative_to(ROOT).as_posix() in producer_paths
    assert ORACLE.relative_to(ROOT).as_posix() not in producer_paths
    assert _digest(_stable_json(oracle_closure)) == source.record["validator"]["import_closure_sha256"]
    assert json.loads(PROFILE.read_bytes())["producer_import_closure_sha256"] == _digest(
        _stable_json(producer_closure)
    )


@pytest.mark.parametrize(
    "mutation",
    ["text", "omission", "reorder", "accountability", "provenance", "readme", "unresolved"],
)
def test_independent_oracle_rejects_resealed_drift(
    verified_candidate,
    tmp_path: Path,
    mutation: str,
) -> None:
    source, candidate, _report = verified_candidate
    target = tmp_path / mutation
    shutil.copytree(candidate.path, target)

    if mutation in {"text", "omission", "reorder"}:
        name = "content.tei.xml"
        tei = etree.fromstring((target / name).read_bytes())
        if mutation == "text":
            paragraph = tei.xpath(
                "./tei:text/tei:body//tei:p/tei:seg",
                namespaces=NS,
            )[0]
            paragraph.text = (paragraph.text or "") + " invented text"
        elif mutation == "omission":
            paragraph = tei.xpath(
                "./tei:text/tei:body//tei:p",
                namespaces=NS,
            )[0]
            paragraph.remove(paragraph[0])
        else:
            body = tei.xpath("./tei:text/tei:body", namespaces=NS)[0]
            parts = body.xpath("./tei:div[@type='part']", namespaces=NS)
            body.remove(parts[1])
            body.insert(0, parts[1])
        _write_tei(target / name, tei)
    elif mutation == "accountability":
        name = "source-accountability.json"
        record = json.loads((target / name).read_bytes())
        record["lines"][0], record["lines"][1] = record["lines"][1], record["lines"][0]
        (target / name).write_bytes(_canonical(record))
    elif mutation == "provenance":
        name = "provenance.json"
        record = json.loads((target / name).read_bytes())
        record["publication"] = "ready"
        (target / name).write_bytes(_canonical(record))
    elif mutation == "readme":
        name = "README.source.md"
        (target / name).write_bytes(
            (target / name).read_bytes() + b"\nInvented attribution.\n"
        )
    else:
        name = "unresolved.jsonl"
        content = (target / name).read_bytes().replace(
            b'"status":"unresolved"',
            b'"status":"changed"',
            1,
        )
        (target / name).write_bytes(content)

    mutated = _reseal(target, name)
    with pytest.raises(ValueError):
        validate(source, mutated, _oracle)


def test_fresh_processes_are_byte_identical_across_cwds(
    verified_candidate,
    tmp_path: Path,
) -> None:
    source, candidate, _report = verified_candidate
    other_cwd = tmp_path / "other-cwd"
    other_cwd.mkdir()
    first = tmp_path / "fresh-first"
    second = tmp_path / "fresh-second"
    manifest_relative = MANIFEST.relative_to(ROOT).as_posix()

    def run(seed: str, destination: Path, cwd: Path) -> str:
        environment = os.environ.copy()
        environment["PYTHONHASHSEED"] = seed
        environment["PYTHONPATH"] = str(ROOT) + os.pathsep + environment.get("PYTHONPATH", "")
        code = (
            "from pathlib import Path;"
            "from ocd_kernel.reconstruction import SourceManifest,reconstruct;"
            "from build.tei.strong_systematic_theology_vol_2_reconstruction import _convert;"
            f"root=Path({str(ROOT)!r});"
            f"source=SourceManifest.load(root / {manifest_relative!r}, repository_root=root);"
            f"candidate=reconstruct(source,Path({str(destination)!r}),_convert);"
            "print(candidate.sha256)"
        )
        completed = subprocess.run(
            [sys.executable, "-c", code],
            cwd=cwd,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        return completed.stdout.strip()

    first_sha = run("1", first, ROOT)
    second_sha = run("random", second, other_cwd)
    assert first_sha == second_sha == candidate.sha256
    for name in EXPECTED_MEMBERS:
        assert (first / name).read_bytes() == (second / name).read_bytes()
