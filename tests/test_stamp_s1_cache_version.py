"""Tests for the S1 sidecar cache-version stamp tool.

The tool backfills ``runner_cache_version`` onto legacy sidecars written before
commit e6a08a98 added the field. It must stamp ONLY sidecars that already pass
every other currentness check (image sha, leaf, schema, rendering_id, no
failure_class) -- never a sidecar whose OCR content cannot be trusted.

The contract these tests pin: after stamping, the runner's own
``_sidecar_is_done`` returns True, and the page_extras integrity fields
(``page_extras_carried_keys`` + ``page_extras_jcs_sha256``) are recomputed so
the sidecar stays internally consistent and schema-valid.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import build.parsers.s1_tesseract_runner as tess
from build.lib.edition_page_key import body_edition_key
from build.tools.ocr_pipeline import stamp_s1_cache_version as stamp

# A realistic source-image sha and leaf for the fixtures.
_SHA = "sha256:" + "a" * 64
_LEAF = 42


def _write_sidecar(
    path: Path,
    *,
    runner=tess,
    sha: str = _SHA,
    leaf: int | None = _LEAF,
    failure_class=None,
    cache_version: str | None = None,
    include_version_key: bool = False,
) -> dict:
    """Write a minimal schema-valid sidecar; return the dict written.

    By default the sidecar has NO runner_cache_version key (the legacy shape).
    Pass include_version_key=True with cache_version to write the key explicitly.
    """
    extras: dict = {"engine_version": "tesseract-5.5.0"}
    if failure_class is not None:
        extras["failure_class"] = failure_class
    else:
        extras["failure_class"] = None
    if include_version_key:
        extras["runner_cache_version"] = cache_version
    record = {
        "schema_version": "sidecar-page-v1",
        "manifest_id": "sm-sha256:" + "b" * 64,
        "rendering_id": runner.RENDERING_ID,
        "page_native_id": "page_0001",
        "page_sequence": 1,
        "page_dimensions_native": {"width": 100, "height": 100, "unit": "pixel"},
        "blocks": [],
        "parsed_keys_index": [],
        "canonical_leaf_id": leaf,
        "source_payload_sha256": sha,
        "page_extras_carried": extras,
        "page_extras_carried_keys": sorted(extras),
        "page_extras_jcs_sha256": runner._extras_hash(extras),
        "edition_page_key": body_edition_key(leaf if leaf is not None else 1),
    }
    runner._validate("sidecar-page-v1", record)
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    return record


def test_classify_missing_sidecar(tmp_path: Path) -> None:
    p = tmp_path / "page_0001.json"
    status = stamp.classify_sidecar(
        p, canonical_leaf_id=_LEAF, source_payload_sha256=_SHA, runner=tess
    )
    assert status == "missing"


def test_classify_none_version_otherwise_current_is_stamp(tmp_path: Path) -> None:
    p = tmp_path / "page_0001.json"
    _write_sidecar(p)  # legacy: no runner_cache_version key
    # Precondition: the runner gate currently REJECTS it (the bug we fix).
    assert not tess._sidecar_is_done(
        p, canonical_leaf_id=_LEAF, source_payload_sha256=_SHA
    )
    status = stamp.classify_sidecar(
        p, canonical_leaf_id=_LEAF, source_payload_sha256=_SHA, runner=tess
    )
    assert status == "stamp"


def test_classify_already_current_is_not_stamped(tmp_path: Path) -> None:
    p = tmp_path / "page_0001.json"
    _write_sidecar(
        p,
        include_version_key=True,
        cache_version=tess.S1_SIDECAR_CACHE_VERSION,
    )
    assert tess._sidecar_is_done(
        p, canonical_leaf_id=_LEAF, source_payload_sha256=_SHA
    )
    status = stamp.classify_sidecar(
        p, canonical_leaf_id=_LEAF, source_payload_sha256=_SHA, runner=tess
    )
    assert status == "already_current"


def test_classify_failure_class_is_skip_not_current(tmp_path: Path) -> None:
    p = tmp_path / "page_0001.json"
    _write_sidecar(p, failure_class="ocr_timeout")
    status = stamp.classify_sidecar(
        p, canonical_leaf_id=_LEAF, source_payload_sha256=_SHA, runner=tess
    )
    assert status == "skip_not_current"


def test_classify_sha_mismatch_is_skip_not_current(tmp_path: Path) -> None:
    p = tmp_path / "page_0001.json"
    _write_sidecar(p, sha="sha256:" + "c" * 64)  # sidecar sha != current image sha
    status = stamp.classify_sidecar(
        p, canonical_leaf_id=_LEAF, source_payload_sha256=_SHA, runner=tess
    )
    assert status == "skip_not_current"


def test_classify_leaf_mismatch_is_skip_not_current(tmp_path: Path) -> None:
    p = tmp_path / "page_0001.json"
    _write_sidecar(p, leaf=7)  # sidecar leaf != current leaf
    status = stamp.classify_sidecar(
        p, canonical_leaf_id=_LEAF, source_payload_sha256=_SHA, runner=tess
    )
    assert status == "skip_not_current"


def test_stamp_sidecar_makes_it_current(tmp_path: Path) -> None:
    p = tmp_path / "page_0001.json"
    _write_sidecar(p)
    stamp.stamp_sidecar(p, runner=tess)
    # Post-condition: the runner's own gate now accepts the sidecar.
    assert tess._sidecar_is_done(
        p, canonical_leaf_id=_LEAF, source_payload_sha256=_SHA
    )


def test_stamp_sidecar_recomputes_extras_integrity(tmp_path: Path) -> None:
    p = tmp_path / "page_0001.json"
    _write_sidecar(p)
    stamp.stamp_sidecar(p, runner=tess)
    data = json.loads(p.read_text(encoding="utf-8"))
    extras = data["page_extras_carried"]
    assert extras["runner_cache_version"] == tess.S1_SIDECAR_CACHE_VERSION
    # The integrity fields must match the new extras, else the sidecar is
    # internally inconsistent and downstream validation breaks.
    assert data["page_extras_carried_keys"] == sorted(extras)
    assert data["page_extras_jcs_sha256"] == tess._extras_hash(extras)
    # And it must still validate against the schema.
    tess._validate("sidecar-page-v1", data)


def test_stamp_sidecar_is_idempotent(tmp_path: Path) -> None:
    p = tmp_path / "page_0001.json"
    _write_sidecar(p)
    stamp.stamp_sidecar(p, runner=tess)
    first = p.read_bytes()
    # Re-stamping an already-current sidecar must be a no-op on disk.
    stamp.stamp_sidecar(p, runner=tess)
    assert p.read_bytes() == first
