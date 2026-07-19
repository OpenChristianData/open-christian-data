"""Focused provenance coverage for regenerated Westminster HTML documents."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from build.lib import writer_identities
from build.parsers import westminster_standard_parser as parser


DOCTRINAL_SLUGS = (
    "directory-for-family-worship",
    "form-of-church-government",
    "solemn-league-and-covenant",
    "sum-of-saving-knowledge",
)


@pytest.mark.parametrize("slug", DOCTRINAL_SLUGS)
def test_regenerated_doctrinal_provenance_matches_source_config(slug: str) -> None:
    config = json.loads(
        (parser.SOURCES_OUT_DIR / slug / "config.json").read_text(encoding="utf-8")
    )
    output = json.loads(
        (parser.DOCS_OUT_DIR / f"{slug}.json").read_text(encoding="utf-8")
    )

    source = config["source"]
    provenance = output["meta"]["provenance"]
    assert provenance["source_url"] == source["url"]
    assert provenance["download_date"] == source["download_date"]
    assert provenance["source_hash"] == source["source_hash"]


def test_source_loader_requires_cache_to_match_config_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    slug = "seeded-document"
    raw_dir = tmp_path / "raw"
    sources_dir = tmp_path / "sources"
    raw_dir.mkdir()
    (sources_dir / slug).mkdir(parents=True)
    raw_bytes = b"<html><body>edition-matched witness</body></html>"
    (raw_dir / f"{slug}.html").write_bytes(raw_bytes)
    expected_hash = "sha256:" + hashlib.sha256(raw_bytes).hexdigest()
    config_path = sources_dir / slug / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "source": {
                    "url": "https://example.test/canonical/",
                    "download_date": "2026-07-16",
                    "source_hash": expected_hash,
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(parser, "RAW_DIR", raw_dir)
    monkeypatch.setattr(parser, "SOURCES_OUT_DIR", sources_dir)

    assert parser._load_document_source(slug)["source_hash"] == expected_hash

    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["source"]["source_hash"] = "sha256:" + "0" * 64
    config_path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ValueError, match="cached HTML hash .* does not match config pin"):
        parser._load_document_source(slug)


def test_shorter_catechism_keeps_html_as_secondary_witness() -> None:
    config = json.loads(
        parser.WSC_CONFIG.read_text(encoding="utf-8")
    )

    assert config["source"]["name"] == "Creeds.json"
    html_sources = [
        source
        for source in config["secondary_sources"]
        if source["name"] == "thewestminsterstandard.org"
    ]
    assert len(html_sources) == 1
    assert html_sources[0]["contribution"] == "proof_texts"
    assert html_sources[0]["source_hash"].startswith("sha256:")


def _seed_temp_document_source(tmp_path: Path, slug: str) -> tuple[Path, Path, Path]:
    raw_dir = tmp_path / "raw" / "westminster-standard-org"
    sources_dir = tmp_path / "sources" / "doctrinal-documents"
    docs_dir = tmp_path / "data" / "doctrinal-documents"
    raw_dir.mkdir(parents=True)
    source_dir = sources_dir / slug
    source_dir.mkdir(parents=True)
    html = b"<html><body><h1>Directory</h1><h1>I.</h1><p>New text.</p></body></html>"
    (raw_dir / f"{slug}.html").write_bytes(html)
    source_hash = "sha256:" + hashlib.sha256(html).hexdigest()
    (source_dir / "config.json").write_text(
        json.dumps(
            {
                "source": {
                    "url": "https://example.test/westminster/",
                    "download_date": "2026-07-17",
                    "source_hash": source_hash,
                }
            }
        ),
        encoding="utf-8",
    )
    return raw_dir, sources_dir, docs_dir


def _nested_delta_document() -> dict:
    def parent(number: str, title: str) -> dict:
        return {
            "unit_type": "section",
            "number": number,
            "title": title,
            "children": [
                {
                    "unit_type": "section",
                    "number": str(child_number),
                    "title": f"Section {child_number}",
                    "content": f"Parent {number}, child {child_number}.",
                }
                for child_number in range(1, 5)
            ],
        }

    return {
        "meta": {"id": "nested-document", "title": "Nested document"},
        "data": {
            "document_id": "nested-document",
            "document_kind": "declaration",
            "revision_history": [],
            "units": [
                parent("8", "Warrants to Believe"),
                parent("9", "The Evidences of True Faith"),
            ],
        },
    }


def _flat_delta_document() -> dict:
    return {
        "meta": {"id": "flat-document", "title": "Flat document"},
        "data": {
            "document_id": "flat-document",
            "document_kind": "declaration",
            "units": [
                {
                    "unit_type": "section",
                    "number": "1",
                    "title": "One",
                    "content": "Body.",
                }
            ],
        },
    }


@pytest.mark.parametrize("text_field", ["content", "content_with_proofs"])
def test_token_count_preservation_matches_flat_unchanged_source_text(
    text_field: str,
) -> None:
    before = _flat_delta_document()
    unit_before = before["data"]["units"][0]
    source_text = unit_before.pop("content")
    unit_before[text_field] = source_text
    unit_before["token_count"] = 2
    after = deepcopy(before)
    after["data"]["units"][0].pop("token_count")

    parser._preserve_unchanged_token_counts(before, after)

    assert after["data"]["units"][0]["token_count"] == 2


def test_token_count_preservation_does_not_copy_after_source_text_change() -> None:
    before = _flat_delta_document()
    before["data"]["units"][0]["token_count"] = 2
    after = deepcopy(before)
    after["data"]["units"][0].pop("token_count")
    after["data"]["units"][0]["content"] = "Changed body."

    parser._preserve_unchanged_token_counts(before, after)

    assert "token_count" not in after["data"]["units"][0]


def test_token_count_preservation_scopes_repeated_child_numbers_by_parent() -> None:
    before = _nested_delta_document()
    expected_counts = ((11, 12, 13, 14), (21, 22, 23, 24))
    for parent, parent_counts in zip(before["data"]["units"], expected_counts):
        for child, token_count in zip(parent["children"], parent_counts):
            child["token_count"] = token_count
    after = deepcopy(before)
    for parent in after["data"]["units"]:
        for child in parent["children"]:
            child.pop("token_count")

    parser._preserve_unchanged_token_counts(before, after)

    actual_counts = tuple(
        tuple(child["token_count"] for child in parent["children"])
        for parent in after["data"]["units"]
    )
    assert actual_counts == expected_counts


def test_token_count_preservation_rejects_duplicate_sibling_keys() -> None:
    before = _flat_delta_document()
    before["data"]["units"][0]["token_count"] = 2
    after = deepcopy(before)
    after["data"]["units"][0].pop("token_count")
    after["data"]["units"].append(deepcopy(after["data"]["units"][0]))

    with pytest.raises(ValueError, match="duplicate sibling key"):
        parser._preserve_unchanged_token_counts(before, after)


def test_document_delta_handles_nested_repeated_child_numbers_deterministically() -> None:
    before = _nested_delta_document()
    after = deepcopy(before)
    after["data"]["units"][1]["children"][2]["content"] = "Changed body."

    assert parser._document_delta_counts(before, after) == (1, 1)
    assert parser._document_delta_counts(before, after) == parser._document_delta_counts(
        before, after
    )


def test_document_delta_counts_missing_metadata_and_data_fields_honestly() -> None:
    before = _flat_delta_document()
    after = deepcopy(before)
    after["meta"]["title"] = "Updated title"
    after["meta"]["edition"] = "Web edition"
    after["meta"]["contributors"] = []
    after["data"]["document_kind"] = "directory"
    after["data"]["revision_history"] = []
    after["data"]["units"][0].pop("content")

    # Metadata changed in three direct fields, data changed in two direct fields, and
    # the unit lost one direct field. Missing fields must not collapse into a match.
    assert parser._document_delta_counts(before, after) == (3, 6)


def test_document_delta_rejects_duplicate_top_level_stable_keys() -> None:
    document = _flat_delta_document()
    duplicate = deepcopy(document["data"]["units"][0])
    document["data"]["units"].append(duplicate)

    with pytest.raises(ValueError, match="not unique"):
        parser._document_delta_counts(None, document)


def test_document_regeneration_emits_real_manifest_in_temp_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    slug = "directory-for-family-worship"
    raw_dir, sources_dir, docs_dir = _seed_temp_document_source(tmp_path, slug)
    output = docs_dir / f"{slug}.json"
    previous = {
        "meta": {"id": slug, "title": "Old title"},
        "data": {
            "document_id": slug,
            "document_kind": "directory",
            "revision_history": [],
            "units": [
                {
                    "unit_type": "section",
                    "number": "1",
                    "title": "I.",
                    "content": "New text.",
                    "token_count": 3,
                }
            ],
        },
    }
    previous_bytes = json.dumps(previous, indent=2).encode("utf-8")
    output.parent.mkdir(parents=True)
    output.write_bytes(previous_bytes)

    monkeypatch.setattr(parser, "RAW_DIR", raw_dir)
    monkeypatch.setattr(parser, "SOURCES_OUT_DIR", sources_dir)
    monkeypatch.setattr(parser, "DOCS_OUT_DIR", docs_dir)

    parser.parse_document(slug)

    manifest_path = tmp_path / "review" / "writer-manifests"
    manifests = sorted(manifest_path.glob("*.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    written = json.loads(output.read_text(encoding="utf-8"))
    assert writer_identities.is_authorised("westminster_standard_parser")
    assert manifest["writer_identity"] == "westminster_standard_parser"
    assert manifest["data_paths"] == [f"data/doctrinal-documents/{slug}.json"]
    checksums = manifest["checksums"][f"data/doctrinal-documents/{slug}.json"]
    assert checksums["before_sha256"] == hashlib.sha256(previous_bytes).hexdigest()
    assert checksums["after_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    expected_counts = parser._document_delta_counts(previous, written)
    assert manifest["expected_delta_counts"][f"data/doctrinal-documents/{slug}.json"] == {
        "entries_changed": expected_counts[0],
        "fields_changed": expected_counts[1],
    }
    assert list(
        Draft202012Validator(
            json.loads(
                (parser.REPO_ROOT / "schemas" / "v1" / "writer_manifest.schema.json").read_text(
                    encoding="utf-8"
                )
            )
        ).iter_errors(manifest)
    ) == []
    assert written["data"]["units"][0]["content"] == "New text."
    assert written["data"]["units"][0]["token_count"] == 3


def test_first_document_write_emits_nonzero_manifest_counts_in_temp_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    slug = "directory-for-family-worship"
    raw_dir, sources_dir, docs_dir = _seed_temp_document_source(tmp_path, slug)
    monkeypatch.setattr(parser, "RAW_DIR", raw_dir)
    monkeypatch.setattr(parser, "SOURCES_OUT_DIR", sources_dir)
    monkeypatch.setattr(parser, "DOCS_OUT_DIR", docs_dir)

    parser.parse_document(slug)

    output = docs_dir / f"{slug}.json"
    manifest_path = next((tmp_path / "review" / "writer-manifests").glob("*.json"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    written = json.loads(output.read_text(encoding="utf-8"))
    data_path = f"data/doctrinal-documents/{slug}.json"
    counts = manifest["expected_delta_counts"][data_path]
    expected = parser._document_delta_counts(None, written)

    assert counts == {
        "entries_changed": expected[0],
        "fields_changed": expected[1],
    }
    assert expected[0] > 0 and expected[1] > 0
    assert expected == parser._document_delta_counts(None, written)
    assert manifest["checksums"][data_path]["before_sha256"] is None
    assert manifest["checksums"][data_path]["after_sha256"] == hashlib.sha256(
        output.read_bytes()
    ).hexdigest()
    assert "token_count" not in written["data"]["units"][0]


def test_document_dry_run_does_not_write_data_or_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    slug = "directory-for-family-worship"
    raw_dir, sources_dir, docs_dir = _seed_temp_document_source(tmp_path, slug)
    output = docs_dir / f"{slug}.json"
    original = b"resident-safe sentinel"
    output.parent.mkdir(parents=True)
    output.write_bytes(original)

    monkeypatch.setattr(parser, "RAW_DIR", raw_dir)
    monkeypatch.setattr(parser, "SOURCES_OUT_DIR", sources_dir)
    monkeypatch.setattr(parser, "DOCS_OUT_DIR", docs_dir)

    parser.parse_document(slug, dry_run=True)

    assert output.read_bytes() == original
    assert not (tmp_path / "review" / "writer-manifests").exists()
