from __future__ import annotations

import json
from pathlib import Path

from lxml import etree

from build.tei import calvins_institutes_pg64392_member_oracle as oracle_module
from build.tei.calvins_institutes_pg64392_member_reconstruction import _convert
from ocd_kernel.reconstruction.contract import SourceManifest, reconstruct, validate
from tests.live_work_catalog_fixture import _live_work_catalog_record, live_work_catalog


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = (
    ROOT
    / "tests/fixtures/reconstruction-runtime/calvins-institutes-pg64392-member.source-manifest.json"
)
SOURCE_PATH = ROOT / "raw/gutenberg/pg64392.txt"
NS = {"tei": "http://www.tei-c.org/ns/1.0", "xml": "http://www.w3.org/XML/1998/namespace"}


def test_pg64392_member_is_an_exact_nonaccepted_partial_candidate(tmp_path: Path) -> None:
    source_manifest = SourceManifest.load(MANIFEST, repository_root=ROOT)
    primary = [
        item
        for item in source_manifest.record["authorities"]
        if item.get("role") == "primary-source"
    ]
    assert primary == [
        {
            "bytes": 2_134_850,
            "name": "retained-volume-2",
            "path": "raw/gutenberg/pg64392.txt",
            "role": "primary-source",
            "sha256": "3d79335bbb231773d1cbf849f4f7dd67e52f8773091416ba765da3ade0fefb31",
        }
    ]

    candidate = reconstruct(source_manifest, tmp_path / "candidate", _convert)
    report = validate(source_manifest, candidate, oracle_module._oracle)
    assert report.status == "pass"
    assert candidate.manifest["status"] == "nonaccepted"
    assert candidate.manifest["source_id"] == (
        "calvins-institutes-project-gutenberg-pg64392-member-retained"
    )

    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    assert accountability["source_bytes"] == 2_134_850
    assert accountability["physical_line_count"] == 38_723
    expected_member = {
        key: primary[0][key]
        for key in ("bytes", "path", "sha256")
    }
    assert accountability["source_members"] == [expected_member]
    assert {row["member"] for row in accountability["lines"]} == {
        "raw/gutenberg/pg64392.txt"
    }

    tei = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    assert tei.get("{http://www.w3.org/XML/1998/namespace}id") == (
        "calvins-institutes-gutenberg-pg64392-member-candidate"
    )
    assert [
        (node.get("{http://www.w3.org/XML/1998/namespace}id"), node.get("n"))
        for node in tei.xpath("./tei:text/tei:group/tei:text", namespaces=NS)
    ] == [("calvin-volume-2", "2")]
    assert tei.xpath(
        "//tei:div[@type='book' and @n='3']/tei:div[@type='chapter' and @n='14']",
        namespaces=NS,
    )
    assert tei.xpath("//tei:div[@type='book' and @n='4']", namespaces=NS)
    assert tei.xpath(
        "//tei:div[@type='index' and @subtype='principal-matters']",
        namespaces=NS,
    )
    assert tei.xpath(
        "//tei:div[@type='index' and @subtype='scripture']", namespaces=NS
    )
    assert len(tei.xpath("//tei:note[@place='end']", namespaces=NS)) == 1_490
    assert tei.xpath("//tei:hi[@rend='underscore']", namespaces=NS)

    package_bytes = b"".join(candidate.member_bytes(name) for name in candidate.member_names)
    assert b"pg64392.txt" in package_bytes
    assert b"pg45001" not in package_bytes
    assert SOURCE_PATH.read_text(encoding="utf-8-sig").startswith(
        "The Project Gutenberg eBook"
    )


def test_pg64392_member_route_is_verified_partial_and_cvws_one_source(live_work_catalog) -> None:
    catalog = live_work_catalog
    work = next(item for item in catalog.works if item["work_id"] == "calvins-institutes")
    route = next(
        route
        for route in work["reconstruction_state"]["routes"]
        if route["manifest"].endswith(
            "sources/calvins-institutes/pg64392-member/"
            "calvins-institutes-pg64392-member.source-manifest.json"
        )
    )
    assert route["verification"] == "verified"
    assert route["scope"] == "partial"
    assert route["association"] == "catalog_claim_lineage+exact_id"
    assert work["reconstruction_state"]["retained_source"] == "manifest_bound_partial"
    assert work["reconstruction_state"]["blocker"] == (
        "partial source coverage cannot establish whole-work accepted IR"
    )
