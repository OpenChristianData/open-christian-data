"""Tests for build.lib.render_cache."""

from __future__ import annotations

import json
from pathlib import Path

from build.lib.render_cache import CacheKey, CacheManifest
from build.tools import render_review_html


def _key(record_sha: str = "a", sidecar_sha: str = "b", **overrides) -> CacheKey:
    base = {
        "record_sha256": record_sha,
        "sidecar_sha256": sidecar_sha,
        "producer_registry_version": "v1",
        "renderer_version": "v1.0.0",
        "schema_version": "v1",
        "scans_manifest_checksum_sha256": None,
    }
    base.update(overrides)
    return CacheKey(**base)


def _resource_record() -> dict:
    return {
        "meta": {
            "id": "sample-commentary",
            "title": "Sample Commentary",
            "author": "Test Author",
            "license": "public-domain",
            "schema_type": "commentary",
            "schema_version": "2.2.0",
            "provenance": {
                "source_url": "https://example.test/source",
                "source_format": "HTML",
                "source_edition": "Sample edition",
                "processing_method": "automated",
                "processing_script_version": "parser@v1",
                "processing_date": "2026-05-06",
            },
        },
        "data": [
            {
                "entry_id": "sample.Gen.1.1",
                "book": "Genesis",
                "book_osis": "Gen",
                "chapter": 1,
                "verse_range": "1",
                "verse_range_osis": "Gen.1.1",
                "verse_text": "In the beginning God created the heavens and the earth.",
                "commentary_text": "Verse note line one.",
                "summary": None,
                "summary_review_status": "withheld",
                "cross_references": [],
                "word_count": 4,
            }
        ],
    }


def test_cache_hit_when_all_components_match(tmp_path: Path) -> None:
    manifest = CacheManifest()
    key = _key()
    manifest.record("clarke-2-john", key, "review/foo.html")

    assert manifest.is_hit("clarke-2-john", key)


def test_record_change_invalidates_one_entry(tmp_path: Path) -> None:
    manifest = CacheManifest()
    key1 = _key()
    manifest.record("clarke-2-john", key1, "review/foo.html")

    key2 = _key(record_sha="changed")
    assert not manifest.is_hit("clarke-2-john", key2)


def test_producer_registry_bump_invalidates_entries(tmp_path: Path) -> None:
    manifest = CacheManifest()
    manifest.record("clarke-2-john", _key(), "review/foo.html")
    manifest.record("sh", _key(), "review/sh.html")

    bumped_key = _key(producer_registry_version="v2")
    assert not manifest.is_hit("clarke-2-john", bumped_key)
    assert not manifest.is_hit("sh", bumped_key)


def test_scans_manifest_checksum_change_invalidates_entry(tmp_path: Path) -> None:
    manifest = CacheManifest()
    key1 = _key(scans_manifest_checksum_sha256="abc123")
    manifest.record("sh", key1, "review/sh.html")

    key2 = _key(scans_manifest_checksum_sha256="def456")
    assert not manifest.is_hit("sh", key2)


def test_round_trip_save_and_load(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    manifest = CacheManifest()
    manifest.record("clarke-2-john", _key(), "review/foo.html")
    manifest.save(path)

    loaded = CacheManifest.load(path)
    assert loaded.is_hit("clarke-2-john", _key())


def test_render_resource_review_skips_producers_on_cache_hit(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "data" / "commentaries" / "sample" / "genesis.json"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(json.dumps(_resource_record()), encoding="utf-8")
    cache_path = tmp_path / "cache.json"
    calls = {"run_all_producers": 0}

    def fake_run_all_producers(payload, meta, producers):
        calls["run_all_producers"] += 1
        return {}

    monkeypatch.setattr(render_review_html, "DEFAULT_CACHE_PATH", cache_path)
    monkeypatch.setattr(render_review_html, "run_all_producers", fake_run_all_producers)

    first_output = render_review_html.render_resource_review(
        source_path=source,
        data_root=tmp_path / "data",
        output_root=tmp_path / "review",
    )
    first_html = first_output.read_text(encoding="utf-8")
    second_output = render_review_html.render_resource_review(
        source_path=source,
        data_root=tmp_path / "data",
        output_root=tmp_path / "review",
    )
    second_html = second_output.read_text(encoding="utf-8")

    assert calls["run_all_producers"] == 1
    assert first_output == second_output
    assert second_output.exists()
    assert second_html == first_html
