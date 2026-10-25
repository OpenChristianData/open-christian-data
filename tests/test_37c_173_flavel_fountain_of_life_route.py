"""Focused tests for the 37c-173 work-local LIB-055 source route.

These tests call the pure converter in memory. They do not invoke the candidate
packager, create a candidate directory, or write to the durable candidate home.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest
from lxml import etree

from ocd_kernel.reconstruction.contract import SourceManifest
from build.tei.ccel_puritan_lib055_flavel_fountain_of_life_reconstruction import (
    SOURCE_BYTES,
    SOURCE_PATH,
    SOURCE_SHA256,
    WORK_ID,
    _convert,
)
from build.tei.ccel_puritan_lib055_flavel_fountain_of_life_oracle import (
    _expected_accountability,
    _expected_provenance,
    _expected_unresolved,
    _import_closure_sha256,
    _read,
    _source_facts,
    validate_tei_bytes,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = (
    ROOT / 'tests/fixtures/reconstruction-runtime/ccel_puritan_lib055_flavel_fountain_of_life_oracle.source-manifest.json'
)
PROFILE = (
    ROOT
    / "sources/structured-text/flavel-fountain-of-life/lib055/source-feature-profile.json"
)
POLICY = (
    ROOT
    / "sources/structured-text/flavel-fountain-of-life/lib055/validation-policy.json"
)
NS = {"tei": "http://www.tei-c.org/ns/1.0"}
TEI = "{http://www.tei-c.org/ns/1.0}"


@pytest.fixture(scope="module")
def route():
    manifest = SourceManifest.load(MANIFEST, repository_root=ROOT)
    members = _convert(manifest)
    return manifest, members


def test_manifest_binds_exact_complete_retained_member_and_owner_contract():
    manifest = SourceManifest.load(MANIFEST, repository_root=ROOT)
    record = manifest.record
    member = manifest.authority_path("source-member").read_bytes()
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    identity = record["identity"]

    assert record["ticket"] == "37c-173"
    assert record["owner_route"] == "LIB-055"
    assert record["work_id"] == WORK_ID
    assert record["status"] == "entry-local-route-ready"
    assert len(member) == SOURCE_BYTES
    assert tuple(record["scope"]["member_order"]) == (SOURCE_PATH,)
    assert tuple(record["scope"]["top_level_div1_ids"]) == (
        "i",
        "ii",
        "iii",
        "iv",
        "v",
        "vi",
    )
    assert tuple(record["scope"]["main_div1_direct_div2_ids"]) == tuple(
        profile["document"]["main_div1_direct_div2_ids_in_order"]
    )
    assert tuple(record["scope"]["index_div2_ids"]) == ("vi.i", "vi.ii")
    assert all(
        identity[field] is None
        for field in (
            "textual_form",
            "edition",
            "parts",
            "witness_claim",
            "translator",
            "original_publication_year",
        )
    )
    assert profile["source_member"]["sha256"] == SOURCE_SHA256
    assert profile["document"]["element_count"] == 7539
    assert profile["document"]["attribute_count"] == 16199
    assert (
        profile["document"]["source_id_count"]
        == profile["document"]["unique_source_id_count"]
        == 4971
    )
    assert profile["document"]["links"] == {
        "count": 2375,
        "fragment_links": 2375,
        "all_fragments_resolve_to_source_ids": True,
    }
    assert policy["scope"]["exclusions"] == []

    owner = (
        ROOT
        / "plans/2026-08-26-whole-library-faithful-tei-completion/tickets/library/055-reconstruct-and-review-ccel-puritan-works-cohort-2.md"
    ).read_text(encoding="utf-8")
    work_map = (
        ROOT
        / "plans/2026-08-26-whole-library-faithful-tei-completion/02-work-ticket-map.md"
    ).read_text(encoding="utf-8")
    source_map = (
        ROOT
        / "plans/2026-08-26-whole-library-faithful-tei-completion/05-source-ticket-map.md"
    ).read_text(encoding="utf-8")
    assert "`flavel-fountain-of-life` — The Fountain of Life Opened Up" in owner
    assert (
        "| `flavel-fountain-of-life` | The Fountain of Life Opened Up | LIB-055 | 1 | none |"
        in work_map
    )
    assert (
        f"| `{WORK_ID}` | `sha256:{SOURCE_SHA256}` | LIB-055 | current-claim |"
        in source_map
    )


def test_pure_converter_output_is_independently_checked_without_packaging(route):
    manifest, members = route
    assert set(members) == {
        "README.source.md",
        "content.tei.xml",
        "provenance.json",
        "source-accountability.json",
        "unresolved.jsonl",
    }
    assert "manifest.json" not in members
    assert validate_tei_bytes(manifest, members["content.tei.xml"])["status"] == "pass"

    tei = etree.fromstring(members["content.tei.xml"])
    assert (
        tei.findtext(
            "./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title", namespaces=NS
        )
        == "The Fountain of Life Opened Up"
    )
    assert [
        node.get("{http://www.w3.org/XML/1998/namespace}id")
        for node in tei.xpath(
            "./tei:text/tei:front/tei:div | ./tei:text/tei:body/tei:div | ./tei:text/tei:back/tei:div",
            namespaces=NS,
        )
    ] == ["i", "ii", "iii", "iv", "v", "vi"]
    assert len(tei.xpath(".//tei:div[@type='source-div2']", namespaces=NS)) == 44
    assert len(tei.xpath(".//tei:ref[@type='scripture']", namespaces=NS)) == 1949
    assert (
        len(
            tei.xpath(
                ".//tei:anchor[@type='scripture-commentary-marker']", namespaces=NS
            )
        )
        == 42
    )
    assert len(tei.xpath(".//tei:anchor[@type='index-insertion']", namespaces=NS)) == 2

    accounting = json.loads(members["source-accountability.json"])
    assert accounting["source_member"] == {
        "path": SOURCE_PATH,
        "bytes": SOURCE_BYTES,
        "sha256": SOURCE_SHA256,
    }
    assert len(accounting["elements"]) == 7539
    assert len(accounting["body_divisions"]) == 6
    assert [item["id"] for item in accounting["body_divisions"]] == [
        "i",
        "ii",
        "iii",
        "iv",
        "v",
        "vi",
    ]
    assert accounting["dispositions"]["unrepresented_body_divisions"] == []
    assert accounting["source_envelope"]["shell"]["before_root_nodes"] == [
        {"kind": "comment", "text": " Copyright Christian Classics Ethereal Library "}
    ]
    source_tree = _read(manifest.authority_path("source-member").read_bytes())
    source_facts = _source_facts(source_tree)
    assert members["source-accountability.json"] == _expected_accountability(
        manifest, source_tree, source_facts
    )
    assert members["provenance.json"] == _expected_provenance(
        manifest, manifest.authority_path("source-member").read_bytes()
    )
    assert members["unresolved.jsonl"] == _expected_unresolved(manifest)
    assert (
        members["README.source.md"]
        == manifest.authority_path("source-readme").read_bytes()
    )


def _mutate(data: bytes, mutation: str) -> bytes:
    root = etree.fromstring(data)
    if mutation == "omit-division":
        root.find("./tei:text/tei:front", namespaces=NS).remove(
            root.find("./tei:text/tei:front/tei:div", namespaces=NS)
        )
    elif mutation == "duplicate-division":
        front = root.find("./tei:text/tei:front", namespaces=NS)
        front.insert(1, deepcopy(front[0]))
    elif mutation == "reorder-division":
        front = root.find("./tei:text/tei:front", namespaces=NS)
        first, second = front[0], front[1]
        front.remove(first)
        front.insert(1, first)
        assert front[0] is second
    elif mutation == "paragraph-wording":
        paragraph = root.find(".//tei:p", namespaces=NS)
        assert paragraph is not None and paragraph.text
        paragraph.text += " altered"
    elif mutation == "internal-link":
        reference = root.find(".//tei:ref[@target]", namespaces=NS)
        assert reference is not None
        reference.set("target", reference.get("target", "") + "-altered")
    elif mutation == "scripture-reference":
        reference = root.find(".//tei:ref[@type='scripture']", namespaces=NS)
        assert reference is not None and reference.get("target")
        reference.set("target", reference.get("target", "") + ".99")
    elif mutation == "commentary-marker":
        marker = root.find(
            ".//tei:anchor[@type='scripture-commentary-marker']", namespaces=NS
        )
        assert marker is not None and marker.getparent() is not None
        marker.getparent().remove(marker)
    elif mutation == "metadata":
        title = root.find(
            "./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title", namespaces=NS
        )
        assert title is not None
        title.text = "Different source title"
    else:
        raise AssertionError(mutation)
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True)


@pytest.mark.parametrize(
    "mutation",
    (
        "omit-division",
        "duplicate-division",
        "reorder-division",
        "paragraph-wording",
        "internal-link",
        "scripture-reference",
        "commentary-marker",
        "metadata",
    ),
)
def test_independent_oracle_rejects_source_meaning_mutations(route, mutation):
    manifest, members = route
    baseline = members["content.tei.xml"]
    changed = _mutate(baseline, mutation)
    assert changed != baseline
    with pytest.raises(ValueError, match="candidate TEI|TEI differs"):
        validate_tei_bytes(manifest, changed)


def test_oracle_closure_is_bound_and_does_not_import_the_producer():
    manifest = SourceManifest.load(MANIFEST, repository_root=ROOT)
    validator = manifest.record["validator"]
    assert validator["import_closure_sha256"] == _import_closure_sha256(ROOT)
    oracle_source = Path(validator["implementation_path"])
    text = (ROOT / oracle_source).read_text(encoding="utf-8")
    assert "ccel_puritan_lib055_flavel_fountain_of_life_reconstruction" not in text
    assert "build.parsers.ccel_puritan_works" not in text
