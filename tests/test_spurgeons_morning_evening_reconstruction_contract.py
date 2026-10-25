from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Iterator

from lxml import etree
import pytest

from build.tei.lib030_oracle import _oracle
from build.tei.lib030_reconstruction import _convert, _parse, _validate_source_shape
from ocd_kernel.reconstruction import (
    CandidatePackage,
    SourceManifest,
    prepare_review,
    reconstruct,
    validate,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE_MANIFEST = ROOT / 'tests/fixtures/reconstruction-runtime/puritan-spurgeons-morning-evening.source-manifest.json'
RETAINED_RAW_ROOT = Path(
    os.environ.get("OCD_RETAINED_RAW_ROOT", r"D:\Library\Open Christian Data\raw")
)
RETAINED_SOURCE = RETAINED_RAW_ROOT / "ccel/spurgeon/morneve.xml"
EXPECTED_MEMBERS = {
    "manifest.json",
    "content.tei.xml",
    "source-accountability.json",
    "provenance.json",
    "unresolved.jsonl",
    "README.source.md",
}
TEI_NS = "http://www.tei-c.org/ns/1.0"
NS = {"tei": TEI_NS, "xml": "http://www.w3.org/XML/1998/namespace"}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(record: object) -> bytes:
    return (
        json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _reseal_member(candidate_path: Path, name: str, content: bytes) -> None:
    (candidate_path / name).write_bytes(content)
    manifest = json.loads((candidate_path / "manifest.json").read_bytes())
    member = next(item for item in manifest["members"] if item["name"] == name)
    member.update(bytes=len(content), sha256=_sha(content))
    (candidate_path / "manifest.json").write_bytes(_canonical(manifest))


@contextmanager
def _candidate_copy(candidate: CandidatePackage, destination: Path) -> Iterator[Path]:
    shutil.copytree(candidate.path, destination)
    try:
        yield destination
    finally:
        shutil.rmtree(destination)


@pytest.fixture(scope="module")
def lib030_evidence(tmp_path_factory: pytest.TempPathFactory):
    if not RETAINED_SOURCE.is_file():
        pytest.skip(f"durable retained source is unavailable: {RETAINED_SOURCE}")
    previous = os.environ.get("OCD_RETAINED_RAW_ROOT")
    os.environ["OCD_RETAINED_RAW_ROOT"] = str(RETAINED_RAW_ROOT)
    try:
        source = SourceManifest.load(SOURCE_MANIFEST, repository_root=ROOT)
        candidate = reconstruct(
            source,
            tmp_path_factory.mktemp("lib030-contract") / "candidate",
            _convert,
        )
        report = validate(source, candidate, _oracle)
        yield source, candidate, report
    finally:
        if previous is None:
            os.environ.pop("OCD_RETAINED_RAW_ROOT", None)
        else:
            os.environ["OCD_RETAINED_RAW_ROOT"] = previous


def test_lib030_candidate_accounts_for_the_complete_retained_document(
    lib030_evidence,
) -> None:
    source, candidate, report = lib030_evidence
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    document = accountability["document_accounting"][0]
    crosswalk = accountability["crosswalk"]
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    unresolved = [
        json.loads(line)
        for line in candidate.member_bytes("unresolved.jsonl").splitlines()
    ]

    assert set(candidate.member_names) == EXPECTED_MEMBERS
    assert candidate.manifest["status"] == "nonaccepted"
    assert accountability["contract"] == "ocd-lib030-source-accountability-v3"
    assert accountability["work_count"] == 1
    assert accountability["node_count"] == 13_824
    assert accountability["attribute_count"] == 27_125
    assert accountability["internal_source_reference_count"] == 2_591
    assert accountability["duplicate_id_reference_count"] == 2_564
    assert len(crosswalk) == accountability["node_count"]
    assert [row["ordinal"] for row in crosswalk] == list(range(1, 13_825))
    assert len({row["source_selector"] for row in crosswalk}) == 13_824
    assert all(row.get("disposition") for row in crosswalk)
    assert all(row.get("tei_targets") for row in crosswalk)
    assert {
        accountability["omitted_node_count"],
        accountability["duplicate_node_count"],
        accountability["invented_node_count"],
        accountability["unresolved_node_count"],
    } == {0}

    assert document["node_kind_counts"] == {
        "element": 13_821,
        "comment": 3,
        "processing-instruction": 0,
    }
    assert document["head_node_count"] == 73
    assert document["body_node_count"] == 13_747
    assert document["body_projection_node_count"] == 13_746
    assert document["source_xml_id_occurrence_count"] == 9_178
    assert document["source_xml_id_unique_count"] == 8_444
    assert document["source_duplicate_xml_id_value_count"] == 734
    assert document["source_duplicate_xml_id_extra_occurrence_count"] == 734
    assert document["internal_source_reference_count"] == 2_591
    assert document["duplicate_id_reference_count"] == 2_564
    assert document["semantic_index_container_count"] == 2
    assert document["centered_front_matter_container_count"] == 1
    envelope = document["document_envelope"]
    assert envelope["covered_bytes"] == 2_136_777
    assert envelope["carrier_count"] == 11
    assert [row["kind"] for row in envelope["carriers"]] == [
        "xml-declaration",
        "padding",
        "doctype",
        "padding",
        "comment",
        "padding",
        "comment",
        "padding",
        "comment",
        "padding",
        "padding",
    ]

    assert provenance["status"] == "nonaccepted"
    assert provenance["publication_state"] == "not_ready"
    assert provenance["canonical_data_written"] is False
    assert provenance["canonical_ir_written"] is False
    assert provenance["source_document_metadata"]["rights"]
    assert len(provenance["source_document_metadata"]["styles"]) == 2
    assert [item["scope"] for item in unresolved] == [
        ["spurgeons-morning-evening"],
        ["spurgeons-morning-evening"],
    ]
    readme = candidate.member_bytes("README.source.md")
    assert b"Christian Classics Ethereal Library" in readme
    assert b"Steve Liguori" in readme
    assert report.status == "pass"
    assert report.findings == ()
    review = prepare_review(source, candidate, report)
    assert review.candidate_sha256 == candidate.sha256


def test_lib030_tei_is_readable_semantic_and_preserves_outer_source_material(
    lib030_evidence,
) -> None:
    _source, candidate, _report = lib030_evidence
    tei = etree.fromstring(candidate.member_bytes("content.tei.xml"))

    assert tei.tag == f"{{{TEI_NS}}}TEI"
    assert len(tei.xpath("/tei:TEI/tei:teiHeader", namespaces=NS)) == 1
    assert len(tei.xpath("/tei:TEI/tei:text/tei:front", namespaces=NS)) == 1
    assert len(tei.xpath("/tei:TEI/tei:text/tei:body", namespaces=NS)) == 1
    assert len(tei.xpath('//tei:div[@type="work"]', namespaces=NS)) == 1
    assert len(tei.xpath('//tei:note[@type="pre-root-comment"]', namespaces=NS)) == 3
    assert len(tei.xpath('//tei:ab[@type="xml-declaration"]', namespaces=NS)) == 1
    assert len(tei.xpath('//tei:ab[@type="doctype"]', namespaces=NS)) == 1
    transcription = tei.xpath(
        '//tei:ab[@type="exact-parsed-thml-head-xml"]', namespaces=NS
    )[0]
    assert "<ThML.head>" in transcription.text
    assert "DC.Rights" in transcription.text
    assert "revisionHistory" in transcription.text
    assert len(
        tei.xpath('//tei:milestone[@unit="scripture-comment"]', namespaces=NS)
    ) == 736
    assert len(tei.xpath("//tei:index[@indexName]", namespaces=NS)) == 2
    assert len(tei.xpath('//tei:div[@type="index"]', namespaces=NS)) == 2
    assert len(
        tei.xpath('//tei:div[@type="centered-front-matter"]', namespaces=NS)
    ) == 1
    assert not tei.xpath('//tei:quote', namespaces=NS)
    assert len(
        tei.xpath(
            '//*[@xml:id][starts-with(@xml:id,"lib030-node-")]',
            namespaces=NS,
        )
    ) == 13_746


def test_lib030_index_containers_and_every_duplicate_reference_are_exact(
    lib030_evidence,
) -> None:
    _source, candidate, _report = lib030_evidence
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    crosswalk = accountability["crosswalk"]
    tei = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    targets = {
        node.get("{http://www.w3.org/XML/1998/namespace}id"): node
        for node in tei.xpath('//*[@xml:id]', namespaces=NS)
    }
    source_id_occurrences: dict[str, list[str]] = {}
    for row in crosswalk:
        attributes = dict(row["attributes"])
        if attributes.get("id"):
            source_id_occurrences.setdefault(attributes["id"], []).append(
                row["feature_id"]
            )
    duplicate_ids = {
        source_id
        for source_id, occurrences in source_id_occurrences.items()
        if len(occurrences) > 1
    }
    first_targets = {
        source_id: occurrences[0]
        for source_id, occurrences in source_id_occurrences.items()
    }
    internal_references = []
    duplicate_references = []
    for row in crosswalk:
        attributes = dict(row["attributes"])
        for name in ("href", "prev", "next"):
            value = attributes.get(name)
            normalized = value[1:] if value and value.startswith("#") else value
            if normalized not in first_targets:
                continue
            record = (row, name, normalized)
            internal_references.append(record)
            if normalized in duplicate_ids:
                duplicate_references.append(record)
            target_attribute = "target" if name == "href" else name
            assert targets[row["feature_id"]].get(target_attribute) == (
                f"#{first_targets[normalized]}"
            )

    assert len(duplicate_ids) == 734
    assert len(internal_references) == 2_591
    assert len(duplicate_references) == 2_564
    assert {item[2] for item in duplicate_references} == duplicate_ids
    index_rows = [
        row
        for row in crosswalk
        if row["source_tag"] == "div"
        and dict(row["attributes"]).get("class") == "Index"
    ]
    assert [row["source_selector"] for row in index_rows] == [
        "/ThML[1]/ThML.body[1]/div1[14]/div2[1]/div[1]",
        "/ThML[1]/ThML.body[1]/div1[14]/div2[2]/div[1]",
    ]
    assert all(targets[row["feature_id"]].get("type") == "index" for row in index_rows)


def test_lib030_reconstruction_is_deterministic_across_process_and_cwd(
    tmp_path: Path,
) -> None:
    if not RETAINED_SOURCE.is_file():
        pytest.skip(f"durable retained source is unavailable: {RETAINED_SOURCE}")
    other_cwd = tmp_path / "different-cwd"
    other_cwd.mkdir()
    first = tmp_path / "first"
    second = tmp_path / "second"
    script = (
        "from pathlib import Path; import hashlib,sys; "
        "from ocd_kernel.reconstruction import SourceManifest,reconstruct; "
        "from build.tei.lib030_reconstruction import _convert; "
        f"root=Path({str(ROOT)!r}); "
        f"manifest=SourceManifest.load(root/{str(SOURCE_MANIFEST.relative_to(ROOT))!r}, repository_root=root); "
        "candidate=reconstruct(manifest,Path(sys.argv[1]),_convert); "
        "print('|'.join(name+':'+hashlib.sha256(candidate.member_bytes(name)).hexdigest() "
        "for name in candidate.member_names))"
    )
    environment = os.environ.copy()
    environment["OCD_RETAINED_RAW_ROOT"] = str(RETAINED_RAW_ROOT)
    environment["PYTHONPATH"] = str(ROOT)
    try:
        first_run = subprocess.run(
            [sys.executable, "-B", "-c", script, str(first)],
            cwd=ROOT,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        second_run = subprocess.run(
            [sys.executable, "-B", "-c", script, str(second)],
            cwd=other_cwd,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert first_run.stdout == second_run.stdout
        assert {
            item.name: item.read_bytes() for item in first.iterdir() if item.is_file()
        } == {
            item.name: item.read_bytes() for item in second.iterdir() if item.is_file()
        }
    finally:
        for path in (first, second):
            if path.is_dir():
                shutil.rmtree(path)


def _mutate_candidate(path: Path, mutation: str) -> None:
    if mutation.startswith("tei-"):
        tree = etree.fromstring((path / "content.tei.xml").read_bytes())
        paragraphs = tree.xpath('//tei:div[@type="work"]//tei:p', namespaces=NS)
        if mutation == "tei-omit-node":
            paragraphs[0].getparent().remove(paragraphs[0])
        elif mutation == "tei-duplicate-node":
            duplicate = deepcopy(paragraphs[0])
            duplicate.set(
                "{http://www.w3.org/XML/1998/namespace}id",
                "lib030-node-invented-duplicate",
            )
            paragraphs[0].addnext(duplicate)
        elif mutation == "tei-reorder-siblings":
            siblings = tree.xpath(
                '//tei:div[@type="thml-div2"][count(tei:p) >= 2][1]/tei:p',
                namespaces=NS,
            )
            parent = siblings[0].getparent()
            parent.remove(siblings[1])
            parent.insert(0, siblings[1])
        elif mutation == "tei-misattach-node":
            target = tree.xpath('//tei:div[@type="thml-div2"]', namespaces=NS)[1]
            paragraphs[0].getparent().remove(paragraphs[0])
            target.append(paragraphs[0])
        elif mutation == "tei-invent-back":
            text = tree.find(f"{{{TEI_NS}}}text")
            assert text is not None
            text.append(etree.Element(f"{{{TEI_NS}}}back"))
        elif mutation == "tei-pre-root-comment":
            note = tree.xpath('//tei:note[@type="pre-root-comment"]', namespaces=NS)[0]
            note.text = (note.text or "") + " changed"
        elif mutation == "tei-source-head":
            ab = tree.xpath(
                '//tei:ab[@type="exact-parsed-thml-head-xml"]', namespaces=NS
            )[0]
            ab.text = (ab.text or "").replace("DC.Rights", "DC.Wrongs", 1)
        elif mutation == "tei-internal-ref-target":
            node = tree.xpath(
                '//tei:ref[starts-with(@target,"#")][@xml:id]', namespaces=NS
            )[0]
            node.set("target", "#lib030-node-000001")
        elif mutation == "tei-scripture-ref-target":
            node = tree.xpath('//tei:ref[@type="scripture"]', namespaces=NS)[0]
            node.set("target", "Bible:Invented.1.1")
        elif mutation == "tei-ref-tag":
            node = tree.xpath('//tei:ref[@xml:id]', namespaces=NS)[0]
            node.tag = f"{{{TEI_NS}}}seg"
        elif mutation == "tei-scripture-comment-unit":
            node = tree.xpath(
                '//tei:milestone[@unit="scripture-comment"]', namespaces=NS
            )[0]
            node.set("unit", "commentary")
        elif mutation == "tei-sync-n":
            node = tree.xpath(
                '//tei:milestone[not(@unit="scripture-comment") and '
                'not(@unit="horizontal-rule")]',
                namespaces=NS,
            )[0]
            node.set("n", (node.get("n") or "") + "-changed")
        elif mutation == "tei-horizontal-rule-unit":
            node = tree.xpath(
                '//tei:milestone[@unit="horizontal-rule"]', namespaces=NS
            )[0]
            node.set("unit", "rule")
        elif mutation == "tei-hi-rend":
            node = tree.xpath('//tei:hi[@xml:id]', namespaces=NS)[0]
            node.set("rend", "bold")
        elif mutation == "tei-index-name":
            node = tree.xpath('//tei:index[@indexName]', namespaces=NS)[0]
            node.set("indexName", "changed")
        elif mutation == "tei-line-text":
            node = tree.xpath('//tei:l[@xml:id]', namespaces=NS)[0]
            node.text = (node.text or "") + " changed"
        elif mutation == "tei-line-group-tag":
            node = tree.xpath('//tei:lg[@xml:id]', namespaces=NS)[0]
            node.tag = f"{{{TEI_NS}}}div"
        elif mutation == "tei-segment-type":
            node = tree.xpath('//tei:seg[@xml:id]', namespaces=NS)[0]
            node.set("type", "changed")
        elif mutation == "tei-division-type":
            node = tree.xpath('//tei:div[@type="thml-div1"]', namespaces=NS)[0]
            node.set("type", "changed")
        elif mutation == "tei-index-container-quote":
            node = tree.xpath('//tei:div[@type="index"]', namespaces=NS)[0]
            node.tag = f"{{{TEI_NS}}}quote"
            node.set("type", "quotation")
        elif mutation == "tei-centered-container-type":
            node = tree.xpath(
                '//tei:div[@type="centered-front-matter"]', namespaces=NS
            )[0]
            node.set("type", "quotation")
        elif mutation == "tei-heading-tag":
            node = tree.xpath('//tei:head[@xml:id]', namespaces=NS)[0]
            node.tag = f"{{{TEI_NS}}}p"
        elif mutation == "tei-source-attribute-n":
            node = tree.xpath('//tei:body//*[@xml:id][@n]', namespaces=NS)[0]
            node.set("n", (node.get("n") or "") + "-changed")
        elif mutation == "tei-direct-body-text":
            node = tree.xpath('//tei:p[@xml:id][normalize-space(text())]', namespaces=NS)[0]
            node.text = (node.text or "") + " changed"
        elif mutation == "tei-tail-body-text":
            node = next(
                item
                for item in tree.xpath('//*[@xml:id]', namespaces=NS)
                if (item.tail or "").strip()
            )
            node.tail = (node.tail or "") + " changed"
        elif mutation == "tei-all-duplicate-reference-targets":
            accountability = json.loads(
                (path / "source-accountability.json").read_bytes()
            )
            occurrences: dict[str, list[str]] = {}
            for row in accountability["crosswalk"]:
                attributes = dict(row["attributes"])
                if attributes.get("id"):
                    occurrences.setdefault(attributes["id"], []).append(
                        row["feature_id"]
                    )
            duplicates = {
                source_id: feature_ids
                for source_id, feature_ids in occurrences.items()
                if len(feature_ids) > 1
            }
            targets = {
                node.get("{http://www.w3.org/XML/1998/namespace}id"): node
                for node in tree.xpath('//*[@xml:id]', namespaces=NS)
            }
            changed = 0
            referenced_duplicate_ids: set[str] = set()
            for row in accountability["crosswalk"]:
                for name, value in row["attributes"]:
                    if name not in {"href", "prev", "next"}:
                        continue
                    normalized = value[1:] if value.startswith("#") else value
                    if normalized not in duplicates:
                        continue
                    target_attribute = "target" if name == "href" else name
                    targets[row["feature_id"]].set(
                        target_attribute,
                        f"#{duplicates[normalized][1]}",
                    )
                    changed += 1
                    referenced_duplicate_ids.add(normalized)
            assert changed == 2_564
            assert len(referenced_duplicate_ids) == 734
        else:
            raise AssertionError(f"unknown TEI mutation: {mutation}")
        _reseal_member(
            path,
            "content.tei.xml",
            etree.tostring(tree, encoding="UTF-8", xml_declaration=True),
        )
        return

    if mutation.startswith("accountability-"):
        name = "source-accountability.json"
        record = json.loads((path / name).read_bytes())
        if mutation == "accountability-crosswalk":
            record["crosswalk"][100]["source_payload_sha256"] = "0" * 64
        elif mutation == "accountability-envelope":
            record["document_accounting"][0]["document_envelope"]["carriers"][0][
                "text"
            ] = '<?xml version="1.1" encoding="UTF-8"?>'
        elif mutation == "accountability-duplicate-target":
            record["crosswalk"][101]["tei_targets"] = record["crosswalk"][100][
                "tei_targets"
            ]
        else:
            raise AssertionError(f"unknown accountability mutation: {mutation}")
        _reseal_member(path, name, _canonical(record))
        return

    if mutation.startswith("provenance-"):
        name = "provenance.json"
        record = json.loads((path / name).read_bytes())
        if mutation == "provenance-rights":
            record["rights"]["worldwide_rights_decision"] = "cleared"
        elif mutation == "provenance-style":
            record["source_document_metadata"]["styles"][0]["text"] += " changed"
        else:
            raise AssertionError(f"unknown provenance mutation: {mutation}")
        _reseal_member(path, name, _canonical(record))
        return

    if mutation == "unresolved-scope":
        name = "unresolved.jsonl"
        records = [json.loads(line) for line in (path / name).read_bytes().splitlines()]
        records[0]["scope"] = ["all-ten-works"]
        _reseal_member(path, name, b"".join(_canonical(item) for item in records))
        return
    if mutation == "attribution":
        name = "README.source.md"
        _reseal_member(path, name, (path / name).read_bytes() + b"changed\n")
        return
    if mutation == "candidate-source-binding":
        manifest = json.loads((path / "manifest.json").read_bytes())
        manifest["source_manifest"]["sha256"] = "0" * 64
        (path / "manifest.json").write_bytes(_canonical(manifest))
        return
    if mutation == "candidate-status":
        manifest = json.loads((path / "manifest.json").read_bytes())
        manifest["status"] = "accepted"
        (path / "manifest.json").write_bytes(_canonical(manifest))
        return
    raise AssertionError(f"unknown mutation: {mutation}")


@pytest.mark.parametrize(
    "mutation",
    [
        "tei-omit-node",
        "tei-duplicate-node",
        "tei-reorder-siblings",
        "tei-misattach-node",
        "tei-invent-back",
        "tei-pre-root-comment",
        "tei-source-head",
        "tei-internal-ref-target",
        "tei-scripture-ref-target",
        "tei-ref-tag",
        "tei-scripture-comment-unit",
        "tei-sync-n",
        "tei-horizontal-rule-unit",
        "tei-hi-rend",
        "tei-index-name",
        "tei-line-text",
        "tei-line-group-tag",
        "tei-segment-type",
        "tei-division-type",
        "tei-index-container-quote",
        "tei-centered-container-type",
        "tei-heading-tag",
        "tei-source-attribute-n",
        "tei-direct-body-text",
        "tei-tail-body-text",
        "tei-all-duplicate-reference-targets",
        "accountability-crosswalk",
        "accountability-envelope",
        "accountability-duplicate-target",
        "provenance-rights",
        "provenance-style",
        "unresolved-scope",
        "attribution",
        "candidate-source-binding",
        "candidate-status",
    ],
)
def test_lib030_oracle_rejects_resealed_mutations(
    lib030_evidence,
    tmp_path: Path,
    mutation: str,
) -> None:
    source, candidate, _report = lib030_evidence
    with _candidate_copy(candidate, tmp_path / mutation) as path:
        _mutate_candidate(path, mutation)
        mutated = CandidatePackage.load(path)
        with pytest.raises(ValueError):
            _oracle(source, mutated)


def test_lib030_converter_fails_closed_on_unsupported_source_feature() -> None:
    if not RETAINED_SOURCE.is_file():
        pytest.skip(f"durable retained source is unavailable: {RETAINED_SOURCE}")
    tree = _parse(RETAINED_SOURCE.read_bytes())
    _head, body = _validate_source_shape(tree)
    body.append(etree.Element("table"))

    with pytest.raises(ValueError, match="unsupported ThML.body elements"):
        _validate_source_shape(tree)
