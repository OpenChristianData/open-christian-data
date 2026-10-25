"""Bounded LIB-053 route, source accounting, and resealed fidelity challenges."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from xml.etree import ElementTree as StdET

from lxml import etree
import pytest

from build.tei.john_owen_lib053_oracle import _oracle, _verify_family_census
from build.tei.john_owen_lib053_reconstruction import reconstruct_candidate
from build.tools.count_dataset_records import _manifest_primary_hashes
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'tests/fixtures/reconstruction-runtime/puritan-lib053-john-owen.source-manifest.json'
NS = {"t": "http://www.tei-c.org/ns/1.0"}
pytestmark = pytest.mark.requires_local_artifacts


@pytest.fixture(scope="module")
def verified(tmp_path_factory):
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    package = reconstruct_candidate(
        source, tmp_path_factory.mktemp("lib053") / "package"
    )
    report = validate(source, package, _oracle)
    assert report.status == "pass", report.findings
    return source, package


def test_complete_source_accounting_and_exact_route(verified):
    source, package = verified
    assert source.record["work_id"] == "john-owen-worship"
    assert _manifest_primary_hashes(source.record) == {
        "88c1fee9f8907222dbef6bcc4fa9bed469b72d8c445bb9a605403af62829e1d3"
    }
    account = json.loads(package.member_bytes("source-accountability.json"))
    assert account["assigned_work_count"] == account["included_member_count"] == 1
    assert account["adjacent_member_count"] == 31
    assert account["total_node_count"] == 7508
    assert account["works"][0]["work_id"] == "john-owen-worship"
    assert account["works"][0]["node_kind_counts"] == {
        "element": 7506,
        "comment": 2,
        "processing-instruction": 0,
    }
    family = account["adjacent_retained_member_accounting"]
    assert len(family) == 32
    assert [r["path"] for r in family if r["disposition"].startswith("included:")] == [
        "raw/ccel/owen/worship.xml"
    ]
    tree = etree.fromstring(package.member_bytes("content.tei.xml"))
    readable = tree.xpath("//t:div[@type='readable-transcription']", namespaces=NS)[0]
    assert len(readable) == 5
    assert len(readable.xpath(".//t:pb", namespaces=NS)) == 86
    assert len(readable.xpath(".//t:p[@rend='italic']", namespaces=NS)) == 53
    assert len(readable.xpath(".//t:ab[@subtype='h4']", namespaces=NS)) == 2
    assert len(readable.xpath(".//t:ref[@type='scripture']", namespaces=NS)) == 1054
    assert (
        "Proof-read and ThML markup added."
        in package.member_bytes("provenance.json").decode()
    )


def test_catalog_title_is_not_inserted_before_source_body(verified):
    source, package = verified
    primary = next(
        authority
        for authority in source.record["authorities"]
        if authority["role"] == "primary-source"
    )
    source_root = StdET.parse(ROOT / primary["path"]).getroot()
    source_body = next(node for node in source_root.iter() if node.tag == "ThML.body")
    first_source_heading = next(node for node in source_body.iter() if node.tag == "h2")
    expected_leading_text = "".join(first_source_heading.itertext())

    candidate = etree.fromstring(package.member_bytes("content.tei.xml"))
    member = candidate.xpath(
        "//t:div[@type='retained-source-member']", namespaces=NS
    )[0]
    assert len(member) == 2
    readable = member[0]
    assert readable.get("type") == "readable-transcription"
    assert "".join(readable.itertext()).lstrip().startswith(expected_leading_text)


def test_question_prompts_have_unique_readable_ids_and_source_correspondence(verified):
    _, package = verified
    candidate = etree.fromstring(package.member_bytes("content.tei.xml"))
    questions = candidate.xpath(
        "//t:div[@type='readable-transcription']//t:p[@rend='italic']",
        namespaces=NS,
    )

    assert len(questions) == 53
    readable_ids = [question.get("{http://www.w3.org/XML/1998/namespace}id") for question in questions]
    assert all(readable_ids)
    assert len(readable_ids) == len(set(readable_ids))
    assert readable_ids == [
        "readable-" + question.get("corresp", "")[1:]
        for question in questions
    ]


def test_package_node_accounting_matches_independent_stdlib_source_census(verified):
    source, package = verified
    primary = [
        authority
        for authority in source.record["authorities"]
        if authority["role"] == "primary-source"
    ]
    assert len(primary) == 1

    source_path = ROOT / primary[0]["path"]
    source_counts = {
        "element": 0,
        "comment": 0,
        "processing-instruction": 0,
    }
    event_to_kind = {
        "start": "element",
        "comment": "comment",
        "pi": "processing-instruction",
    }
    with source_path.open("rb") as stream:
        for event, _node in StdET.iterparse(stream, events=("start", "comment", "pi")):
            source_counts[event_to_kind[event]] += 1

    accounting = json.loads(package.member_bytes("source-accountability.json"))
    work_account = accounting["works"][0]
    assert source_counts == work_account["node_kind_counts"]
    assert sum(source_counts.values()) == work_account["node_count"]
    assert work_account["node_count"] == accounting["total_node_count"]


@pytest.mark.parametrize(
    "mutation",
    [
        "omit-index",
        "duplicate-division",
        "reorder",
        "invent",
        "reference",
        "question-style",
        "heading",
        "accounting",
        "rights",
        "trailing",
    ],
)
def test_resealed_mutations_rejected(verified, tmp_path, mutation):
    source, package = verified
    target = tmp_path / "mutant"
    shutil.copytree(package.path, target)
    try:
        member = "content.tei.xml"
        if mutation in {"accounting", "rights"}:
            member = (
                "source-accountability.json"
                if mutation == "accounting"
                else "provenance.json"
            )
            record = json.loads((target / member).read_bytes())
            if mutation == "accounting":
                record["total_node_count"] -= 1
            else:
                record["status"] = "accepted"
            payload = (
                json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
            ).encode()
        else:
            tree = etree.fromstring(package.member_bytes(member))
            body = tree.xpath("//t:div[@type='readable-transcription']", namespaces=NS)[
                0
            ]
            if mutation == "omit-index":
                body.remove(body[-1])
            elif mutation == "duplicate-division":
                body.append(deepcopy(body[-1]))
            elif mutation == "reorder":
                body.insert(0, body[-1])
            elif mutation == "invent":
                body[0].text = "Invented text"
            elif mutation == "reference":
                body.xpath(".//t:ref[@target]", namespaces=NS)[0].set(
                    "target", "#wrong"
                )
            elif mutation == "question-style":
                del body.xpath(".//t:p[@rend='italic']", namespaces=NS)[0].attrib[
                    "rend"
                ]
            elif mutation == "heading":
                body.xpath(".//t:ab[@subtype='h4']", namespaces=NS)[0].set(
                    "subtype", "h1"
                )
            payload = etree.tostring(tree, encoding="UTF-8", xml_declaration=True)
            if mutation == "trailing":
                payload += b"\n<!--unclaimed-->"
        assert payload != package.member_bytes(member)
        (target / member).write_bytes(payload)
        record = json.loads((target / "manifest.json").read_bytes())
        row = next(r for r in record["members"] if r["name"] == member)
        row.update(bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())
        (target / "manifest.json").write_text(json.dumps(record), encoding="utf-8")
        mutant = CandidatePackage.load(target)
        mutant.verify_integrity()
        with pytest.raises(ValueError, match="LIB-053"):
            _oracle(source, mutant)
    finally:
        shutil.rmtree(target)


def test_reassigned_neighbor_rejected(verified):
    source, _ = verified
    profile = json.loads(source.authority_path("reconstruction-profile").read_bytes())
    profile["adjacent_retained_member_accounting"][0]["disposition"] = (
        "included: LIB-053 john-owen-worship"
    )
    with pytest.raises(ValueError, match="census drift"):
        _verify_family_census(source, profile)


def test_public_cli_fresh_process_determinism(verified, tmp_path):
    _, package = verified
    destination = tmp_path / "fresh"
    env = dict(os.environ, PYTHONHASHSEED="53")
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "build/tools/reconstruct_candidate.py"),
            "--manifest",
            MANIFEST.relative_to(ROOT).as_posix(),
            "--repository-root",
            str(ROOT),
            "--destination",
            str(destination),
        ],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        fresh = CandidatePackage.load(destination / "package")
        assert fresh.member_names == package.member_names
        for name in package.member_names:
            assert fresh.member_bytes(name) == package.member_bytes(name), name
        assert (
            json.loads((destination / "validation.json").read_bytes())["status"]
            == "pass"
        )
    finally:
        shutil.rmtree(destination)
