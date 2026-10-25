from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from build.parsers.ccel_npnf1 import VOLUME_CONFIG, build_meta as build_ccel_meta
from build.parsers.standard_ebooks import build_meta as build_standard_ebooks_meta
from ocd_kernel.lib.schema_enums import resolve_schema_path


EXPRESSION_ID = "augustine-city-of-god-dods-en"
SE_WITNESS_ID = "city-of-god-standard-ebooks"
CCEL_WITNESS_ID = "city-of-god-ccel-npnf102"
CURRENT_SE_REVISION = "7ec3a325a495cb791581d06f1c0fed14d2576ff0"
CURRENT_SE_ACQUISITION_DATE = "2026-07-21"


@pytest.mark.requires_local_artifacts
def test_current_standard_ebooks_checkout_config_and_canonical_provenance_agree() -> None:
    root = Path(__file__).resolve().parents[1]
    source_dir = root / "raw" / "standard_ebooks" / (
        "augustine-of-hippo_the-city-of-god_marcus-dods_george-wilson_j-j-smith"
    )
    head_ref = (source_dir / ".git" / "HEAD").read_text(encoding="utf-8").strip()
    assert head_ref == "ref: refs/heads/master"
    retained_revision = (source_dir / ".git" / "refs" / "heads" / "master").read_text(
        encoding="utf-8"
    ).strip()
    config = json.loads(
        (
            root
            / "sources"
            / "standard-ebooks"
            / source_dir.name
            / "config.json"
        ).read_text(encoding="utf-8")
    )
    canonical = json.loads(
        (root / "data" / "structured-text" / "city-of-god.json").read_text(
            encoding="utf-8"
        )
    )

    assert retained_revision == CURRENT_SE_REVISION
    assert config["source_revision"] == retained_revision
    assert config["source_revision_type"] == "git-commit-sha1"
    assert config["download_date"] == CURRENT_SE_ACQUISITION_DATE
    assert canonical["meta"]["provenance"]["source_revision"] == retained_revision
    assert canonical["meta"]["provenance"]["download_date"] == CURRENT_SE_ACQUISITION_DATE


def test_standard_ebooks_provenance_separates_source_output_and_processing_identities() -> None:
    config = {
        "resource_id": "city-of-god",
        "title": "The City of God",
        "author": "Augustine of Hippo",
        "contributors": [{"name": "Marcus Dods", "role": "translator"}],
        "original_publication_year": 426,
        "language": "en",
        "original_language": "la",
        "tradition": ["patristic"],
        "license": "public-domain",
        "schema_type": "structured_text",
        "source_url": "https://github.com/standardebooks/example",
        "source_format": "Standard Ebooks EPUB source repository",
        "source_edition": "Standard Ebooks edition",
        "download_date": None,
        "source_revision": "6290cb26fa2cac6ef2f9105c9176a97ee3f46b94",
        "source_revision_type": "git-commit-sha1",
        "source_hash_scope": "selected-xhtml-source-manifest-v1",
        "expression_id": EXPRESSION_ID,
        "digital_witness_id": SE_WITNESS_ID,
        "witness_role": "preferred-reading-transformation",
        "related_witness_ids": [CCEL_WITNESS_ID],
        "segmentation_basis": "Publisher XHTML files flattened to parser sections.",
        "notes": "Fixture.",
    }

    meta = build_standard_ebooks_meta(
        config,
        source_hash="sha256:" + "a" * 64,
        generated_content_hash="sha256:" + "b" * 64,
        processing_date="2026-07-20",
    )

    assert meta["expression_id"] == EXPRESSION_ID
    assert meta["digital_witness_id"] == SE_WITNESS_ID
    assert meta["witness_role"] == "preferred-reading-transformation"
    assert meta["related_witness_ids"] == [CCEL_WITNESS_ID]
    assert meta["segmentation_basis"].startswith("Publisher XHTML")
    assert meta["provenance"]["download_date"] is None
    assert meta["provenance"]["processing_date"] == "2026-07-20"
    assert meta["provenance"]["source_hash"] == "sha256:" + "a" * 64
    assert meta["provenance"]["source_hash_scope"] == "selected-xhtml-source-manifest-v1"
    assert meta["provenance"]["source_revision"] == "6290cb26fa2cac6ef2f9105c9176a97ee3f46b94"
    assert meta["provenance"]["source_revision_type"] == "git-commit-sha1"
    assert meta["provenance"]["generated_content_hash"] == "sha256:" + "b" * 64


def test_ccel_city_of_god_metadata_records_translator_editor_print_basis_and_witness_role() -> None:
    volume = VOLUME_CONFIG["npnf102"]
    work = next(item for item in volume["works"] if item["slug"] == "augustine-city-of-god")

    meta = build_ccel_meta(
        "npnf102",
        work,
        "sha256:" + "c" * 64,
        generated_content_hash="sha256:" + "d" * 64,
    )

    assert meta["contributors"] == [
        {"name": "Marcus Dods", "role": "translator", "note": "1871 translation"},
        {"name": "Philip Schaff", "role": "series_editor"},
    ]
    assert meta["provenance"]["translator"] == "Marcus Dods (translator), 1871"
    assert meta["provenance"]["source_edition"] == (
        "Nicene and Post-Nicene Fathers, First Series, Volume 2. "
        "New York: Christian Literature Publishing Co., 1890. Philip Schaff, series editor."
    )
    assert meta["provenance"]["download_date"] == "2026-04-23"
    assert meta["provenance"]["source_hash_scope"] == "retained-thml-file"
    assert meta["provenance"]["generated_content_hash"] == "sha256:" + "d" * 64
    assert meta["expression_id"] == EXPRESSION_ID
    assert meta["digital_witness_id"] == CCEL_WITNESS_ID
    assert meta["witness_role"] == "verification-collation-apparatus"
    assert meta["related_witness_ids"] == [SE_WITNESS_ID]
    assert "page breaks" in meta["segmentation_basis"]


def test_structured_text_schema_accepts_distinct_witness_and_identity_metadata() -> None:
    schema = json.loads(resolve_schema_path("structured_text").read_text(encoding="utf-8"))
    payload = {
        "meta": {
            "id": "city-of-god",
            "title": "The City of God",
            "author": "Augustine of Hippo",
            "original_publication_year": 426,
            "language": "en",
            "original_language": "la",
            "tradition": ["patristic"],
            "license": "public-domain",
            "schema_type": "structured_text",
            "schema_version": "1.0.0",
            "completeness": "full",
            "expression_id": EXPRESSION_ID,
            "digital_witness_id": SE_WITNESS_ID,
            "witness_role": "preferred-reading-transformation",
            "related_witness_ids": [CCEL_WITNESS_ID],
            "segmentation_basis": "Publisher XHTML files flattened to parser sections.",
            "provenance": {
                "source_url": "https://example.test/source",
                "source_format": "EPUB source repository",
                "source_edition": "Fixture",
                "download_date": None,
                "source_hash": "sha256:" + "a" * 64,
                "source_hash_scope": "selected-xhtml-source-manifest-v1",
                "source_revision": "6290cb26fa2cac6ef2f9105c9176a97ee3f46b94",
                "source_revision_type": "git-commit-sha1",
                "generated_content_hash": "sha256:" + "b" * 64,
                "processing_method": "automated",
                "processing_script_version": "fixture@1",
                "processing_date": "2026-07-20",
            },
        },
        "data": {
            "work_id": "city-of-god",
            "work_kind": "theological-work",
            "sections": [{"section_type": "book"}],
        },
    }

    jsonschema.validate(payload, schema)
