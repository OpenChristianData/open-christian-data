from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from lxml import etree
import pytest

from build.tei.creeds_json_lib064_oracle import _closure_digest, _oracle
from build.tei.creeds_json_lib064_reconstruction import ASSIGNED, _convert
from build.tools.count_dataset_records import collect_work_catalog
from ocd_kernel.reconstruction import (
    CandidatePackage,
    SourceManifest,
    reconstruct,
    validate,
)
from ocd_kernel.reconstruction.decision import load_verified_review
from build.lib.tei_xsd import compiled_tei_schema


pytestmark = [
    pytest.mark.slow,
    pytest.mark.xdist_group(name="creeds-json-lib064-reconstruction"),
]

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "sources/doctrinal-documents/lib064-creeds-json"
EVIDENCE_ROOT: Path
TEI_NS = "http://www.tei-c.org/ns/1.0"
TEI = {"tei": TEI_NS}
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
EXPECTED_COUNTS = {
    "french-confession-of-faith": {
        "objects": 44,
        "members": 138,
        "strings": 136,
        "arrays": 3,
        "items": 45,
        "numbers": 0,
        "booleans": 0,
        "nulls": 1,
    },
    "gregorys-declaration-of-faith": {
        "objects": 3,
        "members": 13,
        "strings": 10,
        "arrays": 2,
        "items": 2,
        "numbers": 0,
        "booleans": 0,
        "nulls": 1,
    },
    "helvetic-consensus": {
        "objects": 29,
        "members": 93,
        "strings": 91,
        "arrays": 3,
        "items": 29,
        "numbers": 0,
        "booleans": 0,
        "nulls": 0,
    },
    "ignatius-creed": {
        "objects": 3,
        "members": 13,
        "strings": 10,
        "arrays": 2,
        "items": 1,
        "numbers": 0,
        "booleans": 0,
        "nulls": 0,
    },
    "irenaeus-rule-of-faith": {
        "objects": 3,
        "members": 13,
        "strings": 9,
        "arrays": 2,
        "items": 1,
        "numbers": 0,
        "booleans": 0,
        "nulls": 1,
    },
    "london-baptist-confession-1689": {
        "objects": 194,
        "members": 428,
        "strings": 432,
        "arrays": 35,
        "items": 232,
        "numbers": 0,
        "booleans": 0,
        "nulls": 0,
    },
    "nicene-creed": {
        "objects": 3,
        "members": 13,
        "strings": 12,
        "arrays": 2,
        "items": 3,
        "numbers": 0,
        "booleans": 0,
        "nulls": 0,
    },
    "savoy-declaration": {
        "objects": 193,
        "members": 426,
        "strings": 390,
        "arrays": 35,
        "items": 192,
        "numbers": 0,
        "booleans": 0,
        "nulls": 1,
    },
    "scots-confession": {
        "objects": 27,
        "members": 87,
        "strings": 89,
        "arrays": 3,
        "items": 31,
        "numbers": 0,
        "booleans": 0,
        "nulls": 0,
    },
    "second-helvetic-confession": {
        "objects": 310,
        "members": 658,
        "strings": 625,
        "arrays": 33,
        "items": 309,
        "numbers": 0,
        "booleans": 0,
        "nulls": 0,
    },
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _jsonable(value: object) -> object:
    if isinstance(value, dict) or hasattr(value, "items"):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


@pytest.fixture(scope="session", autouse=True)
def _disposable_evidence(tmp_path_factory: pytest.TempPathFactory) -> None:
    global EVIDENCE_ROOT
    EVIDENCE_ROOT = tmp_path_factory.mktemp("lib064-evidence")
    for work_id, _stem in ASSIGNED:
        source = _source(work_id)
        work_root = EVIDENCE_ROOT / work_id
        work_root.mkdir()
        candidate = reconstruct(source, work_root / "candidate", _convert)
        report = validate(source, candidate, _oracle)
        record = {
            "contract": "ocd-validation-report-v1",
            "status": report.status,
            "candidate_sha256": report.candidate_sha256,
            "source_manifest_sha256": report.source_manifest_sha256,
            "attestation": _jsonable(report.attestation),
            "findings": list(report.findings),
        }
        (work_root / "validation.json").write_bytes(
            _canonical({**record, "report_sha256": report.sha256})
        )


def _manifest_path(work_id: str) -> Path:
    return ROOT / "tests/fixtures/reconstruction-runtime" / f"creeds-lib064-{work_id}.source-manifest.json"


def _source(work_id: str) -> SourceManifest:
    return SourceManifest.load(_manifest_path(work_id), repository_root=ROOT)


def _candidate(work_id: str) -> CandidatePackage:
    return CandidatePackage.load(EVIDENCE_ROOT / work_id / "candidate")


def _reseal(path: Path, member_name: str) -> CandidatePackage:
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    content = (path / member_name).read_bytes()
    member = next(item for item in manifest["members"] if item["name"] == member_name)
    member.update(bytes=len(content), sha256=_sha(content))
    manifest_path.write_bytes(_canonical(manifest))
    return CandidatePackage.load(path)


def _write_tree(path: Path, tree: etree._ElementTree) -> None:
    path.write_bytes(
        etree.tostring(
            tree,
            encoding="UTF-8",
            xml_declaration=True,
            pretty_print=False,
        )
    )


def _assert_p5_valid(source: SourceManifest, tree: etree._ElementTree) -> None:
    schema = compiled_tei_schema(source.authority_path("tei-p5-xsd"))
    assert schema.validate(tree), schema.error_log.last_error


def _package_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_frozen_ticket_and_maps_bind_exact_ten_work_scope() -> None:
    expected = {work_id for work_id, _stem in ASSIGNED}
    assert expected == set(EXPECTED_COUNTS)
    ticket = (
        ROOT
        / "plans/2026-08-26-whole-library-faithful-tei-completion/tickets/library/064-reconstruct-and-review-json-confessions-and-creeds-cohort-2.md"
    ).read_text(encoding="utf-8")
    for work_id in expected:
        assert f"`{work_id}`" in ticket
    work_map = (
        ROOT
        / "plans/2026-08-26-whole-library-faithful-tei-completion/02-work-ticket-map.md"
    ).read_text(encoding="utf-8")
    source_map = (
        ROOT
        / "plans/2026-08-26-whole-library-faithful-tei-completion/05-source-ticket-map.md"
    ).read_text(encoding="utf-8")
    profile = json.loads(
        (SOURCE_ROOT / "lib064.reconstruction-profile.json").read_bytes()
    )
    assigned = {row["work_id"]: row for row in profile["assigned_members"]}
    assert (
        sum(
            f"| `{work_id}`" in line and "| LIB-064 |" in line
            for line in work_map.splitlines()
            for work_id in expected
        )
        == 10
    )
    for work_id in expected:
        rows = [
            line
            for line in source_map.splitlines()
            if f"| `{work_id}`" in line and "| LIB-064 |" in line
        ]
        assert len(rows) == 1
        assert f"sha256:{assigned[work_id]['legacy_normalized_sha256']}" in rows[0]


def test_complete_retained_family_census_and_legacy_claim_semantics_are_exact() -> None:
    profile = json.loads(
        (SOURCE_ROOT / "lib064.reconstruction-profile.json").read_bytes()
    )
    census = profile["family_census"]
    assert len(census) == profile["family_member_count"] == 43
    assert sum(row["disposition"] == "included-lib064" for row in census) == 10
    assert (
        sum(row["disposition"] == "excluded-other-library-ticket" for row in census)
        == 33
    )
    assert [row["path"] for row in census] == sorted(row["path"] for row in census)
    retained = sorted((ROOT / "raw/Creeds.json/creeds").glob("*.json"))
    assert [str(ROOT / row["path"]) for row in census] == [
        str(path) for path in retained
    ]
    for row in census:
        content = (ROOT / row["path"]).read_bytes()
        normalized = content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        assert row["bytes"] == len(content)
        assert row["sha256"] == _sha(content)
        assert row["normalized_utf8_sha256"] == _sha(normalized)
        assert row["reason"]


@pytest.mark.parametrize("work_id", [work_id for work_id, _stem in ASSIGNED])
def test_retained_packages_are_exact_independently_verified_nonaccepted_evidence(
    work_id: str,
) -> None:
    source = _source(work_id)
    candidate = _candidate(work_id)
    review = load_verified_review(
        source,
        candidate_path=candidate.path,
        validation_path=EVIDENCE_ROOT / work_id / "validation.json",
    )
    assert review.validation.status == "pass"
    assert candidate.member_names == (
        "README.source.md",
        "content.tei.xml",
        "manifest.json",
        "provenance.json",
        "source-accountability.json",
        "unresolved.jsonl",
    )
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    assert accountability["json_counts"] == EXPECTED_COUNTS[work_id]
    assert accountability["omitted_json_node_count"] == 0
    assert accountability["invented_json_node_count"] == 0
    assert accountability["family_member_count"] == 43
    assert accountability["family_included_count"] == 10
    assert accountability["family_excluded_count"] == 33
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    assert provenance["status"] == {
        "candidate": "nonaccepted",
        "human_review": "required",
        "accepted_ir": "not_accepted",
        "publication": "not_ready",
    }
    assert (
        provenance["retained_metadata"]
        == json.loads(
            source.authority_path("retained-json").read_text(encoding="utf-8")
        )["Metadata"]
    )
    assert len(candidate.member_bytes("unresolved.jsonl").splitlines()) == 3


def test_london_preserves_all_confession_sections_and_proof_representations() -> None:
    work_id = "london-baptist-confession-1689"
    raw = json.loads(_source(work_id).authority_path("retained-json").read_bytes())
    keys: list[str] = []

    def visit(value: object) -> None:
        if isinstance(value, dict):
            keys.extend(value)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(raw)
    expected = {
        key: keys.count(key)
        for key in ("Content", "ContentWithProofs", "Proofs", "ProofsWithScripture")
    }
    assert expected["Content"] > 0
    tree = etree.fromstring(_candidate(work_id).member_bytes("content.tei.xml"))
    observed_keys = tree.xpath(".//tei:head[@type='json-key']/text()", namespaces=TEI)
    assert {
        key: observed_keys.count(key)
        for key in ("Content", "ContentWithProofs", "Proofs", "ProofsWithScripture")
    } == expected


def test_savoy_preserves_unusual_data_before_metadata_order_and_restricted_rights() -> (
    None
):
    work_id = "savoy-declaration"
    raw = json.loads(
        _source(work_id).authority_path("retained-json").read_bytes(),
        object_pairs_hook=dict,
    )
    assert list(raw) == ["Data", "Metadata"]
    accountability = json.loads(
        _candidate(work_id).member_bytes("source-accountability.json")
    )
    assert accountability["crosswalk"][1]["key"] == "Data"
    provenance = json.loads(_candidate(work_id).member_bytes("provenance.json"))
    assert provenance["rights"]["reuse_permission"] == "required"
    assert b"permission-required" in _candidate(work_id).member_bytes(
        "unresolved.jsonl"
    )
    _oracle(_source(work_id), _candidate(work_id))


@pytest.mark.parametrize(
    "mutation",
    [
        "semantic-omission",
        "member-key",
        "array-reorder",
        "scalar-value",
        "literal-byte-stream",
        "header-metadata",
        "comment",
    ],
)
def test_independent_oracle_rejects_resealed_tei_mutations(
    tmp_path: Path,
    mutation: str,
) -> None:
    work_id = "london-baptist-confession-1689"
    source = _source(work_id)
    target = tmp_path / mutation
    shutil.copytree(_candidate(work_id).path, target)
    xml_path = target / "content.tei.xml"
    tree = etree.parse(str(xml_path), etree.XMLParser(remove_comments=False))
    root = tree.getroot()
    if mutation == "semantic-omission":
        node = root.xpath(
            ".//tei:div[@type='json-semantic-tree']/tei:div", namespaces=TEI
        )[0]
        node.getparent().remove(node)
    elif mutation == "member-key":
        root.xpath(".//tei:head[@type='json-key']", namespaces=TEI)[0].text = "Invented"
    elif mutation == "array-reorder":
        array = root.xpath(
            ".//tei:div[@type='json-array'][count(tei:div) > 1]", namespaces=TEI
        )[0]
        first, second = list(array)[:2]
        array.remove(second)
        array.insert(0, second)
        assert list(array)[1] is first
    elif mutation == "scalar-value":
        scalar = root.xpath(
            ".//tei:ab[@type='json-scalar'][string-length(text()) > 0]", namespaces=TEI
        )[0]
        scalar.text = (scalar.text or "") + " invented"
    elif mutation == "literal-byte-stream":
        literal = root.xpath(
            ".//tei:ab[@type='base64-application-json']", namespaces=TEI
        )[0]
        literal.text = "A" + (literal.text or "")[1:]
    elif mutation == "header-metadata":
        root.xpath("./tei:teiHeader//tei:title", namespaces=TEI)[0].text = "Invented"
    else:
        root.xpath("./tei:text/tei:body", namespaces=TEI)[0].append(
            etree.Comment("invented")
        )
    _write_tree(xml_path, tree)
    mutated = _reseal(target, "content.tei.xml")
    with pytest.raises(ValueError):
        _oracle(source, mutated)


@pytest.mark.parametrize(
    "mutation",
    [
        "publisher",
        "resp-role",
        "print-source",
        "rights-text",
        "extra-metadata-node",
        "extra-metadata-attribute",
    ],
)
def test_complete_header_oracle_rejects_p5_valid_resealed_mutations(
    tmp_path: Path,
    mutation: str,
) -> None:
    work_id = "london-baptist-confession-1689"
    source = _source(work_id)
    target = tmp_path / mutation
    shutil.copytree(_candidate(work_id).path, target)
    xml_path = target / "content.tei.xml"
    tree = etree.parse(str(xml_path))
    root = tree.getroot()
    if mutation == "publisher":
        root.xpath("./tei:teiHeader//tei:publisher", namespaces=TEI)[
            0
        ].text = "Invented Publisher"
    elif mutation == "resp-role":
        root.xpath("./tei:teiHeader//tei:resp", namespaces=TEI)[0].text = "Editor"
    elif mutation == "print-source":
        root.xpath("./tei:teiHeader//tei:note[@type='print-source']", namespaces=TEI)[
            0
        ].text = "Invented source description"
    elif mutation == "rights-text":
        root.xpath("./tei:teiHeader//tei:availability/tei:p", namespaces=TEI)[
            0
        ].text = "Invented rights statement"
    elif mutation == "extra-metadata-node":
        root.xpath("./tei:teiHeader//tei:bibl", namespaces=TEI)[0].append(
            etree.Element(f"{{{TEI_NS}}}note", type="invented")
        )
    else:
        root.xpath("./tei:teiHeader//tei:title", namespaces=TEI)[0].set("n", "invented")
    _assert_p5_valid(source, tree)
    _write_tree(xml_path, tree)
    mutated = _reseal(target, "content.tei.xml")
    with pytest.raises(ValueError):
        _oracle(source, mutated)


@pytest.mark.parametrize(
    "mutation",
    [
        "extra-top-level-key",
        "wrong-source-id",
        "member-bytes-float",
        "extra-member-key",
    ],
)
def test_closed_manifest_oracle_rejects_fully_resealed_mutations(
    tmp_path: Path,
    mutation: str,
) -> None:
    work_id = "london-baptist-confession-1689"
    source = _source(work_id)
    target = tmp_path / mutation
    shutil.copytree(_candidate(work_id).path, target)
    manifest_path = target / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    if mutation == "extra-top-level-key":
        manifest["invented"] = True
    elif mutation == "wrong-source-id":
        manifest["source_id"] = "invented-source"
    elif mutation == "member-bytes-float":
        manifest["members"][0]["bytes"] = float(manifest["members"][0]["bytes"])
    else:
        manifest["members"][0]["invented"] = "extra"
    manifest_path.write_bytes(_canonical(manifest))
    mutated = CandidatePackage.load(target)
    mutated.verify_integrity()
    with pytest.raises(ValueError):
        _oracle(source, mutated)


@pytest.mark.parametrize(
    ("member_name", "mutation"),
    [
        ("source-accountability.json", "extra-key"),
        ("provenance.json", "status"),
        ("unresolved.jsonl", "clear"),
        ("README.source.md", "publication"),
    ],
)
def test_independent_oracle_rejects_resealed_evidence_mutations(
    tmp_path: Path,
    member_name: str,
    mutation: str,
) -> None:
    work_id = "london-baptist-confession-1689"
    source = _source(work_id)
    target = tmp_path / mutation
    shutil.copytree(_candidate(work_id).path, target)
    path = target / member_name
    if member_name == "source-accountability.json":
        value = json.loads(path.read_bytes())
        value["invented_extra_key"] = True
        path.write_bytes(_canonical(value))
    elif member_name == "provenance.json":
        value = json.loads(path.read_bytes())
        value["status"]["publication"] = "ready"
        path.write_bytes(_canonical(value))
    elif member_name == "unresolved.jsonl":
        path.write_bytes(b"")
    else:
        path.write_bytes(path.read_bytes() + b"\nPublication ready.\n")
    mutated = _reseal(target, member_name)
    with pytest.raises(ValueError):
        _oracle(source, mutated)


def test_oracle_is_producer_and_legacy_parser_independent_with_exact_closure() -> None:
    oracle_source = (ROOT / "build/tei/creeds_json_lib064_oracle.py").read_text(
        encoding="utf-8"
    )
    policy = json.loads((SOURCE_ROOT / "lib064.validation-policy.json").read_bytes())
    for forbidden in policy["forbidden_oracle_imports"]:
        assert f"import {forbidden}" not in oracle_source
        assert f"from {forbidden}" not in oracle_source
    expected = _closure_digest(ROOT, policy)
    for work_id, _stem in ASSIGNED:
        assert _source(work_id).record["validator"]["import_closure_sha256"] == expected


def test_two_fresh_process_different_cwd_hashseed_package_sets_are_byte_identical(
    tmp_path: Path,
) -> None:
    outputs = []
    for ordinal, seed in enumerate(("17", "83"), start=1):
        external_cwd = tmp_path / f"cwd-{ordinal}"
        external_cwd.mkdir()
        output = tmp_path / f"run-{ordinal}"
        code = (
            "from pathlib import Path;import sys;"
            "from ocd_kernel.reconstruction import SourceManifest,reconstruct;"
            "from build.tei.creeds_json_lib064_reconstruction import ASSIGNED,_convert;"
            f"r=Path({str(ROOT)!r});o=Path(sys.argv[1]);"
            "[(lambda d,m: (d.mkdir(parents=True),reconstruct(SourceManifest.load(m,repository_root=r),d/'candidate',_convert)))(o/w,r/f'tests/fixtures/reconstruction-runtime/creeds-lib064-{w}.source-manifest.json') for w,_ in ASSIGNED]"
        )
        environment = os.environ.copy()
        environment["PYTHONHASHSEED"] = seed
        environment["PYTHONPATH"] = (
            str(ROOT) + os.pathsep + environment.get("PYTHONPATH", "")
        )
        subprocess.run(
            [sys.executable, "-c", code, str(output)],
            cwd=external_cwd,
            env=environment,
            check=True,
            timeout=180,
        )
        outputs.append(output)
    expected = {
        f"{work_id}/candidate/{name}": content
        for work_id, _stem in ASSIGNED
        for name, content in _package_bytes(
            EVIDENCE_ROOT / work_id / "candidate"
        ).items()
    }
    assert _package_bytes(outputs[0]) == expected
    assert _package_bytes(outputs[1]) == expected


def test_work_catalog_routes_all_ten_packages_as_verified_nonaccepted(monkeypatch: pytest.MonkeyPatch) -> None:
    source_by_work = {work_id: _source(work_id) for work_id, _stem in ASSIGNED}
    evidence = {
        (str(source_by_work[work_id].record["source_id"]), work_id): (
            EVIDENCE_ROOT / work_id / "candidate",
            EVIDENCE_ROOT / work_id / "validation.json",
        )
        for work_id, _stem in ASSIGNED
    }
    from build.tools import count_dataset_records

    manifest_paths = tuple(source.path for source in source_by_work.values())

    def selected_manifest_paths(sources_root: Path, selections):
        assert sources_root == ROOT / "sources"
        assert tuple(selections) == tuple(path.relative_to(ROOT).as_posix() for path in manifest_paths)
        return sources_root, manifest_paths

    # Use preserved runtime authorities with the real retained-claim evidence checks.
    monkeypatch.setattr(
        count_dataset_records, "_resolve_source_manifest_allowlist", selected_manifest_paths
    )
    catalog = collect_work_catalog(
        ROOT / "data",
        reconstruction_evidence=evidence,
        source_manifest_allowlist=[
            source.path.relative_to(ROOT).as_posix()
            for source in source_by_work.values()
        ],
        data_resource_allowlist=[
            f"data/{claim['source_path']}"
            for source in source_by_work.values()
            for claim in source.record["catalog_claim_lineage"]["claims"]
        ],
    )
    by_id = {work["work_id"]: work for work in catalog.works}
    assert catalog.summary["work_units"] == len(ASSIGNED)
    assert set(by_id) == {work_id for work_id, _stem in ASSIGNED}
    for work_id, _stem in ASSIGNED:
        state = by_id[work_id]["reconstruction_state"]
        assert state["retained_source"] == "manifest_bound"
        assert state["tei_candidate"] == "verified"
        assert state["validation"] == "verified"
        assert state["human_review"] == "required"
        assert state["accepted_ir"] == "not_accepted"
        assert state["publication"] == "not_ready"
        matching = [
            route
            for route in state["routes"]
            if route["source_id"] == source_by_work[work_id].record["source_id"]
        ]
        assert len(matching) == 1
        assert matching[0]["association"] == "catalog_claim_lineage+exact_id"
        assert matching[0]["scope"] == "work"
        assert matching[0]["candidate_verification"] == "verified"
        assert matching[0]["validation_verification"] == "verified"
