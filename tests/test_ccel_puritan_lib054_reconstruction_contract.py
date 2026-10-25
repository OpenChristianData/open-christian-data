from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from lxml import etree
import pytest

from build.tei.ccel_puritan_lib054_oracle import _closure, _closure_digest, _oracle
from build.tei.ccel_puritan_lib054_reconstruction import _convert
from build.tools.count_dataset_records import (
    _manifest_config_ids,
    _manifest_primary_hashes,
    collect_work_catalog,
)
from ocd_kernel.reconstruction import (
    CandidatePackage,
    SourceManifest,
    reconstruct,
    validate,
)


pytestmark = [pytest.mark.slow, pytest.mark.requires_local_artifacts]
ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "sources/structured-text/lib054-ccel-puritan"
MANIFEST = ROOT / 'tests/fixtures/reconstruction-runtime/puritan-lib054-ccel-puritan.source-manifest.json'
WORK_IDS = (
    "baxter-call-to-unconverted",
    "baxter-reformed-pastor",
    "baxter-saints-rest",
    "boston-crook-in-the-lot",
    "bunyan-grace-abounding",
    "bunyan-holy-war",
    "butler-analogy-of-religion",
    "edwards-distinguishing-marks",
    "edwards-freedom-of-the-will",
    "edwards-history-of-redemption",
)
SOURCE_HASHES = (
    "6e615176e913936a25457ad8f485ec5204f05a7f05397c2850fdae558b2e84a0",
    "a747146c22fe37acdd6018455ebb40dd2b6b7eb7ddaf309d261857a43ba31ea5",
    "b848aab1b45c721bd06ce02c30795e2e03f72594677feb9ec8c986c4853cb69f",
    "64cc81b01e511b788450d2a6389ede6629e35bdbb5c8429452bfc68a78ad1732",
    "21dba22cf36ddec4399091313ce74e826152ea62232f10e6182365496102e2c0",
    "0e85699e7ba7d78073c5321533f19e0dd287a14375d3481cc4dbd5d936f8007a",
    "1e075db3555e003b2338f7317d9eecb0aaa8e800462f3a41485c95bdb2eff0e7",
    "a2d8ff387fd51a02eaa073eda9581fd45f46f2d93b35c19f6fb9747b695d3b1f",
    "c710571e9f6993e732e7fab88a1c60f2f9c62770a16c32729d3559a18c4e9600",
    "301b521eaeae8f2077767cc107626ba8ca7a02f7b53dde5aafcb18a56b5ebeeb",
)
TEI = {"tei": "http://www.tei-c.org/ns/1.0"}
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _reseal(path: Path, member_name: str) -> CandidatePackage:
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    member = next(item for item in manifest["members"] if item["name"] == member_name)
    content = (path / member_name).read_bytes()
    member.update(bytes=len(content), sha256=_sha(content))
    manifest_path.write_bytes(_canonical(manifest))
    return CandidatePackage.load(path)


@pytest.fixture(scope="module")
def verified_candidate(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[SourceManifest, CandidatePackage, object]:
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    candidate = reconstruct(
        source, tmp_path_factory.mktemp("lib054-candidate") / "candidate", _convert
    )
    validation = validate(source, candidate, _oracle)
    return source, candidate, validation


def test_exact_ten_authorities_fifteen_member_census_and_metadata(
    verified_candidate: tuple[SourceManifest, CandidatePackage, object],
) -> None:
    source, candidate, validation = verified_candidate
    assert validation.status == "pass"
    primary = [
        item
        for item in source.record["authorities"]
        if item["role"] == "primary-source"
    ]
    assert len(primary) == 10
    assert tuple(item["sha256"] for item in primary) == SOURCE_HASHES
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    assert accountability["source_bytes"] == 5_244_468
    assert accountability["feature_count"] == 14_065
    assert accountability["qualified_attribute_count"] == 0
    assert accountability["comment_count"] == 44
    assert accountability["processing_instruction_count"] == 6
    assert accountability["processing_instruction_source_count"] == 3
    assert accountability["doctype_declaration_count"] == 8
    assert len(accountability["non_element_events"]) == 58
    assert accountability["member_census"]["counts"] == {
        "included": 10,
        "excluded": 5,
        "retained_family_total": 15,
    }
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    assert provenance["source_metadata"]["edwards-distinguishing-marks"] == []
    assert provenance["source_metadata"]["edwards-history-of-redemption"] == []
    assert (
        provenance["status"] == "nonaccepted"
        and provenance["publication"] == "not_ready"
    )


def test_complete_tei_projection_and_exact_embedded_bytes(
    verified_candidate: tuple[SourceManifest, CandidatePackage, object],
) -> None:
    source, candidate, _ = verified_candidate
    tree = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    works = tree.xpath("/tei:teiCorpus/tei:TEI", namespaces=TEI)
    assert tuple(item.get(XML_ID) for item in works) == WORK_IDS
    assert (
        len(tree.xpath("//tei:ab[@type='source-xml-element']", namespaces=TEI))
        == 14_065
    )
    notes = tree.xpath(
        "//tei:note[@type='exact-retained-source-bytes']", namespaces=TEI
    )
    assert len(notes) == 10
    for authority, note in zip(
        (
            item
            for item in source.record["authorities"]
            if item["role"] == "primary-source"
        ),
        notes,
        strict=True,
    ):
        import base64

        assert (
            base64.b64decode(note.text)
            == source.authority_path(str(authority["name"])).read_bytes()
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "omission",
        "duplication",
        "reorder",
        "attribute-reorder",
        "invention",
        "metadata",
        "rights",
        "evidence",
        "namespace",
    ],
)
def test_oracle_rejects_resealed_tei_mutations(
    verified_candidate: tuple[SourceManifest, CandidatePackage, object],
    tmp_path: Path,
    mutation: str,
) -> None:
    source, candidate, _ = verified_candidate
    target = tmp_path / mutation
    shutil.copytree(candidate.path, target)
    path = target / "content.tei.xml"
    tree = etree.parse(str(path))
    transcription = tree.xpath(
        "//tei:div[@type='parsed-xml-feature-transcription']", namespaces=TEI
    )[0]
    first, second = transcription[0], transcription[1]
    if mutation == "omission":
        transcription.remove(first)
    elif mutation == "duplication":
        duplicate = etree.fromstring(etree.tostring(first))
        duplicate.set(XML_ID, "invented-duplicate")
        transcription.append(duplicate)
    elif mutation == "reorder":
        transcription.remove(second)
        transcription.insert(0, second)
    elif mutation == "attribute-reorder":
        attributes = list(first.attrib.items())
        assert len(attributes) > 1
        first.attrib.clear()
        for name, value in reversed(attributes):
            first.set(name, value)
    elif mutation == "invention":
        etree.SubElement(
            transcription,
            f"{{{TEI['tei']}}}ab",
            type="source-xml-element",
            subtype="invented",
            n="0",
        )
    elif mutation == "metadata":
        tree.xpath("//tei:titleStmt/tei:title", namespaces=TEI)[
            0
        ].text = "Invented title"
    elif mutation == "rights":
        tree.xpath("//tei:availability", namespaces=TEI)[0].set("status", "free")
    elif mutation == "evidence":
        tree.xpath("//tei:note[@type='exact-retained-source-bytes']", namespaces=TEI)[
            0
        ].text = "aW52ZW50ZWQ="
    else:
        first.set("{urn:invented}qualified", "yes")
    path.write_bytes(
        etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=False)
    )
    mutated = _reseal(target, "content.tei.xml")
    with pytest.raises(ValueError, match="LIB-054"):
        validate(source, mutated, _oracle)


@pytest.mark.parametrize(
    "mutation",
    ["document-comment", "document-pi", "doctype", "xml-declaration", "namespace"],
)
def test_oracle_rejects_resealed_document_level_tei_mutations(
    verified_candidate: tuple[SourceManifest, CandidatePackage, object],
    tmp_path: Path,
    mutation: str,
) -> None:
    """Root-tree equality alone must not permit lexical document mutations."""
    source, candidate, _ = verified_candidate
    target = tmp_path / mutation
    shutil.copytree(candidate.path, target)
    member = target / "content.tei.xml"
    content = member.read_bytes()
    if mutation == "document-comment":
        content = content.replace(b"?>", b"?>\n<!--invented-document-comment-->", 1)
    elif mutation == "document-pi":
        content = content.replace(b"?>", b"?>\n<?invented document?>", 1)
    elif mutation == "doctype":
        content = content.replace(b"?>", b"?>\n<!DOCTYPE teiCorpus>", 1)
    elif mutation == "xml-declaration":
        content = content.replace(b"?>", b" standalone='yes'?>", 1)
    else:
        content = content.replace(
            b'xmlns:ns0="http://www.tei-c.org/ns/1.0"',
            b'xmlns:ns0="http://www.tei-c.org/ns/1.0" xmlns:invented="urn:invented"',
            1,
        )
    member.write_bytes(content)
    mutated = _reseal(target, "content.tei.xml")
    with pytest.raises(ValueError, match="LIB-054"):
        validate(source, mutated, _oracle)


@pytest.mark.parametrize(
    "mutation",
    [
        "status",
        "rights",
        "type",
        "extra",
        "stale",
        "comment",
        "pi",
        "doctype",
        "unresolved",
        "readme",
    ],
)
def test_oracle_rejects_resealed_evidence_mutations(
    verified_candidate: tuple[SourceManifest, CandidatePackage, object],
    tmp_path: Path,
    mutation: str,
) -> None:
    source, candidate, _ = verified_candidate
    target = tmp_path / mutation
    shutil.copytree(candidate.path, target)
    if mutation == "unresolved":
        member = "unresolved.jsonl"
        (target / member).write_bytes(b"")
    elif mutation == "readme":
        member = "README.source.md"
        (target / member).write_bytes(
            (target / member).read_bytes() + b"\nPublication ready.\n"
        )
    else:
        member = (
            "provenance.json"
            if mutation in {"status", "rights", "extra"}
            else "source-accountability.json"
        )
        value = json.loads((target / member).read_bytes())
        if mutation == "status":
            value["status"] = "accepted"
        elif mutation == "rights":
            value["rights"]["publication_authorized"] = True
        elif mutation == "type":
            value["source_bytes"] = True
        elif mutation == "extra":
            value["invented"] = "extra"
        elif mutation in {"comment", "pi", "doctype"}:
            event = next(
                item for item in value["non_element_events"] if item["kind"] == mutation
            )
            event["lexical"] += "invented"
        else:
            value["feature_count"] -= 1
        (target / member).write_bytes(_canonical(value))
    mutated = _reseal(target, member)
    with pytest.raises(ValueError, match="LIB-054"):
        validate(source, mutated, _oracle)


def test_candidate_manifest_stale_and_extra_member_are_rejected(
    verified_candidate: tuple[SourceManifest, CandidatePackage, object], tmp_path: Path
) -> None:
    _, candidate, _ = verified_candidate
    stale = tmp_path / "stale"
    shutil.copytree(candidate.path, stale)
    manifest = json.loads((stale / "manifest.json").read_bytes())
    manifest["source_id"] = "stale"
    (stale / "manifest.json").write_bytes(_canonical(manifest))
    loaded = CandidatePackage.load(stale)
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    with pytest.raises(ValueError, match="^candidate source manifest binding mismatch$"):
        validate(source, loaded, _oracle)
    extra = tmp_path / "extra"
    shutil.copytree(candidate.path, extra)
    (extra / "invented.txt").write_text("invented", encoding="utf-8")
    with pytest.raises(ValueError):
        CandidatePackage.load(extra)


def test_oracle_is_producer_independent_and_closure_pin_current() -> None:
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    policy = json.loads(source.authority_path("validation-policy").read_bytes())
    tree = ast.parse(
        (ROOT / "build/tei/ccel_puritan_lib054_oracle.py").read_text(encoding="utf-8")
    )
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "build.tei.ccel_puritan_lib054_reconstruction" not in imported
    assert "build.parsers.ccel_puritan_works" not in imported
    assert (
        _closure_digest(ROOT, policy)
        == source.record["validator"]["import_closure_sha256"]
    )


def test_oracle_closure_recursively_includes_and_pins_contract_drift(
    tmp_path: Path,
) -> None:
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    policy = json.loads(source.authority_path("validation-policy").read_bytes())
    closure = _closure(ROOT, policy)
    paths = {entry["path"] for entry in closure}
    contract = "ocd_kernel/reconstruction/contract.py"
    assert contract in paths
    replica = tmp_path / "closure-replica"
    for entry in closure:
        relative = Path(entry["path"])
        target = replica / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    before = _closure_digest(replica, policy)
    target = replica / contract
    target.write_bytes(target.read_bytes() + b"\n# LIB-054 closure drift probe\n")
    assert _closure_digest(replica, policy) != before


def test_oracle_rejects_stale_excluded_member_bytes(
    tmp_path: Path,
) -> None:
    """Excluded family members are source-accounted, not merely named."""
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    profile = json.loads(source.authority_path("reconstruction-profile").read_bytes())
    excluded = profile["excluded_members"]
    member = excluded[0]
    target = tmp_path / member["path"]
    target.parent.mkdir(parents=True)
    target.write_bytes(b"stale replacement")
    from build.tei.ccel_puritan_lib054_oracle import _assert_excluded_members

    with pytest.raises(ValueError, match="excluded authority"):
        _assert_excluded_members(tmp_path, [member])


def test_data_side_ccel_attribution_readme_is_present_and_exact() -> None:
    readme = ROOT / "data/structured-text/README.md"
    content = readme.read_text(encoding="utf-8")
    assert "Christian Classics Ethereal Library (CCEL)" in content
    assert "Do not sell CCEL files" in content
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    notice = source.authority_path("data-attribution-readme")
    assert "Do not sell CCEL files" in notice.read_text(encoding="utf-8")


def test_frozen_maps_routes_and_402_catalog_baseline(
    verified_candidate: tuple[SourceManifest, CandidatePackage, object], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, candidate, validation = verified_candidate
    from tests.test_runtime_manifest_binding_boundaries import allow_runtime_manifest_selection

    allow_runtime_manifest_selection(monkeypatch, MANIFEST)
    selection = {
        "source_manifest_allowlist": [MANIFEST.relative_to(ROOT).as_posix()],
        "data_resource_allowlist": [f"data/structured-text/{work_id}.json" for work_id in WORK_IDS],
    }
    work_map = (
        ROOT
        / "plans/2026-08-26-whole-library-faithful-tei-completion/02-work-ticket-map.md"
    ).read_text(encoding="utf-8")
    source_map = (
        ROOT
        / "plans/2026-08-26-whole-library-faithful-tei-completion/05-source-ticket-map.md"
    ).read_text(encoding="utf-8")
    for work_id, digest in zip(WORK_IDS, SOURCE_HASHES, strict=True):
        assert (
            sum(
                line.startswith(f"| `{work_id}` |") and "| LIB-054 |" in line
                for line in work_map.splitlines()
            )
            == 1
        )
        assert (
            f"| `{work_id}` | `sha256:{digest}` | LIB-054 | current-claim |"
            in source_map
        )
    assert _manifest_config_ids(source.record, ROOT) == set(WORK_IDS)
    assert _manifest_primary_hashes(source.record) == set(SOURCE_HASHES)
    record = {
        "contract": "ocd-validation-report-v1",
        "status": validation.status,
        "candidate_sha256": validation.candidate_sha256,
        "source_manifest_sha256": validation.source_manifest_sha256,
        "attestation": dict(validation.attestation),
        "findings": list(validation.findings),
        "report_sha256": validation.sha256,
    }
    validation_path = tmp_path / "validation.json"
    validation_path.write_bytes(_canonical(record))
    evidence = {
        (str(source.record["source_id"]), work_id): (candidate.path, validation_path)
        for work_id in WORK_IDS
    }
    catalog = collect_work_catalog(ROOT / "data", reconstruction_evidence=evidence, **selection)
    assert catalog.summary["work_units"] == len(WORK_IDS)
    by_id = {work["work_id"]: work for work in catalog.works}
    for work_id in WORK_IDS:
        state = by_id[work_id]["reconstruction_state"]
        routes = [
            route
            for route in state["routes"]
            if route["source_id"] == source.record["source_id"]
        ]
        assert len(routes) == 1
        assert routes[0]["association"] == "source_hash+exact_id"
        assert (
            routes[0]["candidate_verification"]
            == routes[0]["validation_verification"]
            == "verified"
        )
        assert state["human_review"] == "required"
        assert state["accepted_ir"] == "not_accepted"
        assert state["publication"] == "not_ready"


def test_two_fresh_processes_different_cwds_hashseeds_are_identical(
    tmp_path: Path,
) -> None:
    script = "from pathlib import Path;import hashlib,json,sys;from ocd_kernel.reconstruction import SourceManifest,reconstruct,validate;from build.tei.ccel_puritan_lib054_reconstruction import _convert;from build.tei.ccel_puritan_lib054_oracle import _oracle;root=Path(sys.argv[1]);s=SourceManifest.load(root/'tests/fixtures/reconstruction-runtime/puritan-lib054-ccel-puritan.source-manifest.json',repository_root=root);c=reconstruct(s,Path(sys.argv[2]),_convert);v=validate(s,c,_oracle);print(json.dumps({'candidate':c.sha256,'validation':v.sha256,'members':{n:hashlib.sha256(c.member_bytes(n)).hexdigest() for n in c.member_names}},sort_keys=True))"
    results = []
    for index, seed in enumerate(("17", "913"), 1):
        cwd = tmp_path / f"cwd-{index}"
        cwd.mkdir()
        destination = tmp_path / f"candidate-{index}"
        env = os.environ.copy()
        env["PYTHONHASHSEED"] = seed
        env["PYTHONPATH"] = str(ROOT)
        completed = subprocess.run(
            [sys.executable, "-c", script, str(ROOT), str(destination)],
            cwd=cwd,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        results.append(json.loads(completed.stdout))
    assert results[0] == results[1]
