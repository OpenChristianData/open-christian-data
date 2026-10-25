from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import MappingProxyType
from typing import Any

from lxml import etree
import jsonschema
import pytest

from build.tei.john_owen_lib051_oracle import (
    _closure_digest,
    _closure_paths,
    _oracle,
)
from build.tei.john_owen_lib051_reconstruction import _convert
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
SOURCE_DIR = ROOT / "sources/structured-text/lib051-john-owen"
MANIFEST = ROOT / 'tests/fixtures/reconstruction-runtime/puritan-lib051-john-owen.source-manifest.json'
TEI_NS = "http://www.tei-c.org/ns/1.0"
TEI = {"tei": TEI_NS}
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
WORK_IDS = (
    "john-owen-glory",
    "john-owen-grotius",
    "john-owen-indwelling-sin",
    "john-owen-justification",
    "john-owen-liturgies",
    "john-owen-mortification",
    "john-owen-pastors-people",
    "john-owen-perseverance",
    "john-owen-pneumatologia",
    "john-owen-psalm130",
)
SOURCE_HASHES = (
    "176f4e2d04fecc699129ff91cc886eba69761b05719a6ac740ceeb78243b2a11",
    "fcbacae9664b164da182195144c3fe3ea7157d83653117e01a272edec6518ce1",
    "d96a21545e33e34ec0cfb1af8f1fad92faa395082bd596ba44d7a1be7adaa6c5",
    "7b5b2a7ee95189a47aaba0364e242d80c09d83d955485761671a78472c86f942",
    "57fc24dab8facffc4bb82a3e39ee2372a97b1c55a0ef1851cfde69b3fbb5897c",
    "e3577b8e81583250a41df8b0bd6504dc37209a60944cbd5e20ec2ae82779c211",
    "dbe4984fd62de26c249ae366f9982353bb39727ea956fbf7c8c36f163cedac4b",
    "0d3bc041bdd6f1615b705ef8f336ece29c3636a42c69d04aebd5b231f75157a5",
    "ebbdf6e0de85a876456dc9fa7a2fd9da5e2b58f65a486b82fcc8b147e8b08d9a",
    "d2fc99719f83e550256d2c2e2edda7f09b6c70d3e399936b872551d7a5090444",
)


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


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


@pytest.fixture(scope="module")
def verified_candidate(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[SourceManifest, CandidatePackage, object]:
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    candidate = reconstruct(
        source, tmp_path_factory.mktemp("lib051-candidate") / "candidate", _convert
    )
    validation = validate(source, candidate, _oracle)
    return source, candidate, validation


def test_exact_ten_sources_complete_family_and_six_file_package(
    verified_candidate: tuple[SourceManifest, CandidatePackage, object],
) -> None:
    source, candidate, validation = verified_candidate
    assert validation.status == "pass"
    assert candidate.member_names == (
        "README.source.md",
        "content.tei.xml",
        "manifest.json",
        "provenance.json",
        "source-accountability.json",
        "unresolved.jsonl",
    )
    primary = [
        row for row in source.record["authorities"] if row["role"] == "primary-source"
    ]
    assert len(primary) == 10
    assert tuple(row["sha256"] for row in primary) == SOURCE_HASHES
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    family = accountability["adjacent_retained_member_accounting"]
    assert len(family) == 32
    assert sum(row["disposition"].startswith("included") for row in family) == 10
    assert sum(row["disposition"].startswith("excluded") for row in family) == 22
    assert accountability["total_node_count"] == 71_006
    by_path = {row["path"]: row for row in family}
    assert (
        "no frozen WorkCatalog or ticket-map identity"
        in by_path["raw/ccel/owen/poema.xml"]["disposition"]
    )
    works = accountability["works"]
    assert sum(row["node_kind_counts"]["comment"] for row in works) == 92
    assert sum(row["node_kind_counts"]["processing-instruction"] for row in works) == 6
    assert sum(row["metadata"]["ccel_copyright_comment_present"] for row in works) == 7


def test_every_retained_byte_and_complete_xml_node_record_is_in_tei(
    verified_candidate: tuple[SourceManifest, CandidatePackage, object],
) -> None:
    source, candidate, _ = verified_candidate
    tree = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    tei_works = tree.xpath("./tei:TEI", namespaces=TEI)
    assert tuple(item.get(XML_ID) for item in tei_works) == WORK_IDS
    profile = json.loads(source.authority_path("reconstruction-profile").read_bytes())
    by_id = {row["work_id"]: row for row in profile["works"]}
    all_node_kinds: set[str] = set()
    for tei in tei_works:
        work = by_id[tei.get(XML_ID)]
        raw = tei.xpath(
            ".//tei:ab[@type='exact-retained-source-bytes']", namespaces=TEI
        )
        nodes = tei.xpath(".//tei:ab[@type='source-xml-node']", namespaces=TEI)
        assert len(raw) == 1
        assert raw[0].get("n") == work["sha256"]
        assert len(nodes) > 0
        work_node_kinds = {json.loads(node.text)["kind"] for node in nodes}
        assert "element" in work_node_kinds
        all_node_kinds.update(work_node_kinds)
    assert all_node_kinds >= {"element", "comment", "processing-instruction"}


@pytest.mark.parametrize(
    "mutation",
    [
        "node-omission",
        "comment-omission",
        "pi-omission",
        "node-duplication",
        "node-reorder",
        "node-invention",
        "metadata-title",
        "publisher-responsibility-print-rights",
        "raw-byte-invention",
        "serialized-declaration",
        "namespace",
        "json-type",
        "status-and-rights-evidence",
    ],
)
def test_oracle_rejects_full_resealed_mutation_matrix(
    verified_candidate: tuple[SourceManifest, CandidatePackage, object],
    tmp_path: Path,
    mutation: str,
) -> None:
    source, candidate, _ = verified_candidate
    target = tmp_path / mutation
    shutil.copytree(candidate.path, target)
    if mutation in {"json-type", "status-and-rights-evidence"}:
        member_name = (
            "source-accountability.json"
            if mutation == "json-type"
            else "provenance.json"
        )
        path = target / member_name
        value = json.loads(path.read_bytes())
        if mutation == "json-type":
            value["total_node_count"] = True
        else:
            value["status"] = "accepted"
            value["rights"]["publication_ready"] = True
        path.write_bytes(_canonical(value))
    elif mutation == "serialized-declaration":
        member_name = "content.tei.xml"
        path = target / member_name
        path.write_bytes(path.read_bytes().replace(b"?>", b"?>\n", 1))
    else:
        member_name = "content.tei.xml"
        path = target / member_name
        tree = etree.parse(str(path))
        first_work = tree.xpath("./tei:TEI[1]", namespaces=TEI)[0]
        transcript = first_work.xpath(
            ".//tei:div[@type='complete-xml-node-transcription']", namespaces=TEI
        )[0]
        records = list(transcript)
        if mutation == "node-omission":
            transcript.remove(records[10])
        elif mutation in {"comment-omission", "pi-omission"}:
            kind = (
                "comment"
                if mutation.startswith("comment")
                else "processing-instruction"
            )
            selected = next(
                node
                for node in tree.xpath(
                    ".//tei:ab[@type='source-xml-node']", namespaces=TEI
                )
                if json.loads(node.text)["kind"] == kind
            )
            selected.getparent().remove(selected)
        elif mutation == "node-duplication":
            duplicate = deepcopy(records[10])
            duplicate.set(XML_ID, "invented-duplicate")
            transcript.append(duplicate)
        elif mutation == "node-reorder":
            transcript.remove(records[11])
            transcript.insert(10, records[11])
        elif mutation == "node-invention":
            invented = etree.SubElement(
                transcript,
                f"{{{TEI_NS}}}ab",
                type="source-xml-node",
                subtype="element",
                n="999999",
            )
            invented.set(XML_ID, "invented-node")
            invented.text = "{}"
        elif mutation == "metadata-title":
            first_work.xpath(
                "./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title", namespaces=TEI
            )[0].text = "Invented title"
        elif mutation == "publisher-responsibility-print-rights":
            first_work.xpath(".//tei:respStmt/tei:name", namespaces=TEI)[
                0
            ].text = "Invented responsibility"
            first_work.xpath(".//tei:sourceDesc//tei:publisher", namespaces=TEI)[
                0
            ].text = "Invented publisher"
            first_work.xpath(".//tei:note[@type='print-source']", namespaces=TEI)[
                0
            ].text = "Invented print source"
            first_work.xpath(".//tei:note[@type='rights']", namespaces=TEI)[
                0
            ].text = "Invented rights"
        elif mutation == "raw-byte-invention":
            first_work.xpath(
                ".//tei:ab[@type='exact-retained-source-bytes']", namespaces=TEI
            )[0].text += "QQ=="
        elif mutation == "namespace":
            records[10].tag = "ab"
        path.write_bytes(
            etree.tostring(
                tree, encoding="UTF-8", xml_declaration=True, pretty_print=False
            )
        )
    mutated = _reseal(target, member_name)
    with pytest.raises((ValueError, jsonschema.ValidationError)):
        validate(source, mutated, _oracle)


def test_manifest_extra_member_stale_binding_and_bound_authorities_fail_closed(
    verified_candidate: tuple[SourceManifest, CandidatePackage, object],
    tmp_path: Path,
) -> None:
    source, candidate, _ = verified_candidate
    for mutation in ("extra-member", "stale-source-binding"):
        target = tmp_path / mutation
        shutil.copytree(candidate.path, target)
        if mutation == "extra-member":
            (target / "extra.txt").write_text("invented", encoding="utf-8")
        else:
            manifest = json.loads((target / "manifest.json").read_bytes())
            manifest["source_manifest"]["sha256"] = "0" * 64
            (target / "manifest.json").write_bytes(_canonical(manifest))
        with pytest.raises(ValueError):
            mutated = CandidatePackage.load(target)
            validate(source, mutated, _oracle)
    policy = json.loads(source.authority_path("validation-policy").read_bytes())
    assert (
        _closure_digest(ROOT, policy)
        == source.record["validator"]["import_closure_sha256"]
    )
    authorities = {row["name"]: row for row in source.record["authorities"]}
    assert (
        authorities["reconstruction-profile"]["sha256"]
        != authorities["validation-policy"]["sha256"]
    )
    closure_paths = {
        path.relative_to(ROOT).as_posix() for path in _closure_paths(ROOT, policy)
    }
    assert {
        "build/tei/john_owen_lib051_oracle.py",
        "ocd_kernel/reconstruction/__init__.py",
        "ocd_kernel/reconstruction/contract.py",
    } <= closure_paths
    stale_record = json.loads(MANIFEST.read_bytes())
    stale_record["validator"]["import_closure_sha256"] = "0" * 64
    stale_source = replace(source, _record=_freeze(stale_record))
    with pytest.raises(ValueError, match="oracle import-closure binding mismatch"):
        validate(stale_source, candidate, _oracle)


def test_all_twenty_two_excluded_family_members_are_recomputed_from_raw_bytes(
    verified_candidate: tuple[SourceManifest, CandidatePackage, object],
) -> None:
    source, candidate, _ = verified_candidate
    profile = json.loads(source.authority_path("reconstruction-profile").read_bytes())
    excluded = [
        row
        for row in profile["adjacent_retained_member_accounting"]
        if row["disposition"].startswith("excluded")
    ]
    assert len(excluded) == 22
    for row in excluded:
        content = (ROOT / row["path"]).read_bytes()
        assert len(content) == row["bytes"]
        assert _sha(content) == row["sha256"]
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    assert (
        accountability["adjacent_retained_member_accounting"]
        == profile["adjacent_retained_member_accounting"]
    )


def test_ticket_maps_catalog_and_ten_exact_identity_routes(
    verified_candidate: tuple[SourceManifest, CandidatePackage, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
            sum(line.startswith(f"| `{work_id}` |") for line in work_map.splitlines())
            == 1
        )
        assert (
            f"| `{work_id}` | `sha256:{digest}` | LIB-051 | current-claim |"
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
        (source.record["source_id"], work_id): (candidate.path, validation_path)
        for work_id in WORK_IDS
    }
    catalog = collect_work_catalog(ROOT / "data", reconstruction_evidence=evidence, **selection)
    assert catalog.summary["work_units"] == len(WORK_IDS)
    by_id = {work["work_id"]: work for work in catalog.works}
    for work_id in WORK_IDS:
        state = by_id[work_id]["reconstruction_state"]
        routes = [
            item
            for item in state["routes"]
            if item["source_id"] == source.record["source_id"]
        ]
        assert len(routes) == 1
        route = routes[0]
        assert route["association"] == "source_hash+exact_id"
        assert route["scope"] == "work"
        assert (
            route["candidate_verification"]
            == route["validation_verification"]
            == "verified"
        )
        assert state["human_review"] == "required"
        assert state["accepted_ir"] == "not_accepted"
        assert state["publication"] == "not_ready"


def test_fresh_process_different_cwd_hashseed_package_bytes_are_exact(
    tmp_path: Path,
) -> None:
    script = (
        "from pathlib import Path;import hashlib,json,sys;"
        "from ocd_kernel.reconstruction import SourceManifest,reconstruct,validate;"
        "from build.tei.john_owen_lib051_reconstruction import _convert;"
        "from build.tei.john_owen_lib051_oracle import _oracle;"
        "r=Path(sys.argv[1]);d=Path(sys.argv[2]);"
        "s=SourceManifest.load(r/'tests/fixtures/reconstruction-runtime/puritan-lib051-john-owen.source-manifest.json',repository_root=r);"
        "c=reconstruct(s,d,_convert);v=validate(s,c,_oracle);"
        "print(json.dumps({'candidate':c.sha256,'members':{n:hashlib.sha256((d/n).read_bytes()).hexdigest() for n in c.member_names}},sort_keys=True))"
    )
    results = []
    for ordinal, seed in enumerate(("17", "913"), 1):
        cwd = tmp_path / f"cwd-{ordinal}"
        cwd.mkdir()
        destination = tmp_path / f"candidate-{ordinal}"
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
        results.append(json.loads(completed.stdout.strip()))
    assert results[0] == results[1]
    for name in CandidatePackage.load(tmp_path / "candidate-1").member_names:
        assert (tmp_path / "candidate-1" / name).read_bytes() == (
            tmp_path / "candidate-2" / name
        ).read_bytes()
