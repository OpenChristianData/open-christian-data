import importlib
import json
from pathlib import Path

from build.scripts.export_huggingface import extract_meta_fields


def _write_resource(path: Path, *, resource_id: str, title: str, schema_type: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "meta": {
                    "id": resource_id,
                    "title": title,
                    "author": "Fixture Author",
                    "schema_type": schema_type,
                    "license": "public-domain",
                    "provenance": {"source_url": "https://example.test/source"},
                },
                "data": [{"entry_id": "entry-1", "definition": "Text."}],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_publication_metadata_exposes_witness_relationship_and_identity_boundaries() -> None:
    fields = extract_meta_fields(
        {
            "id": "city-of-god",
            "title": "The City of God",
            "author": "Augustine of Hippo",
            "schema_type": "structured_text",
            "license": "public-domain",
            "expression_id": "augustine-city-of-god-dods-en",
            "digital_witness_id": "city-of-god-standard-ebooks",
            "witness_role": "preferred-reading-transformation",
            "related_witness_ids": ["city-of-god-ccel-npnf102"],
            "segmentation_basis": "Publisher XHTML files flattened to parser sections.",
            "provenance": {
                "source_url": "https://example.test/source",
                "source_edition": "Standard Ebooks edition",
                "download_date": None,
                "processing_date": "2026-07-20",
                "source_hash": "sha256:" + "a" * 64,
                "source_hash_scope": "selected-xhtml-source-manifest-v1",
                "source_revision": "6290cb26fa2cac6ef2f9105c9176a97ee3f46b94",
                "source_revision_type": "git-commit-sha1",
                "generated_content_hash": "sha256:" + "b" * 64,
            },
        }
    )

    assert fields["_expression_id"] == "augustine-city-of-god-dods-en"
    assert fields["_digital_witness_id"] == "city-of-god-standard-ebooks"
    assert fields["_witness_role"] == "preferred-reading-transformation"
    assert fields["_related_witness_ids"] == ["city-of-god-ccel-npnf102"]
    assert fields["_segmentation_basis"].startswith("Publisher XHTML")
    assert fields["_source_revision_type"] == "git-commit-sha1"
    assert fields["_source_revision"].startswith("6290cb26")
    assert fields["_source_hash"].startswith("sha256:")
    assert fields["_source_hash_scope"] == "selected-xhtml-source-manifest-v1"
    assert fields["_generated_content_hash"].startswith("sha256:")
    assert fields["_acquired_on"] is None
    assert fields["_processed_on"] == "2026-07-20"


def test_legacy_huggingface_export_skips_nsh_artifacts_and_writes_card(
    tmp_path: Path, monkeypatch
) -> None:
    data_root = tmp_path / "data"
    output_root = tmp_path / "exports" / "huggingface"
    card_path = tmp_path / "docs" / "HUGGINGFACE_DATASET_CARD.md"
    log_path = tmp_path / "export_huggingface.log"

    _write_resource(
        data_root / "reference" / "eastons-bible-dictionary.json",
        resource_id="eastons-bible-dictionary",
        title="Easton's Bible Dictionary",
        schema_type="reference_entry",
    )
    _write_resource(
        data_root / "reference" / "schaff" / "encyclopedia" / "1908-1914" / "original" / "vol_01.json",
        resource_id="schaff-herzog-encyclopedia",
        title="New Schaff-Herzog Encyclopedia of Religious Knowledge",
        schema_type="reference_entry",
    )
    card_path.parent.mkdir(parents=True, exist_ok=True)
    card_path.write_text("# Fixture dataset card\n", encoding="utf-8")

    exporter = importlib.import_module("build.scripts.export_huggingface")
    monkeypatch.setattr(exporter, "DATA_DIR", data_root)
    monkeypatch.setattr(exporter, "OUTPUT_DIR", output_root)
    monkeypatch.setattr(exporter, "DATASET_CARD", card_path)
    monkeypatch.setattr(exporter, "LOG_FILE", log_path)

    exporter.run_export()

    rows = [
        json.loads(line)
        for line in (output_root / "reference_entry.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [row["_source_id"] for row in rows] == ["eastons-bible-dictionary"]
    assert (output_root / "README.md").read_text(encoding="utf-8") == "# Fixture dataset card\n"
