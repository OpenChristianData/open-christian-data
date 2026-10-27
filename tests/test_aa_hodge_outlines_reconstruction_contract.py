from __future__ import annotations

import copy
import hashlib
import json
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
WITNESS = Path(
    "D:/Library/Open Christian Data/raw/gutenberg/outlinesoftheolo1879hodg_djvu.txt"
)
SOURCE_SHA256 = "a81808d5a9d2037d3c1d0706de960fb13c175d3581dd131c7d505493df51fee5"
SOURCE_DIR = ROOT / "sources/catechisms/aa-hodge-outlines"
ORIGINAL_MANIFEST = SOURCE_DIR / "aa-hodge-outlines.source-manifest.json"
MANIFEST = ROOT / "tests/fixtures/reconstruction-runtime/aa-hodge-outlines.source-manifest.json"
NS = {"tei": "http://www.tei-c.org/ns/1.0"}
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
GOVERNED_LF_PATHS = (
    "sources/catechisms/aa-hodge-outlines/aa-hodge-outlines.source-manifest.json",
    "tests/fixtures/gutenberg_systematics/aa_hodge_q7_span.txt",
    "sources/catechisms/aa-hodge-outlines/README.source.md",
    "sources/catechisms/aa-hodge-outlines/aa-hodge-outlines.reconstruction-profile.json",
    "sources/catechisms/aa-hodge-outlines/aa-hodge-outlines.source-accountability.schema.json",
    "sources/catechisms/aa-hodge-outlines/aa-hodge-outlines.validation-policy.json",
    "build/tei/aa_hodge_outlines_reconstruction.py",
    "build/tei/aa_hodge_outlines_oracle.py",
)
GOVERNED_CRLF_PATHS = (
    "sources/catechisms/aa-hodge-outlines/config.json",
    "ocd_kernel/tei/vendor/xsd/tei_all.xsd",
    "ocd_kernel/tei/vendor/xsd/tei_all_teix.xsd",
    "ocd_kernel/tei/vendor/xsd/tei_all_xml.xsd",
)


def _assert_effective_checkout_eol(relative: str, expected: str) -> None:
    relative_bytes = relative.encode("utf-8")
    output = subprocess.run(
        ["git", "check-attr", "-z", "text", "eol", "--", relative],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    assert output.split(b"\0") == [
        relative_bytes,
        b"text",
        b"set",
        relative_bytes,
        b"eol",
        expected.encode("ascii"),
        b"",
    ]


def test_manifest_bound_text_materializes_portably() -> None:
    assert hashlib.sha256(ORIGINAL_MANIFEST.read_bytes()).hexdigest() == (
        "d4303df97c3c72ffc74ab389e68d52b53ddffaf865f92f68fde5457f43060d5b"
    )
    manifest = json.loads(MANIFEST.read_bytes())
    authority_bindings = {
        item["path"]: (item["bytes"], item["sha256"])
        for item in manifest["authorities"]
    }
    implementation_bindings = {
        manifest["converter"]["implementation_path"]: manifest["converter"][
            "implementation_sha256"
        ],
        manifest["validator"]["implementation_path"]: manifest["validator"][
            "implementation_sha256"
        ],
    }

    for relative in GOVERNED_LF_PATHS:
        _assert_effective_checkout_eol(relative, "lf")
        payload = (ROOT / relative).read_bytes()
        assert b"\r\n" not in payload
        if relative in authority_bindings:
            expected_bytes, expected_sha256 = authority_bindings[relative]
            assert len(payload) == expected_bytes
            assert hashlib.sha256(payload).hexdigest() == expected_sha256
        if relative in implementation_bindings:
            assert hashlib.sha256(payload).hexdigest() == implementation_bindings[relative]

    for relative in GOVERNED_CRLF_PATHS:
        _assert_effective_checkout_eol(relative, "crlf")
        payload = (ROOT / relative).read_bytes()
        assert b"\r\n" in payload
        assert b"\n" not in payload.replace(b"\r\n", b"")
        if relative in authority_bindings:
            expected_bytes, expected_sha256 = authority_bindings[relative]
            assert len(payload) == expected_bytes
            assert hashlib.sha256(payload).hexdigest() == expected_sha256


@pytest.fixture()
def external_witness_mirror(tmp_path: Path) -> Path:
    mirror_root = tmp_path / "external-witness"
    mirror_root.mkdir()
    mirror = mirror_root / WITNESS.name
    shutil.copyfile(WITNESS, mirror)
    return mirror


def test_witness_inspection_pins_exact_bytes_lines_and_literal_ocr(
    external_witness_mirror: Path,
) -> None:
    from build.tei.aa_hodge_outlines_reconstruction import inspect_witness

    witness = inspect_witness(external_witness_mirror)

    assert witness.byte_count == 1_976_207
    assert witness.sha256 == SOURCE_SHA256
    assert witness.line_count == 37_553
    assert witness.terminal_lf is True
    assert hashlib.sha256(witness.content).hexdigest() == SOURCE_SHA256
    assert b"Shoio  that  this  Laio" in witness.content


def test_source_local_contract_is_whole_work_nonaccepted_and_external() -> None:
    profile = json.loads(
        (SOURCE_DIR / "aa-hodge-outlines.reconstruction-profile.json").read_bytes()
    )
    policy = json.loads(
        (SOURCE_DIR / "aa-hodge-outlines.validation-policy.json").read_bytes()
    )
    readme = (SOURCE_DIR / "README.source.md").read_text(encoding="utf-8")

    assert profile["source"] == {
        "durable_path": "D:/Library/Open Christian Data/raw/gutenberg/outlinesoftheolo1879hodg_djvu.txt",
        "logical_path": "raw/gutenberg/outlinesoftheolo1879hodg_djvu.txt",
        "bytes": 1_976_207,
        "sha256": SOURCE_SHA256,
        "physical_lines": 37_553,
        "terminal_lf": True,
    }
    assert profile["coverage"] == {
        "physical_lines": 37_553,
        "represented_lines": 37_553,
        "omitted_lines": 0,
        "duplicated_lines": 0,
    }
    assert profile["structure"]["identity"] == "catechism_qa"
    assert profile["structure"]["question_candidates"] == 1_107
    assert profile["structure"]["chapter_candidates"] == 85
    assert profile["diagnostic_fixture"] == {
        "path": "tests/fixtures/gutenberg_systematics/aa_hodge_q7_span.txt",
        "checkout_bytes": 1_630,
        "checkout_sha256": "6711666f19ca7c869c0e6601f40f5bb03ab02280976c2292c99fa9ee70e36034",
        "source_span_lines": "16538-16567",
        "source_span_lf_bytes": 1_630,
        "source_span_lf_sha256": "6711666f19ca7c869c0e6601f40f5bb03ab02280976c2292c99fa9ee70e36034",
        "whole_work_acceptance": False,
    }
    assert policy["candidate_status"] == "nonaccepted"
    assert policy["publication_authorized"] is False
    assert policy["ocr_cleanup_performed"] is False
    assert "human textual, edition, and rights review" in readme
    assert "not authorized" in readme
    assert "retained payload" not in {path.name for path in SOURCE_DIR.iterdir()}


def test_complete_candidate_is_schema_valid_lossless_and_nonaccepted(
    tmp_path: Path,
    external_witness_mirror: Path,
) -> None:
    from build.tei.aa_hodge_outlines_reconstruction import (
        build_candidate,
        load_source_manifest,
    )

    source_manifest = load_source_manifest(
        MANIFEST,
        repository_root=ROOT,
        witness_path=external_witness_mirror,
    )
    candidate = build_candidate(source_manifest, tmp_path / "candidate")

    assert candidate.manifest["status"] == "nonaccepted"
    package_schema = json.loads(
        (
            ROOT / "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json"
        ).read_bytes()
    )
    Draft202012Validator(package_schema).validate(
        json.loads(candidate.member_bytes("manifest.json"))
    )

    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    accountability_schema = json.loads(
        (
            SOURCE_DIR / "aa-hodge-outlines.source-accountability.schema.json"
        ).read_bytes()
    )
    Draft202012Validator(accountability_schema).validate(accountability)
    assert accountability["counts"] == {
        "source_bytes": 1_976_207,
        "physical_lines": 37_553,
        "represented_lines": 37_553,
        "question_candidates": 1_107,
        "chapter_candidates": 85,
        "omitted_lines": 0,
        "duplicated_lines": 0,
    }
    assert len(accountability["crosswalk"]) == 37_553
    assert accountability["crosswalk"][0]["byte_start"] == 0
    assert accountability["crosswalk"][-1]["byte_end"] == 1_976_207

    tei = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    xsd = compiled_tei_schema(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd")
    xsd.assertValid(etree.ElementTree(tei))
    lines = tei.xpath("./tei:text/tei:body/tei:div/tei:ab", namespaces=NS)
    assert len(lines) == 37_553
    assert lines[16_537].text.startswith("7.  Shoio  that  this  Laio")

    provenance = json.loads(candidate.member_bytes("provenance.json"))
    assert provenance["candidate_status"] == "nonaccepted"
    assert provenance["publication_authorized"] is False
    assert provenance["handoff_result"]["ocr_correction_status"] == "not-performed"
    assert provenance["handoff_result"]["corrected_text_sha256"] == SOURCE_SHA256
    assert (
        provenance["handoff_result"]["request_digest"]
        == provenance["handoff_request"]["request_digest"]
    )
    unresolved = candidate.member_bytes("unresolved.jsonl").decode("utf-8")
    assert "all 37553 retained OCR source lines" in unresolved
    assert "human-review-required" in unresolved


def test_independent_oracle_reconstructs_complete_source_truth(
    tmp_path: Path,
    external_witness_mirror: Path,
) -> None:
    from build.tei.aa_hodge_outlines_oracle import _oracle
    from build.tei.aa_hodge_outlines_reconstruction import (
        build_candidate,
        load_source_manifest,
    )

    source_manifest = load_source_manifest(
        MANIFEST,
        repository_root=ROOT,
        witness_path=external_witness_mirror,
    )
    candidate = build_candidate(source_manifest, tmp_path / "oracle-candidate")
    report = validate(source_manifest, candidate, _oracle)

    assert report.status == "pass"
    assert report.findings == ()
    assert report.attestation["source_sha256"] == SOURCE_SHA256
    assert report.attestation["candidate_sha256"] == candidate.sha256


@pytest.fixture(scope="module")
def oracle_bundle(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[object, CandidatePackage]:
    from build.tei.aa_hodge_outlines_reconstruction import (
        build_candidate,
        load_source_manifest,
    )

    root = tmp_path_factory.mktemp("hodge-oracle-bundle")
    mirror = root / WITNESS.name
    shutil.copyfile(WITNESS, mirror)
    source_manifest = load_source_manifest(
        MANIFEST,
        repository_root=ROOT,
        witness_path=mirror,
    )
    candidate = build_candidate(source_manifest, root / "candidate")
    return source_manifest, candidate


def _candidate_copy(tmp_path: Path, candidate: CandidatePackage, label: str) -> Path:
    destination = tmp_path / label
    shutil.copytree(candidate.path, destination)
    return destination


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _reseal(path: Path, name: str, content: bytes) -> CandidatePackage:
    (path / name).write_bytes(content)
    manifest = json.loads((path / "manifest.json").read_bytes())
    member = next(item for item in manifest["members"] if item["name"] == name)
    member["bytes"] = len(content)
    member["sha256"] = hashlib.sha256(content).hexdigest()
    (path / "manifest.json").write_bytes(_canonical(manifest))
    return CandidatePackage.load(path)


@pytest.mark.parametrize(
    "mutation",
    [
        "omission",
        "duplication",
        "reorder",
        "invention",
        "text",
        "crosswalk",
        "metadata",
        "header-comment",
        "provenance",
        "manifest-source",
        "manifest-converter",
        "manifest-package-schema",
    ],
)
def test_oracle_rejects_resealed_whole_work_fidelity_attacks(
    mutation: str,
    tmp_path: Path,
    oracle_bundle: tuple[object, CandidatePackage],
) -> None:
    from build.tei.aa_hodge_outlines_oracle import _oracle

    source_manifest, candidate = oracle_bundle
    path = _candidate_copy(tmp_path, candidate, mutation)
    if mutation in {
        "omission",
        "duplication",
        "reorder",
        "invention",
        "text",
        "metadata",
        "header-comment",
    }:
        tei = etree.fromstring((path / "content.tei.xml").read_bytes())
        lines = tei.xpath("./tei:text/tei:body/tei:div/tei:ab", namespaces=NS)
        if mutation == "omission":
            lines[100].getparent().remove(lines[100])
        elif mutation == "duplication":
            duplicate = copy.deepcopy(lines[100])
            duplicate.set(XML_ID, "hodge-line-invented-duplicate")
            duplicate.set("n", "999999")
            lines[100].addnext(duplicate)
        elif mutation == "reorder":
            parent = lines[100].getparent()
            first = lines[100]
            parent.remove(first)
            parent.insert(102, first)
        elif mutation == "invention":
            invented = etree.SubElement(
                lines[-1].getparent(), "{http://www.tei-c.org/ns/1.0}ab"
            )
            invented.set(XML_ID, "hodge-line-invented")
            invented.set("n", "999999")
            invented.set("ana", "#source-line")
            invented.text = "Invented normalized reading."
        elif mutation == "text":
            lines[16_537].text = (lines[16_537].text or "").replace("Shoio", "Show")
        elif mutation == "metadata":
            title = tei.xpath(
                "./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title", namespaces=NS
            )[0]
            title.text = "Accepted critical edition of Outlines of Theology"
        elif mutation == "header-comment":
            title_stmt = tei.xpath(
                "./tei:teiHeader/tei:fileDesc/tei:titleStmt", namespaces=NS
            )[0]
            title_stmt.insert(0, etree.Comment("P5-valid invented header comment"))
        content = etree.tostring(
            tei, encoding="UTF-8", xml_declaration=True, pretty_print=False
        )
        mutated = _reseal(path, "content.tei.xml", content)
    elif mutation == "crosswalk":
        accountability = json.loads((path / "source-accountability.json").read_bytes())
        accountability["crosswalk"][100]["target"] = "#hodge-line-000102"
        accountability["crosswalk_sha256"] = hashlib.sha256(
            _canonical(accountability["crosswalk"])
        ).hexdigest()
        mutated = _reseal(
            path, "source-accountability.json", _canonical(accountability)
        )
    elif mutation == "provenance":
        provenance = json.loads((path / "provenance.json").read_bytes())
        provenance["publication_authorized"] = True
        provenance["rights"]["worldwide"] = "cleared"
        mutated = _reseal(path, "provenance.json", _canonical(provenance))
    else:
        package = json.loads((path / "manifest.json").read_bytes())
        if mutation == "manifest-source":
            package["source_manifest"]["sha256"] = "0" * 64
        elif mutation == "manifest-converter":
            package["converter"]["id"] = "invented-converter"
        else:
            package["package_schema"]["sha256"] = "0" * 64
        (path / "manifest.json").write_bytes(_canonical(package))
        mutated = CandidatePackage.load(path)
    message = "TEI serialized bytes drift" if mutation == "header-comment" else None
    with pytest.raises(ValueError, match=message):
        validate(source_manifest, mutated, _oracle)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "mutation",
    [
        "header-processing-instruction",
        "attribute-order",
        "declaration-quotes",
        "trailing-comment",
    ],
)
def test_oracle_rejects_resealed_serialization_only_tei_attacks(
    mutation: str,
    tmp_path: Path,
    oracle_bundle: tuple[object, CandidatePackage],
) -> None:
    from build.tei.aa_hodge_outlines_oracle import _oracle

    source_manifest, candidate = oracle_bundle
    path = _candidate_copy(tmp_path, candidate, mutation)
    content = (path / "content.tei.xml").read_bytes()
    if mutation in {"header-processing-instruction", "attribute-order"}:
        tei = etree.fromstring(content)
        if mutation == "header-processing-instruction":
            title_stmt = tei.xpath(
                "./tei:teiHeader/tei:fileDesc/tei:titleStmt", namespaces=NS
            )[0]
            title_stmt.insert(
                0,
                etree.ProcessingInstruction("invented", "header-evidence"),
            )
        else:
            division = tei.xpath("./tei:text/tei:body/tei:div", namespaces=NS)[0]
            values = dict(division.attrib)
            division.attrib.clear()
            for name in ("subtype", "type", XML_ID):
                division.set(name, values[name])
        content = etree.tostring(
            tei,
            encoding="UTF-8",
            xml_declaration=True,
            pretty_print=False,
        )
    elif mutation == "declaration-quotes":
        content = content.replace(
            b"<?xml version='1.0' encoding='UTF-8'?>",
            b'<?xml version="1.0" encoding="UTF-8"?>',
            1,
        )
    else:
        content += b"<!--invented trailing document comment-->"
    mutated = _reseal(path, "content.tei.xml", content)

    with pytest.raises(ValueError, match="TEI serialized bytes drift"):
        validate(source_manifest, mutated, _oracle)  # type: ignore[arg-type]


class _AuthorityDriftFacade:
    def __init__(
        self,
        source_manifest: object,
        authority_name: str,
        path: Path,
        record: object | None = None,
        source_manifest_sha256: str | None = None,
    ) -> None:
        self._source_manifest = source_manifest
        self._authority_name = authority_name
        self._path = path
        self.path = source_manifest.path
        self.repository_root = source_manifest.repository_root
        self.sha256 = source_manifest_sha256 or source_manifest.sha256
        self.record = source_manifest.record if record is None else record

    def authority_path(self, name: str) -> Path:
        if name == self._authority_name:
            return self._path
        return self._source_manifest.authority_path(name)

    def verify(self) -> None:
        self._source_manifest.verify()


def test_oracle_rejects_bound_diagnostic_evidence_drift(
    tmp_path: Path,
    oracle_bundle: tuple[object, CandidatePackage],
) -> None:
    from build.tei.aa_hodge_outlines_oracle import _oracle

    source_manifest, candidate = oracle_bundle
    fixture = tmp_path / "drifted-q7.txt"
    fixture.write_bytes(
        source_manifest.authority_path("q7-diagnostic-fixture").read_bytes()
        + b"invented evidence\n"
    )
    facade = _AuthorityDriftFacade(source_manifest, "q7-diagnostic-fixture", fixture)
    with pytest.raises(ValueError, match="authority bytes drift"):
        validate(facade, candidate, _oracle)  # type: ignore[arg-type]


def test_oracle_requires_the_complete_authority_inventory(
    tmp_path: Path,
    oracle_bundle: tuple[object, CandidatePackage],
) -> None:
    from build.tei.aa_hodge_outlines_oracle import _oracle

    source_manifest, candidate = oracle_bundle
    record = json.loads((MANIFEST).read_bytes())
    record["authorities"] = [
        item
        for item in record["authorities"]
        if item["name"] != "q7-diagnostic-fixture"
    ]
    record["authorities"] = tuple(record["authorities"])
    facade = _AuthorityDriftFacade(
        source_manifest,
        "q7-diagnostic-fixture",
        tmp_path / "unused-q7.txt",
        record=record,
    )
    with pytest.raises(ValueError, match="authority inventory"):
        validate(facade, candidate, _oracle)  # type: ignore[arg-type]


def test_oracle_rejects_resealed_q7_authority_rebind(
    tmp_path: Path,
    oracle_bundle: tuple[object, CandidatePackage],
) -> None:
    from build.tei.aa_hodge_outlines_oracle import _oracle

    source_manifest, candidate = oracle_bundle
    record = json.loads(MANIFEST.read_bytes())
    replacement = SOURCE_DIR / "config.json"
    replacement_bytes = replacement.read_bytes()
    replacement_authority = next(
        item
        for item in record["authorities"]
        if item["name"] == "q7-diagnostic-fixture"
    )
    replacement_authority.update(
        {
            "path": "sources/catechisms/aa-hodge-outlines/config.json",
            "role": "local-metadata-claim-evidence",
            "bytes": len(replacement_bytes),
            "sha256": hashlib.sha256(replacement_bytes).hexdigest(),
        }
    )
    record["authorities"] = tuple(record["authorities"])
    resealed_source_manifest_sha256 = hashlib.sha256(_canonical(record)).hexdigest()
    facade = _AuthorityDriftFacade(
        source_manifest,
        "q7-diagnostic-fixture",
        replacement,
        record=record,
        source_manifest_sha256=resealed_source_manifest_sha256,
    )
    path = _candidate_copy(tmp_path, candidate, "q7-rebound")
    package = json.loads((path / "manifest.json").read_bytes())
    package["source_manifest"]["sha256"] = resealed_source_manifest_sha256
    (path / "manifest.json").write_bytes(_canonical(package))
    mutated = CandidatePackage.load(path)

    with pytest.raises(ValueError, match="q7-diagnostic-fixture authority record"):
        validate(facade, mutated, _oracle)  # type: ignore[arg-type]


def test_oracle_rejects_resealed_authority_record_rebind(
    tmp_path: Path,
    oracle_bundle: tuple[object, CandidatePackage],
) -> None:
    from build.tei.aa_hodge_outlines_oracle import _oracle

    source_manifest, candidate = oracle_bundle
    record = json.loads(MANIFEST.read_bytes())
    replacement = SOURCE_DIR / "README.source.md"
    replacement_bytes = replacement.read_bytes()
    replacement_authority = next(
        item for item in record["authorities"] if item["name"] == "local-source-config"
    )
    replacement_authority.update(
        {
            "path": "sources/catechisms/aa-hodge-outlines/README.source.md",
            "role": "local-source-readme",
            "bytes": len(replacement_bytes),
            "sha256": hashlib.sha256(replacement_bytes).hexdigest(),
        }
    )
    record["authorities"] = tuple(record["authorities"])
    resealed_source_manifest_sha256 = hashlib.sha256(_canonical(record)).hexdigest()
    facade = _AuthorityDriftFacade(
        source_manifest,
        "local-source-config",
        replacement,
        record=record,
        source_manifest_sha256=resealed_source_manifest_sha256,
    )
    path = _candidate_copy(tmp_path, candidate, "authority-rebound")
    package = json.loads((path / "manifest.json").read_bytes())
    package["source_manifest"]["sha256"] = resealed_source_manifest_sha256
    (path / "manifest.json").write_bytes(_canonical(package))
    mutated = CandidatePackage.load(path)

    with pytest.raises(ValueError, match="local-source-config authority record"):
        validate(facade, mutated, _oracle)  # type: ignore[arg-type]


def test_oracle_rejects_resealed_imported_tei_schema_rebind(
    tmp_path: Path,
    oracle_bundle: tuple[object, CandidatePackage],
) -> None:
    from build.tei.aa_hodge_outlines_oracle import _oracle

    source_manifest, candidate = oracle_bundle
    record = json.loads(MANIFEST.read_bytes())
    schema = ROOT / "ocd_kernel/tei/vendor/xsd/tei_all_xml.xsd"
    mutated_schema = tmp_path / schema.name
    mutated_bytes = schema.read_bytes().replace(b"xs:ID", b"xs:string", 1)
    mutated_schema.write_bytes(mutated_bytes)
    schema_authority = next(
        item for item in record["authorities"] if item["name"] == "tei-p5-xsd-xml"
    )
    schema_authority.update(
        {
            "bytes": len(mutated_bytes),
            "sha256": hashlib.sha256(mutated_bytes).hexdigest(),
        }
    )
    record["authorities"] = tuple(record["authorities"])
    resealed_source_manifest_sha256 = hashlib.sha256(_canonical(record)).hexdigest()
    facade = _AuthorityDriftFacade(
        source_manifest,
        "tei-p5-xsd-xml",
        mutated_schema,
        record=record,
        source_manifest_sha256=resealed_source_manifest_sha256,
    )
    path = _candidate_copy(tmp_path, candidate, "imported-schema-rebound")
    package = json.loads((path / "manifest.json").read_bytes())
    package["source_manifest"]["sha256"] = resealed_source_manifest_sha256
    (path / "manifest.json").write_bytes(_canonical(package))
    mutated = CandidatePackage.load(path)

    with pytest.raises(ValueError, match="tei-p5-xsd-xml authority record"):
        validate(facade, mutated, _oracle)  # type: ignore[arg-type]


def test_fresh_process_complete_packages_are_byte_identical(
    tmp_path: Path,
    external_witness_mirror: Path,
) -> None:
    destinations = [tmp_path / "fresh-a", tmp_path / "fresh-b"]
    for destination in destinations:
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "build.tei.aa_hodge_outlines_reconstruction",
                "--repository-root",
                str(ROOT),
                "--manifest",
                str(MANIFEST),
                "--witness",
                str(external_witness_mirror),
                "--output",
                str(destination),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        assert "nonaccepted" in completed.stdout
    first_names = sorted(path.name for path in destinations[0].iterdir())
    second_names = sorted(path.name for path in destinations[1].iterdir())
    assert (
        first_names
        == second_names
        == [
            "README.source.md",
            "content.tei.xml",
            "manifest.json",
            "provenance.json",
            "source-accountability.json",
            "unresolved.jsonl",
        ]
    )
    for name in first_names:
        assert (destinations[0] / name).read_bytes() == (
            destinations[1] / name
        ).read_bytes()
