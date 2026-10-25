"""Technical acceptance checks for the LIB-055 Murray reconstruction route."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from lxml import etree

from build.tei.murray_absolute_surrender_oracle import _oracle
from build.tei.murray_absolute_surrender_reconstruction import _convert
from ocd_kernel.reconstruction import (
    CandidatePackage,
    SourceManifest,
    reconstruct,
    validate,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = Path('tests/fixtures/reconstruction-runtime/puritan-murray-absolute-surrender.source-manifest.json')
SOURCE_SHA256 = "3b8a474258f452b6d43ce14735c2594da52cd583a0271e8a650969aad97aff7d"
WORK_ID = "murray-absolute-surrender"
SOURCE_ID = "murray-absolute-surrender-retained-thml"


def _route(tmp_path: Path) -> tuple[SourceManifest, CandidatePackage]:
    manifest = SourceManifest.load(MANIFEST_PATH, repository_root=ROOT)
    run_parent = tmp_path / "candidate-run"
    run_parent.mkdir()
    candidate = reconstruct(manifest, run_parent / "package", _convert)
    return manifest, candidate


def _canonical(record: object) -> bytes:
    return (
        json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _reseal(candidate_path: Path) -> CandidatePackage:
    manifest_path = candidate_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for member in manifest["members"]:
        content = (candidate_path / member["name"]).read_bytes()
        member["bytes"] = len(content)
        member["sha256"] = hashlib.sha256(content).hexdigest()
    manifest_path.write_bytes(_canonical(manifest))
    return CandidatePackage.load(candidate_path)


def test_murray_route_binds_complete_source_and_independent_validation(
    tmp_path: Path,
) -> None:
    manifest, candidate = _route(tmp_path)

    assert manifest.record["source_id"] == SOURCE_ID
    assert manifest.record["work_id"] == WORK_ID
    assert set(candidate.member_names) == {
        "README.source.md",
        "content.tei.xml",
        "manifest.json",
        "provenance.json",
        "source-accountability.json",
        "unresolved.jsonl",
    }
    accountability = json.loads(
        candidate.member_bytes("source-accountability.json").decode("utf-8")
    )
    assert accountability["member_census"] == [
        {
            "path": "raw/ccel/murray/surrender.xml",
            "bytes": 217645,
            "sha256": SOURCE_SHA256,
            "scope": "whole ThML document including complete header and body",
            "disposition": "included",
        }
    ]
    assert accountability["counts"]["source_elements"] == 954
    assert accountability["counts"]["body_elements"] == 890
    assert accountability["counts"]["unmapped_features"] == 0
    assert accountability["counts"]["duplicate_features"] == 0
    assert len(accountability["crosswalk"]) == 954

    report = validate(manifest, candidate, _oracle)
    assert report.status == "pass"
    assert report.findings == ()
    assert report.attestation["source_sha256"] == SOURCE_SHA256
    assert report.attestation["oracle_id"] == (
        "ocd-murray-absolute-surrender-independent-thml-oracle"
    )


def test_murray_source_title_attributes_are_accounted_without_duplicate_heads(
    tmp_path: Path,
) -> None:
    _, candidate = _route(tmp_path)
    accountability = json.loads(
        candidate.member_bytes("source-accountability.json").decode("utf-8")
    )
    tei_root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    namespace = {"tei": "http://www.tei-c.org/ns/1.0"}

    source_root = etree.parse(
        str(ROOT / "raw/ccel/murray/surrender.xml"),
        etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False),
    )
    expected_titles = [
        node.get("title")
        for node in source_root.xpath("/ThML/ThML.body//div1 | /ThML/ThML.body//div2")
        if node.get("title") is not None
    ]
    accounted_titles = [
        next(
            attribute["value"]
            for attribute in row["source_attributes"]
            if attribute["qname"] == "title"
        )
        for row in accountability["crosswalk"]
        if row["source_qname"] in {"div1", "div2"}
        and any(attribute["qname"] == "title" for attribute in row["source_attributes"])
    ]

    assert accounted_titles == expected_titles
    assert tei_root.xpath(
        "//tei:head[@type='source-title-attribute']", namespaces=namespace
    ) == []
    assert len(
        tei_root.xpath("//tei:head[starts-with(@type, 'ThML-h')]", namespaces=namespace)
    ) == 15


def test_murray_oracle_rejects_resealed_source_crosswalk_omission(
    tmp_path: Path,
) -> None:
    manifest, candidate = _route(tmp_path)
    accountability_path = candidate.path / "source-accountability.json"
    accountability = json.loads(accountability_path.read_text(encoding="utf-8"))
    accountability["crosswalk"].pop()
    accountability_path.write_bytes(_canonical(accountability))
    resealed = _reseal(candidate.path)

    with pytest.raises(ValueError, match="independent source enumeration"):
        validate(manifest, resealed, _oracle)


def test_murray_oracle_rejects_resealed_tei_invention(tmp_path: Path) -> None:
    manifest, candidate = _route(tmp_path)
    tei_path = candidate.path / "content.tei.xml"
    tei_root = etree.fromstring(tei_path.read_bytes())
    body_paragraph = tei_root.xpath(
        "//*[local-name()='body']//*[local-name()='p'][1]"
    )[0]
    body_paragraph.text = (body_paragraph.text or "") + "[invented]"
    tei_path.write_bytes(
        etree.tostring(
            tei_root,
            encoding="UTF-8",
            xml_declaration=True,
            pretty_print=False,
        )
    )
    resealed = _reseal(candidate.path)

    with pytest.raises(ValueError, match="independent ThML-to-TEI re-read"):
        validate(manifest, resealed, _oracle)
