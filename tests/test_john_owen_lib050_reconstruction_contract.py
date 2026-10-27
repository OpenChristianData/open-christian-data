from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from lxml import etree
import jsonschema
import pytest

from tests.live_work_catalog_fixture import (
    _live_work_catalog_record, live_work_catalog, reuse_live_retained_witness_audit,
)

from build.tei.john_owen_lib050_oracle import _closure_digest, _oracle
from build.tei.john_owen_lib050_reconstruction import _convert
from build.tools.count_dataset_records import (
    _manifest_config_ids,
    _manifest_primary_hashes,
    collect_work_catalog,
)
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, reconstruct, validate


pytestmark = [pytest.mark.slow, pytest.mark.requires_local_artifacts]
ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "sources/structured-text/lib050-john-owen"
MANIFEST = SOURCE_DIR / "john-owen-lib050.source-manifest.json"
TEI_NS = "http://www.tei-c.org/ns/1.0"
TEI = {"tei": TEI_NS}
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
WORK_IDS = (
    "john-owen-apostasy",
    "john-owen-church-love",
    "john-owen-communion",
    "john-owen-conscience",
    "john-owen-death-of-death",
    "john-owen-display-arminianism",
    "john-owen-divine-justice",
    "john-owen-eshcol",
    "john-owen-evangelical-churches",
    "john-owen-faith-elect",
)
SOURCE_HASHES = (
    "434379f00e2337464f811b1962e9cd066770e83aac4871a80537fc01c8ea35cf",
    "cf6c515990bf310ad0acab8d1adb75a1595c6db0871ef7f924222014dc4b6f5d",
    "108a3b22374c03e1c382c65921e8135693e8197561f0db5ee91e0481fbdf27ec",
    "472e1fd7c0b3abfb9999369cbbe7d091026ef7f6cc314c3576476f787edcb836",
    "c76ae424be0caab02f3e829be21d580cb4c0a93fae0c8a7fe7dc4d5cdddaab22",
    "4e99940b8fc7da9fc0c7a3ae66b342cde56f102a68c0a0eb9026428938649082",
    "6bd7e642532e974b91835c50d64cca73d6ca9dbcb79940790612e0d90d2ea5b7",
    "edb9abc6649f5e4ec1e34e1ef05b0548fd93f48a7eb7f41795c39007fd022419",
    "fa7afc08f59e7298af01650dbe455afd2d145c8109fa55eeb17e0835f369c4c1",
    "4181f2b8411d153056a893be8c15cd0f85a12d31f8c4fe9194bc98de37d8a6aa",
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


@pytest.fixture(scope="module")
def verified_candidate(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[SourceManifest, CandidatePackage, object]:
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    candidate = reconstruct(
        source, tmp_path_factory.mktemp("lib050-candidate") / "candidate", _convert
    )
    validation = validate(source, candidate, _oracle)
    return source, candidate, validation


# Start the shared catalogue audit before the independent mutation matrix.
def test_ticket_maps_catalog_and_ten_exact_identity_routes(
    verified_candidate: tuple[SourceManifest, CandidatePackage, object],
    tmp_path: Path,
    live_work_catalog,
    reuse_live_retained_witness_audit,
) -> None:
    source, candidate, validation = verified_candidate
    work_map = (ROOT / "plans/2026-08-26-whole-library-faithful-tei-completion/02-work-ticket-map.md").read_text(encoding="utf-8")
    source_map = (ROOT / "plans/2026-08-26-whole-library-faithful-tei-completion/05-source-ticket-map.md").read_text(encoding="utf-8")
    for work_id, digest in zip(WORK_IDS, SOURCE_HASHES, strict=True):
        assert sum(line.startswith(f"| `{work_id}` |") for line in work_map.splitlines()) == 1
        assert f"| `{work_id}` | `sha256:{digest}` | LIB-050 | current-claim |" in source_map
    assert _manifest_config_ids(source.record, ROOT) == set(WORK_IDS)
    assert _manifest_primary_hashes(source.record) == set(SOURCE_HASHES)
    baseline = live_work_catalog
    baseline_unassociated = baseline.summary["reconstruction_state_counts"]["unassociated_manifests"]
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
    evidence = {(source.record["source_id"], work_id): (candidate.path, validation_path) for work_id in WORK_IDS}
    catalog = collect_work_catalog(ROOT / "data", reconstruction_evidence=evidence)
    assert catalog.summary["work_units"] == 402
    assert catalog.summary["reconstruction_state_counts"]["unassociated_manifests"] == baseline_unassociated
    by_id = {work["work_id"]: work for work in catalog.works}
    for work_id in WORK_IDS:
        state = by_id[work_id]["reconstruction_state"]
        routes = [item for item in state["routes"] if item["source_id"] == source.record["source_id"]]
        assert len(routes) == 1
        route = routes[0]
        assert route["association"] == "source_hash+exact_id"
        assert route["scope"] == "work"
        assert route["candidate_verification"] == route["validation_verification"] == "verified"
        assert state["human_review"] == "required"
        assert state["accepted_ir"] == "not_accepted"
        assert state["publication"] == "not_ready"


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
    primary = [row for row in source.record["authorities"] if row["role"] == "primary-source"]
    assert len(primary) == 10
    assert tuple(row["sha256"] for row in primary) == SOURCE_HASHES
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    family = accountability["adjacent_retained_member_accounting"]
    assert len(family) == 32
    assert sum(row["disposition"].startswith("included") for row in family) == 10
    assert sum(row["disposition"].startswith("excluded") for row in family) == 22
    assert accountability["total_node_count"] > 75_732
    by_path = {row["path"]: row for row in family}
    assert "no frozen WorkCatalog or ticket-map identity" in by_path[
        "raw/ccel/owen/poema.xml"
    ]["disposition"]
    works = accountability["works"]
    assert sum(row["node_kind_counts"]["comment"] for row in works) > 40
    assert sum(row["node_kind_counts"]["processing-instruction"] for row in works) == 4
    assert sum(row["metadata"]["ccel_copyright_comment_present"] for row in works) == 8


def test_native_readable_projection_preserves_communion_semantics(
    verified_candidate: tuple[SourceManifest, CandidatePackage, object],
) -> None:
    _source, candidate, _validation = verified_candidate
    root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    communion = root.xpath(
        "./tei:TEI[@xml:id='john-owen-communion']", namespaces=TEI
    )[0]
    readable = communion.xpath(
        "./tei:text/tei:body/tei:div/tei:div[@type='readable-transcription']",
        namespaces=TEI,
    )[0]
    assert readable.xpath(".//tei:date[@when='1657-07-10']", namespaces=TEI)
    sections = readable.xpath(".//tei:div[@type='source-division']", namespaces=TEI)
    assert {section.get("subtype") for section in sections} >= {"section"}
    notes = readable.xpath(".//tei:note[@type='source-note']", namespaces=TEI)
    assert len(notes) == 379
    assert {note.get("place") for note in notes} == {"foot"}
    assert {note.get("anchored") for note in notes} == {"true"}
    assert readable.xpath(
        ".//tei:seg[@type='source-span' and contains(@rend, 'small-caps')]",
        namespaces=TEI,
    )
    assert readable.xpath(
        ".//tei:ab[@type='scripture-context' and @subtype='kjv']",
        namespaces=TEI,
    )


@pytest.mark.parametrize(
    "mutation",
    ["native-paragraph-flattening", "note-wrong-parent", "note-content-swap"],
)
def test_oracle_rejects_communion_native_structure_mutations(
    verified_candidate: tuple[SourceManifest, CandidatePackage, object],
    tmp_path: Path,
    mutation: str,
) -> None:
    source, candidate, _validation = verified_candidate
    target = tmp_path / mutation
    shutil.copytree(candidate.path, target)
    tree = etree.parse(str(target / "content.tei.xml"))
    communion = tree.xpath(
        "/tei:teiCorpus/tei:TEI[@xml:id='john-owen-communion']",
        namespaces=TEI,
    )[0]
    readable = communion.xpath(
        "./tei:text/tei:body/tei:div/tei:div[@type='readable-transcription']",
        namespaces=TEI,
    )[0]
    if mutation == "native-paragraph-flattening":
        paragraph = readable.xpath(".//tei:p[@corresp][1]", namespaces=TEI)[0]
        paragraph.tag = f"{{{TEI_NS}}}ab"
    else:
        notes = readable.xpath(
            ".//tei:note[@type='source-note']", namespaces=TEI
        )
        assert len(notes) >= 2
        first, second = notes[:2]
        if mutation == "note-wrong-parent":
            first_parent = first.getparent()
            second_parent = second.getparent()
            assert first_parent is not second_parent
            first_parent.remove(first)
            second_parent.insert(0, first)
        else:
            first_text, second_text = first.text, second.text
            first.text, second.text = second_text, first_text
            first_children, second_children = list(first), list(second)
            for child in first_children:
                first.remove(child)
            for child in second_children:
                second.remove(child)
            for child in second_children:
                first.append(child)
            for child in first_children:
                second.append(child)
    mutated = etree.tostring(tree, encoding="UTF-8", xml_declaration=True)
    (target / "content.tei.xml").write_bytes(mutated)
    package = _reseal(target, "content.tei.xml")
    with pytest.raises(ValueError):
        validate(source, package, _oracle)


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
        raw = tei.xpath(".//tei:ab[@type='exact-retained-source-bytes']", namespaces=TEI)
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
        member_name = "source-accountability.json" if mutation == "json-type" else "provenance.json"
        path = target / member_name
        value = json.loads(path.read_bytes())
        if mutation == "json-type":
            value["total_node_count"] = True
        else:
            value["status"] = "accepted"
            value["rights"]["publication_ready"] = True
        path.write_bytes(_canonical(value))
    else:
        member_name = "content.tei.xml"
        path = target / member_name
        tree = etree.parse(str(path))
        first_work = tree.xpath("./tei:TEI[1]", namespaces=TEI)[0]
        transcript = first_work.xpath(".//tei:div[@type='complete-xml-node-transcription']", namespaces=TEI)[0]
        records = list(transcript)
        if mutation == "node-omission":
            transcript.remove(records[10])
        elif mutation in {"comment-omission", "pi-omission"}:
            kind = "comment" if mutation.startswith("comment") else "processing-instruction"
            selected = next(node for node in records if json.loads(node.text)["kind"] == kind)
            transcript.remove(selected)
        elif mutation == "node-duplication":
            duplicate = deepcopy(records[10])
            duplicate.set(XML_ID, "invented-duplicate")
            transcript.append(duplicate)
        elif mutation == "node-reorder":
            transcript.remove(records[11])
            transcript.insert(10, records[11])
        elif mutation == "node-invention":
            invented = etree.SubElement(transcript, f"{{{TEI_NS}}}ab", type="source-xml-node", subtype="element", n="999999")
            invented.set(XML_ID, "invented-node")
            invented.text = "{}"
        elif mutation == "metadata-title":
            first_work.xpath("./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title", namespaces=TEI)[0].text = "Invented title"
        elif mutation == "publisher-responsibility-print-rights":
            first_work.xpath(".//tei:respStmt/tei:name", namespaces=TEI)[0].text = "Invented responsibility"
            first_work.xpath(".//tei:sourceDesc//tei:publisher", namespaces=TEI)[0].text = "Invented publisher"
            first_work.xpath(".//tei:note[@type='print-source']", namespaces=TEI)[0].text = "Invented print source"
            first_work.xpath(".//tei:note[@type='rights']", namespaces=TEI)[0].text = "Invented rights"
        elif mutation == "raw-byte-invention":
            first_work.xpath(".//tei:ab[@type='exact-retained-source-bytes']", namespaces=TEI)[0].text += "QQ=="
        elif mutation == "namespace":
            records[10].tag = "ab"
        path.write_bytes(etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=False))
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
    assert _closure_digest(ROOT, policy) == source.record["validator"]["import_closure_sha256"]
    authorities = {row["name"]: row for row in source.record["authorities"]}
    assert authorities["reconstruction-profile"]["sha256"] != authorities["validation-policy"]["sha256"]




def test_fresh_process_different_cwd_hashseed_package_bytes_are_exact(tmp_path: Path) -> None:
    script = (
        "from pathlib import Path;import hashlib,json,sys;"
        "from ocd_kernel.reconstruction import SourceManifest,reconstruct,validate;"
        "from build.tei.john_owen_lib050_reconstruction import _convert;"
        "from build.tei.john_owen_lib050_oracle import _oracle;"
        "r=Path(sys.argv[1]);d=Path(sys.argv[2]);"
        "s=SourceManifest.load(r/'sources/structured-text/lib050-john-owen/john-owen-lib050.source-manifest.json',repository_root=r);"
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
        completed = subprocess.run([sys.executable, "-c", script, str(ROOT), str(destination)], cwd=cwd, env=env, text=True, capture_output=True, check=True)
        results.append(json.loads(completed.stdout.strip()))
    assert results[0] == results[1]
    for name in CandidatePackage.load(tmp_path / "candidate-1").member_names:
        assert (tmp_path / "candidate-1" / name).read_bytes() == (tmp_path / "candidate-2" / name).read_bytes()
