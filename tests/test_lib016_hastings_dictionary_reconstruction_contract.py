from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from jsonschema import Draft202012Validator
from lxml import etree
import pytest

from ocd_kernel.reconstruction.contract import CandidatePackage, validate
from build.lib.tei_xsd import compiled_tei_schema


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = Path("D:/Library/Open Christian Data/raw/ia/hastings-dictionary")
SOURCE_DIR = ROOT / "sources/hastings-dictionary-of-the-bible/LIB-016"
MANIFEST = SOURCE_DIR / "lib016-hastings.source-manifest.json"
AGGREGATE_SHA256 = "1cd0f245927973e5f84db7bad42c71aa1dfb259e5aad026a40dd5f0d6238f7a7"
MEMBER_SET_SHA256 = "997d3b2ee21ce47e747811c826e05456964cac318f4846bc346b3b790d6e57c8"
WORK_ID = "hastings-dictionary-of-the-bible"
NS = {"tei": "http://www.tei-c.org/ns/1.0"}


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


@pytest.fixture(scope="module")
def bundle(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[object, CandidatePackage, object]:
    from build.tei.lib016_hastings_dictionary_oracle import _oracle
    from build.tei.lib016_hastings_dictionary_reconstruction import (
        build_candidate,
        load_source_manifest,
    )

    root = tmp_path_factory.mktemp("lib016-bundle")
    source_manifest = load_source_manifest(
        MANIFEST, repository_root=ROOT, source_root=SOURCE_ROOT
    )
    candidate = build_candidate(source_manifest, root / "candidate")
    report = validate(source_manifest, candidate, _oracle)
    return source_manifest, candidate, report


def _clone_candidate(tmp_path: Path, candidate: CandidatePackage, label: str) -> Path:
    destination = tmp_path / label
    destination.mkdir()
    for item in candidate.path.iterdir():
        os.link(item, destination / item.name)
    return destination


def _replace_file(path: Path, name: str, content: bytes) -> None:
    target = path / name
    target.unlink()
    target.write_bytes(content)


def _reseal(path: Path, name: str, content: bytes) -> CandidatePackage:
    _replace_file(path, name, content)
    manifest = json.loads((path / "manifest.json").read_bytes())
    member = next(item for item in manifest["members"] if item["name"] == name)
    member["bytes"] = len(content)
    member["sha256"] = hashlib.sha256(content).hexdigest()
    _replace_file(path, "manifest.json", _canonical(manifest))
    return CandidatePackage.load(path)


def _volume_block(content: bytes, number: int) -> tuple[int, int, bytes]:
    marker = f'<text xml:id="lib016-member-{number:02d}"'.encode()
    start = content.index(marker)
    end = content.index(b"</text>", start) + len(b"</text>")
    return start, end, content[start:end]


def test_exact_five_member_source_identity_and_no_separator_aggregate() -> None:
    from build.tei.lib016_hastings_dictionary_reconstruction import inspect_source_root

    members = inspect_source_root(SOURCE_ROOT)
    aggregate = b"".join(member.content for member in members)
    assert [member.name for member in members] == sorted(
        (member.name for member in members), key=str.casefold
    )
    assert len(aggregate) == 44_374_718
    assert hashlib.sha256(aggregate).hexdigest() == AGGREGATE_SHA256
    assert sum(member.physical_lines for member in members) == 902_993
    assert members[0].latin_letters == 0
    assert members[0].greek_classified_characters == 4_057_175


def test_source_local_contract_is_complete_nonaccepted_and_strict_json() -> None:
    profile = json.loads(
        (SOURCE_DIR / "lib016-hastings.reconstruction-profile.json").read_bytes()
    )
    policy = json.loads(
        (SOURCE_DIR / "lib016-hastings.validation-policy.json").read_bytes()
    )
    manifest = json.loads(MANIFEST.read_bytes())
    readme = (SOURCE_DIR / "README.source.md").read_text(encoding="utf-8")
    assert profile["aggregate"] == {
        "definition": "five retained UTF-8 member bytes concatenated in lexicographic filename order with no separator",
        "bytes": 44_374_718,
        "sha256": AGGREGATE_SHA256,
        "member_count": 5,
    }
    assert profile["coverage"]["represented_lines"] == 902_993
    assert profile["extra_volume"] == {
        "filename": "b24749163_0005_djvu.txt",
        "physical_lines": 217_888,
        "latin_letters": 0,
        "greek_classified_characters": 4_057_175,
        "status": "source-bound-re-ocr-required",
        "silent_correction": False,
    }
    assert policy["candidate_status"] == "nonaccepted"
    assert policy["publication_authorized"] is False
    assert len(manifest["authorities"]) == 14
    assert [item["order"] for item in manifest["authorities"][:5]] == [1, 2, 3, 4, 5]
    assert manifest["authorities"][5] == {
        "name": "work-identity-config",
        "path": "sources/reference/hastings-dictionary-of-the-bible/config.json",
        "role": "work-identity-config",
        "bytes": 1905,
        "sha256": "72fa2720f5ab5599ad446aed096d3b5118b42d5a1beb45e92a4b7fdd85fd61d0",
    }
    assert manifest["catalog_claim_lineage"] == {
        "contract": "ocd-catalog-claim-lineage-v1",
        "work_id": WORK_ID,
        "retained_source_sha256": MEMBER_SET_SHA256,
        "claim_count": 1,
        "claims": [
            {
                "source_path": "reference/hastings-dictionary-of-the-bible.json",
                "legacy_source_sha256": AGGREGATE_SHA256,
            }
        ],
    }
    assert (
        manifest["lineage"]["schema_rebase"]["from"]["sha256"]
        == "eab839cd9f2cbce22fb86f5e8928488b8c91a41f5f83820bb9430dc81fa5c421"
    )
    assert manifest["lineage"]["schema_rebase"]["to"] == {
        "bytes": 2173,
        "sha256": "3aea71ac3407e3ac9b82a6ba89e13430251de685f8efd2399e1bd5176f41a4e3",
    }
    assert "partial diagnostic evidence only" in readme
    assert "publication is not authorized" in readme
    assert not any(
        path.name in {"witnesses.json", "config.json"} for path in SOURCE_DIR.iterdir()
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown-field",
        "duplicate-field",
        "stale-schema-pin",
        "stale-work-config",
        "lineage-contract",
        "lineage-work",
        "lineage-retained",
        "lineage-count",
        "lineage-path",
        "lineage-legacy-hash",
    ],
)
def test_source_manifest_loader_rejects_noncanonical_object_shape(
    mutation: str, tmp_path: Path
) -> None:
    from build.tei.lib016_hastings_dictionary_reconstruction import load_source_manifest

    content = MANIFEST.read_bytes()
    if mutation == "unknown-field":
        value = json.loads(content)
        value["unexpected"] = "self-resealed"
        content = _canonical(value)
    elif mutation == "duplicate-field":
        content = content.replace(
            b'  "contract": "ocd-source-manifest-v1",',
            b'  "contract": "ocd-source-manifest-v1",\n  "contract": "ocd-source-manifest-v1",',
            1,
        )
    elif mutation == "stale-schema-pin":
        value = json.loads(content)
        schema = next(
            item
            for item in value["authorities"]
            if item["name"] == "candidate-package-schema"
        )
        schema.update(
            {
                "bytes": 2244,
                "sha256": "eab839cd9f2cbce22fb86f5e8928488b8c91a41f5f83820bb9430dc81fa5c421",
            }
        )
        value["package_schema"]["sha256"] = schema["sha256"]
        content = _canonical(value)
        for authority in value["authorities"][5:]:
            target = tmp_path / authority["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / authority["path"]).read_bytes())
    else:
        value = json.loads(content)
        if mutation == "stale-work-config":
            config = next(
                item
                for item in value["authorities"]
                if item["name"] == "work-identity-config"
            )
            config["sha256"] = "0" * 64
        elif mutation == "lineage-contract":
            value["catalog_claim_lineage"]["contract"] = "self-resealed"
        elif mutation == "lineage-work":
            value["catalog_claim_lineage"]["work_id"] = "other-work"
        elif mutation == "lineage-retained":
            value["catalog_claim_lineage"]["retained_source_sha256"] = "0" * 64
        elif mutation == "lineage-count":
            value["catalog_claim_lineage"]["claim_count"] = 2
        elif mutation == "lineage-path":
            value["catalog_claim_lineage"]["claims"][0]["source_path"] = (
                "reference/other-work.json"
            )
        else:
            value["catalog_claim_lineage"]["claims"][0]["legacy_source_sha256"] = (
                "0" * 64
            )
        content = _canonical(value)
        for authority in value["authorities"][5:]:
            target = tmp_path / authority["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / authority["path"]).read_bytes())
    manifest = tmp_path / MANIFEST.relative_to(ROOT)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_bytes(content)
    expected = {
        "stale-schema-pin": "authority bytes drift: candidate-package-schema",
        "stale-work-config": "authority bytes drift: work-identity-config",
        "lineage-contract": "catalog claim lineage drift",
        "lineage-work": "catalog claim lineage drift",
        "lineage-retained": "catalog claim lineage drift",
        "lineage-count": "catalog claim lineage drift",
        "lineage-path": "catalog claim lineage drift",
        "lineage-legacy-hash": "catalog claim lineage drift",
    }.get(mutation)
    with pytest.raises(ValueError, match=expected):
        load_source_manifest(
            manifest, repository_root=tmp_path, source_root=SOURCE_ROOT
        )


def test_complete_candidate_is_lossless_schema_valid_and_independently_accepted(
    bundle: tuple[object, CandidatePackage, object],
) -> None:
    source_manifest, candidate, report = bundle
    assert report.status == "pass"
    assert report.findings == ()
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
        (SOURCE_DIR / "lib016-hastings.source-accountability.schema.json").read_bytes()
    )
    Draft202012Validator(accountability_schema).validate(accountability)
    assert accountability["aggregate_sha256"] == AGGREGATE_SHA256
    assert accountability["members"][0]["byte_start"] == 0
    assert accountability["members"][-1]["byte_end"] == 44_374_718
    root = etree.fromstring(
        candidate.member_bytes("content.tei.xml"), etree.XMLParser(huge_tree=True)
    )
    compiled_tei_schema(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd").assertValid(etree.ElementTree(root))
    abs_ = root.xpath(
        "./tei:text/tei:group/tei:text/tei:body/tei:div/tei:ab", namespaces=NS
    )
    assert len(abs_) == 5
    for ab, authority in zip(
        abs_, source_manifest.record["authorities"][:5], strict=True
    ):
        assert (ab.text or "").encode("utf-8") == source_manifest.authority_path(
            authority["name"]
        ).read_bytes()
    unresolved = candidate.member_bytes("unresolved.jsonl").decode("utf-8")
    assert "source-bound-re-ocr-required" in unresolved
    assert "publication remains unauthorized" in unresolved.lower()


def test_exact_work_catalog_route_is_verified_nonaccepted_and_not_ready(
    bundle: tuple[object, CandidatePackage, object], tmp_path: Path
) -> None:
    from build.tools.count_dataset_records import _manifest_config_ids
    from tests.runtime_candidate_baselines import current_runtime_catalog

    source_manifest, candidate, validation = bundle
    assert _manifest_config_ids(source_manifest.record, ROOT) == {WORK_ID}
    report = {
        "contract": "ocd-validation-report-v1",
        "status": validation.status,
        "candidate_sha256": validation.candidate_sha256,
        "source_manifest_sha256": validation.source_manifest_sha256,
        "attestation": dict(validation.attestation),
        "findings": list(validation.findings),
        "report_sha256": validation.sha256,
    }
    validation_path = tmp_path / "validation.json"
    validation_path.write_bytes(_canonical(report))
    catalog = current_runtime_catalog(
        root=ROOT,
        manifest=MANIFEST,
        work_ids=(WORK_ID,),
        data_resource_allowlist=["data/reference/hastings-dictionary-of-the-bible.json"],
        reconstruction_evidence={
            (source_manifest.record["source_id"], WORK_ID): (
                candidate.path,
                validation_path,
            )
        },
    )
    assert catalog.summary["work_units"] == 1
    assert {item["work_id"] for item in catalog.works} == {WORK_ID}
    work = next(item for item in catalog.works if item["work_id"] == WORK_ID)
    state = work["reconstruction_state"]
    routes = [
        route
        for route in state["routes"]
        if route["source_id"] == source_manifest.record["source_id"]
    ]
    assert routes == [
        {
            "association": "catalog_claim_lineage+exact_id",
            "manifest": "sources/hastings-dictionary-of-the-bible/LIB-016/lib016-hastings.source-manifest.json",
            "scope": "work",
            "source_id": WORK_ID,
            "verification": "verified",
            "candidate_verification": "verified",
            "validation_verification": "verified",
        }
    ]
    assert state["human_review"] == "required"
    assert state["accepted_ir"] == "not_accepted"
    assert state["publication"] == "not_ready"


@pytest.mark.parametrize(
    "mutation",
    [
        "omission",
        "duplication",
        "reorder",
        "text",
        "metadata",
        "root-xml-lang",
        "comment",
    ],
)
def test_oracle_rejects_resealed_tei_scope_order_text_and_metadata_attacks(
    mutation: str, tmp_path: Path, bundle: tuple[object, CandidatePackage, object]
) -> None:
    from build.tei.lib016_hastings_dictionary_oracle import _oracle

    source_manifest, candidate, _ = bundle
    path = _clone_candidate(tmp_path, candidate, mutation)
    content = candidate.member_bytes("content.tei.xml")
    if mutation == "omission":
        start, end, _ = _volume_block(content, 5)
        content = content[:start] + content[end:]
    elif mutation == "duplication":
        start, end, block = _volume_block(content, 5)
        content = content[:end] + block + content[end:]
    elif mutation == "reorder":
        start2, end2, block2 = _volume_block(content, 2)
        start3, end3, block3 = _volume_block(content, 3)
        content = (
            content[:start2] + block3 + content[end2:start3] + block2 + content[end3:]
        )
    elif mutation == "text":
        content = content.replace(b"Google", b"G00gle", 1)
    elif mutation == "root-xml-lang":
        content = content.replace(
            b'<TEI xmlns="http://www.tei-c.org/ns/1.0" xml:id="lib016-hastings-dictionary-candidate">',
            b'<TEI xmlns="http://www.tei-c.org/ns/1.0" xml:id="lib016-hastings-dictionary-candidate" xml:lang="en">',
            1,
        )
    elif mutation == "comment":
        declaration_end = content.index(b"?>") + 2
        content = (
            content[:declaration_end]
            + b"<!-- self-resealed -->"
            + content[declaration_end:]
        )
    else:
        content = content.replace(
            b"Dictionary of the Bible: faithful retained-OCR transcription candidate",
            b"Accepted Dictionary of the Bible: normalized critical edition",
            1,
        )
    mutated = _reseal(path, "content.tei.xml", content)
    with pytest.raises((ValueError, etree.DocumentInvalid, etree.XMLSyntaxError)):
        validate(source_manifest, mutated, _oracle)


@pytest.mark.parametrize(
    "mutation",
    [
        "accountability",
        "provenance",
        "unresolved",
        "manifest-converter",
        "manifest-schema",
    ],
)
def test_oracle_rejects_resealed_evidence_and_manifest_attacks(
    mutation: str, tmp_path: Path, bundle: tuple[object, CandidatePackage, object]
) -> None:
    from build.tei.lib016_hastings_dictionary_oracle import _oracle

    source_manifest, candidate, _ = bundle
    path = _clone_candidate(tmp_path, candidate, mutation)
    if mutation == "accountability":
        value = json.loads(candidate.member_bytes("source-accountability.json"))
        value["members"][0]["represented_lines"] -= 1
        mutated = _reseal(path, "source-accountability.json", _canonical(value))
    elif mutation == "provenance":
        value = json.loads(candidate.member_bytes("provenance.json"))
        value["publication_authorized"] = True
        mutated = _reseal(path, "provenance.json", _canonical(value))
    elif mutation == "unresolved":
        value = candidate.member_bytes("unresolved.jsonl").replace(
            b"source-bound-re-ocr-required", b"resolved-and-accepted", 1
        )
        mutated = _reseal(path, "unresolved.jsonl", value)
    else:
        value = json.loads(candidate.member_bytes("manifest.json"))
        if mutation == "manifest-converter":
            value["converter"]["version"] = "2"
        else:
            value["package_schema"]["sha256"] = "0" * 64
        _replace_file(path, "manifest.json", _canonical(value))
        mutated = CandidatePackage.load(path)
    with pytest.raises(ValueError):
        validate(source_manifest, mutated, _oracle)


class _AuthorityFacade:
    def __init__(self, original: object, record: object, name: str, path: Path) -> None:
        self.original = original
        self.record = record
        self.name = name
        self.replacement = path
        self.path = original.path
        self.repository_root = original.repository_root
        self.source_root = original.source_root
        self.sha256 = original.sha256

    def verify(self) -> None:
        self.original.verify()

    def authority_path(self, name: str) -> Path:
        return (
            self.replacement
            if name == self.name
            else self.original.authority_path(name)
        )


@pytest.mark.parametrize(
    "authority_name",
    [
        "retained-member-01",
        "work-identity-config",
        "reconstruction-profile",
        "validation-policy",
        "source-readme",
        "source-accountability-schema",
        "tei-p5-xsd-xml",
    ],
)
def test_oracle_rejects_resealed_source_and_authority_evidence(
    authority_name: str, tmp_path: Path, bundle: tuple[object, CandidatePackage, object]
) -> None:
    from build.tei.lib016_hastings_dictionary_oracle import _oracle

    source_manifest, candidate, _ = bundle
    replacement = tmp_path / authority_name
    replacement.write_bytes(
        source_manifest.authority_path(authority_name).read_bytes() + b"\n"
    )
    record = json.loads(MANIFEST.read_bytes())
    item = next(
        item for item in record["authorities"] if item["name"] == authority_name
    )
    item["bytes"] = replacement.stat().st_size
    item["sha256"] = hashlib.sha256(replacement.read_bytes()).hexdigest()
    facade = _AuthorityFacade(source_manifest, record, authority_name, replacement)
    with pytest.raises(ValueError):
        _oracle(facade, candidate)


@pytest.mark.parametrize(
    "field",
    [
        "contract",
        "work_id",
        "retained_source_sha256",
        "claim_count",
        "source_path",
        "legacy_source_sha256",
    ],
)
def test_oracle_rejects_each_resealed_catalog_lineage_field(
    field: str, bundle: tuple[object, CandidatePackage, object]
) -> None:
    from build.tei.lib016_hastings_dictionary_oracle import _verify_authorities
    from build.tei.lib016_hastings_dictionary_reconstruction import _freeze

    source_manifest, _, _ = bundle
    record = json.loads(MANIFEST.read_bytes())
    lineage = record["catalog_claim_lineage"]
    if field in {"source_path", "legacy_source_sha256"}:
        lineage["claims"][0][field] = (
            "reference/other-work.json" if field == "source_path" else "0" * 64
        )
    elif field == "claim_count":
        lineage[field] = 2
    else:
        lineage[field] = "0" * 64
    facade = _AuthorityFacade(
        source_manifest,
        _freeze(record),
        "unused",
        source_manifest.path,
    )
    with pytest.raises(ValueError, match="catalog claim lineage drift"):
        _verify_authorities(facade)


def test_fresh_process_different_cwd_packages_are_byte_identical(
    tmp_path: Path,
) -> None:
    outputs = [tmp_path / "run-a", tmp_path / "run-b"]
    cwds = [ROOT, tmp_path]
    script = ROOT / "build/tei/lib016_hastings_dictionary_reconstruction.py"
    for output, cwd in zip(outputs, cwds, strict=True):
        subprocess.run(
            [
                sys.executable,
                str(script),
                "--repository-root",
                str(ROOT),
                "--manifest",
                str(MANIFEST),
                "--source-root",
                str(SOURCE_ROOT),
                "--output",
                str(output),
            ],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )
    assert sorted(path.name for path in outputs[0].iterdir()) == sorted(
        path.name for path in outputs[1].iterdir()
    )
    for name in sorted(path.name for path in outputs[0].iterdir()):
        assert (outputs[0] / name).read_bytes() == (outputs[1] / name).read_bytes()
