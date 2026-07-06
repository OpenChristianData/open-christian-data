import json
from pathlib import Path

import jsonschema
import pytest

from build.tools.ocr_pipeline.discard_frontback_leaves import (
    BodyDiscardError,
    process_volumes,
)


REPO_ROOT = Path(__file__).parents[1]


def _manifest(leaves: list[dict], volume: int = 1) -> dict:
    return {
        "ia_item_id": "testitem",
        "ia_derivative_type": "Single Page Processed JP2 ZIP",
        "volume": volume,
        "created_at": "2026-01-01T00:00:00+00:00",
        "page_count": sum(1 for leaf in leaves if leaf.get("kind") == "body"),
        "leaves": leaves,
    }


def _present_leaf(leaf_num: int, kind: str = "front_matter") -> dict:
    return {
        "leaf_num": leaf_num,
        "page_num": None if kind != "body" else 1,
        "kind": kind,
        "image_state": "present",
        "local_path": f"raw/internet-archive/schaff-herzog-pages/vol_01/leaf_{leaf_num:04d}.jpg",
        "ia_leaf_id": f"{leaf_num:04d}",
        "ia_filename": f"testitem_jp2.zip/testitem_jp2/testitem_{leaf_num:04d}.jp2",
        "ia_item_id": "testitem",
        "sha256": "sha256:" + "a" * 64,
        "fetched_at": "2026-01-01T00:00:00+00:00",
        "image_mode": "RGB",
        "image_size": [100, 150],
    }


def _write_manifest(root: Path, manifest: dict, volume: int = 1) -> Path:
    path = root / "raw" / "internet-archive" / "schaff-herzog-pages" / f"vol_{volume:02d}.manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_blank_frontback_leaf_records_blank_without_recycle(tmp_path: Path) -> None:
    manifest_path = _write_manifest(
        tmp_path,
        _manifest([
            {"leaf_num": 0, "page_num": None, "kind": "front_matter", "image_state": "not_imaged"},
            {"leaf_num": 9, "page_num": 1, "kind": "body", "image_state": "present"},
        ]),
    )
    recycled: list[Path] = []

    result = process_volumes(tmp_path, volumes=[1], apply=True, recycle_func=recycled.append)

    leaf = _read(manifest_path)["leaves"][0]
    assert leaf["blank"] is True
    assert leaf["kind"] == "front_matter"
    assert leaf["image_state"] == "not_imaged"
    assert recycled == []
    assert result[0].record_blanks == 1


def test_present_junk_leaf_discards_recycles_and_removes_only_matching_sidecar(tmp_path: Path) -> None:
    leaf = _present_leaf(0)
    manifest_path = _write_manifest(tmp_path, _manifest([leaf, {
        "leaf_num": 9,
        "page_num": 1,
        "kind": "body",
        "image_state": "present",
    }]))
    image_path = tmp_path / leaf["local_path"]
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(b"jpg")
    sidecar_dir = tmp_path / "reports" / "s1-sidecars" / "lineage-a" / "vol_01" / "pages"
    sidecar_dir.mkdir(parents=True)
    (sidecar_dir / "leaf_0000.json").write_text("{}", encoding="utf-8")
    page_sidecar = sidecar_dir / "page_0000.json"
    page_sidecar.write_text("{}", encoding="utf-8")
    recycled: list[Path] = []

    result = process_volumes(tmp_path, volumes=[1], apply=True, recycle_func=recycled.append)

    discarded = _read(manifest_path)["leaves"][0]
    assert discarded["kind"] == "discarded"
    assert discarded["discard_reason"] == "non-content-frontback"
    assert discarded["image_state"] == "discarded"
    assert "local_path" not in discarded
    assert discarded["sha256"] == leaf["sha256"]
    assert discarded["ia_leaf_id"] == leaf["ia_leaf_id"]
    assert discarded["ia_item_id"] == leaf["ia_item_id"]
    assert discarded["ia_filename"] == leaf["ia_filename"]
    assert recycled == [image_path]
    assert not (sidecar_dir / "leaf_0000.json").exists()
    assert page_sidecar.exists()
    assert result[0].discards == 1


def test_body_leaf_in_junk_range_raises(tmp_path: Path) -> None:
    _write_manifest(tmp_path, _manifest([_present_leaf(0, kind="body")]))

    with pytest.raises(BodyDiscardError):
        process_volumes(tmp_path, volumes=[1], apply=True, recycle_func=lambda path: None)


def test_second_apply_is_noop_without_second_recycle_or_byte_change(tmp_path: Path) -> None:
    leaf = _present_leaf(0)
    manifest_path = _write_manifest(tmp_path, _manifest([leaf]))
    image_path = tmp_path / leaf["local_path"]
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(b"jpg")
    recycled: list[Path] = []

    process_volumes(tmp_path, volumes=[1], apply=True, recycle_func=recycled.append)
    first_bytes = manifest_path.read_bytes()
    process_volumes(tmp_path, volumes=[1], apply=True, recycle_func=recycled.append)

    assert recycled == [image_path]
    assert manifest_path.read_bytes() == first_bytes


def test_output_manifest_validates_against_source_manifest_schema(tmp_path: Path) -> None:
    leaf = _present_leaf(0)
    manifest_path = _write_manifest(tmp_path, _manifest([leaf]))
    image_path = tmp_path / leaf["local_path"]
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(b"jpg")

    process_volumes(tmp_path, volumes=[1], apply=True, recycle_func=lambda path: None)

    schema = json.loads((REPO_ROOT / "schemas" / "v1" / "source_manifest.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(instance=_read(manifest_path), schema=schema)
