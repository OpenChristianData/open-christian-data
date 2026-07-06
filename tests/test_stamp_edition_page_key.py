from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from build.tools.ocr_pipeline import stamp_edition_page_key as stamp

ZERO_SHA = "sha256:" + "0" * 64


class FakeRunner:
    SOURCE_LINEAGE_ID = "fake-live-v1"
    RENDERING_ID = "fake-live-v1/schaff/encyclopedia/1908-1914/v1"

    @staticmethod
    def _prefixed_sha256_bytes(payload: bytes) -> str:
        return "sha256:" + hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _image_paths(input_root: Path, volume: int) -> list[Path]:
        return sorted((input_root / f"vol_{volume:02d}").glob("*.jpg"))

    @staticmethod
    def _normal_manifest_paths(output_root: Path, source_lineage_id: str, volume: int):
        run_dir = output_root / source_lineage_id / f"vol_{volume:02d}"
        return run_dir / "manifest.json", run_dir / "manifest.state.json", run_dir / "pages"

    @staticmethod
    def _load_source_manifest(input_root: Path, volume: int) -> dict[str, Any] | None:
        path = input_root / f"vol_{volume:02d}.manifest.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _validate(schema_name: str, record: dict[str, Any]) -> None:
        schema = json.loads((Path("schemas/v1") / f"{schema_name}.schema.json").read_text(encoding="utf-8"))
        jsonschema.validate(instance=record, schema=schema)


def _write_image(root: Path, volume: int, stem: str, payload: bytes) -> str:
    image_dir = root / f"vol_{volume:02d}"
    image_dir.mkdir(parents=True, exist_ok=True)
    path = image_dir / f"{stem}.jpg"
    path.write_bytes(payload)
    return FakeRunner._prefixed_sha256_bytes(payload)


def _write_manifest(input_root: Path, volume: int, *, body_sha: str, gap_sha: str, unresolved_sha: str) -> None:
    manifest = {
        "schema_version": "source_manifest-v1",
        "leaves": [
            {
                "leaf_num": 101,
                "page_num": 37,
                "kind": "body",
                "image_state": "present",
                "sha256": body_sha,
            },
            {
                "leaf_num": 102,
                "page_num": None,
                "kind": "front_matter",
                "image_state": "present",
                "sha256": unresolved_sha,
            },
        ],
        "gaps": [
            {
                "page_num": 96,
                "sha256": gap_sha,
                "status": "recovered",
            }
        ],
    }
    (input_root / f"vol_{volume:02d}.manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )


def _sidecar_path(s1_root: Path, volume: int, stem: str) -> Path:
    return (
        s1_root
        / FakeRunner.SOURCE_LINEAGE_ID
        / f"vol_{volume:02d}"
        / "pages"
        / f"{stem}.json"
    )


def _write_sidecar(
    s1_root: Path,
    volume: int,
    stem: str,
    *,
    sha: str,
    leaf: int | None,
    clid_exempt: bool = False,
    edition_page_key: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "schema_version": "sidecar-page-v1",
        "manifest_id": "sm-sha256:" + "b" * 64,
        "rendering_id": FakeRunner.RENDERING_ID,
        "page_native_id": stem,
        "page_sequence": 1,
        "page_dimensions_native": {"width": 100, "height": 100, "unit": "pixel"},
        "blocks": [{"block_id": "b1", "block_type": "text", "lines": [], "bbox_native": None}],
        "parsed_keys_index": [],
        "page_extras_carried": {"engine_version": "fake-1"},
        "page_extras_carried_keys": ["engine_version"],
        "page_extras_jcs_sha256": ZERO_SHA,
        "source_payload_sha256": sha,
    }
    if leaf is not None:
        record["canonical_leaf_id"] = leaf
    if clid_exempt:
        record["clid_exempt"] = True
    if edition_page_key is not None:
        record["edition_page_key"] = edition_page_key
    # The stamp tool exists to backfill edition_page_key onto legacy sidecars that
    # predate the now-required field, so a key-less input is intentionally
    # schema-old here -- only validate when the record already carries the key.
    if edition_page_key is not None:
        FakeRunner._validate("sidecar-page-v1", record)
    path = _sidecar_path(s1_root, volume, stem)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    return record


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_recovered_gap_sidecar_gets_key_and_only_key_changes(tmp_path: Path) -> None:
    input_root = tmp_path / "raw"
    s1_root = tmp_path / "reports" / "s1-sidecars"
    body_sha = _write_image(input_root, 1, "page_0037", b"body")
    gap_sha = _write_image(input_root, 1, "page_0096", b"gap")
    unresolved_sha = _write_image(input_root, 1, "page_9999", b"front")
    _write_manifest(input_root, 1, body_sha=body_sha, gap_sha=gap_sha, unresolved_sha=unresolved_sha)
    before = _write_sidecar(
        s1_root,
        1,
        "page_0096",
        sha=gap_sha,
        leaf=None,
        clid_exempt=True,
    )

    counts = stamp.stamp_volume(FakeRunner, 1, input_root=input_root, s1_root=s1_root, apply=True)

    after = _read(_sidecar_path(s1_root, 1, "page_0096"))
    assert counts["stamped"] == 1
    assert after["edition_page_key"] == {"section": "body", "anchor": 96, "ordinal": 0}
    for field in ("blocks", "source_payload_sha256", "clid_exempt", "page_extras_carried"):
        assert after[field] == before[field]
    assert after.get("canonical_leaf_id") == before.get("canonical_leaf_id")
    without_key = dict(after)
    without_key.pop("edition_page_key")
    assert without_key == before


def test_normal_body_sidecar_gets_body_key(tmp_path: Path) -> None:
    input_root = tmp_path / "raw"
    s1_root = tmp_path / "reports" / "s1-sidecars"
    body_sha = _write_image(input_root, 1, "page_0037", b"body")
    gap_sha = _write_image(input_root, 1, "page_0096", b"gap")
    unresolved_sha = _write_image(input_root, 1, "page_9999", b"front")
    _write_manifest(input_root, 1, body_sha=body_sha, gap_sha=gap_sha, unresolved_sha=unresolved_sha)
    _write_sidecar(s1_root, 1, "page_0037", sha=body_sha, leaf=101)

    counts = stamp.stamp_volume(FakeRunner, 1, input_root=input_root, s1_root=s1_root, apply=True)

    assert counts["stamped"] == 1
    assert _read(_sidecar_path(s1_root, 1, "page_0037"))["edition_page_key"] == {
        "section": "body",
        "anchor": 37,
        "ordinal": 0,
    }


def test_second_apply_is_idempotent_and_stamps_zero(tmp_path: Path) -> None:
    input_root = tmp_path / "raw"
    s1_root = tmp_path / "reports" / "s1-sidecars"
    body_sha = _write_image(input_root, 1, "page_0037", b"body")
    gap_sha = _write_image(input_root, 1, "page_0096", b"gap")
    unresolved_sha = _write_image(input_root, 1, "page_9999", b"front")
    _write_manifest(input_root, 1, body_sha=body_sha, gap_sha=gap_sha, unresolved_sha=unresolved_sha)
    _write_sidecar(s1_root, 1, "page_0037", sha=body_sha, leaf=101)

    first = stamp.stamp_volume(FakeRunner, 1, input_root=input_root, s1_root=s1_root, apply=True)
    path = _sidecar_path(s1_root, 1, "page_0037")
    bytes_after_first = path.read_bytes()
    second = stamp.stamp_volume(FakeRunner, 1, input_root=input_root, s1_root=s1_root, apply=True)

    assert first["stamped"] == 1
    assert second["stamped"] == 0
    assert second["already_keyed"] == 1
    assert path.read_bytes() == bytes_after_first


def test_unresolved_sidecar_is_left_untouched(tmp_path: Path) -> None:
    input_root = tmp_path / "raw"
    s1_root = tmp_path / "reports" / "s1-sidecars"
    body_sha = _write_image(input_root, 1, "page_0037", b"body")
    gap_sha = _write_image(input_root, 1, "page_0096", b"gap")
    unresolved_sha = _write_image(input_root, 1, "page_9999", b"front")
    _write_manifest(input_root, 1, body_sha=body_sha, gap_sha=gap_sha, unresolved_sha=unresolved_sha)
    before = _write_sidecar(s1_root, 1, "page_9999", sha=unresolved_sha, leaf=None, clid_exempt=True)

    counts = stamp.stamp_volume(FakeRunner, 1, input_root=input_root, s1_root=s1_root, apply=True)

    after = _read(_sidecar_path(s1_root, 1, "page_9999"))
    assert counts["unresolved"] == 1
    assert "edition_page_key" not in after
    assert after == before


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    input_root = tmp_path / "raw"
    s1_root = tmp_path / "reports" / "s1-sidecars"
    body_sha = _write_image(input_root, 1, "page_0037", b"body")
    gap_sha = _write_image(input_root, 1, "page_0096", b"gap")
    unresolved_sha = _write_image(input_root, 1, "page_9999", b"front")
    _write_manifest(input_root, 1, body_sha=body_sha, gap_sha=gap_sha, unresolved_sha=unresolved_sha)
    _write_sidecar(s1_root, 1, "page_0037", sha=body_sha, leaf=101)
    path = _sidecar_path(s1_root, 1, "page_0037")
    before = path.read_bytes()

    counts = stamp.stamp_volume(FakeRunner, 1, input_root=input_root, s1_root=s1_root, apply=False)

    assert counts["stamped"] == 1
    assert path.read_bytes() == before
    assert "edition_page_key" not in _read(path)


def test_different_existing_key_without_force_raises_and_does_not_modify(tmp_path: Path) -> None:
    input_root = tmp_path / "raw"
    s1_root = tmp_path / "reports" / "s1-sidecars"
    body_sha = _write_image(input_root, 1, "page_0037", b"body")
    gap_sha = _write_image(input_root, 1, "page_0096", b"gap")
    unresolved_sha = _write_image(input_root, 1, "page_9999", b"front")
    _write_manifest(input_root, 1, body_sha=body_sha, gap_sha=gap_sha, unresolved_sha=unresolved_sha)
    wrong_key = {"section": "body", "anchor": 999, "ordinal": 0}
    _write_sidecar(s1_root, 1, "page_0037", sha=body_sha, leaf=101, edition_page_key=wrong_key)
    path = _sidecar_path(s1_root, 1, "page_0037")
    before = path.read_bytes()

    with pytest.raises(ValueError, match="refusing to rekey without --force-rekey"):
        stamp.stamp_volume(FakeRunner, 1, input_root=input_root, s1_root=s1_root, apply=True)

    assert path.read_bytes() == before
    assert _read(path)["edition_page_key"] == wrong_key
