from __future__ import annotations

import json
from pathlib import Path

import pytest

from build.lib.edition_page_key import body_edition_key
from build.lib.nsh_leaf_model import set_leaf_or_exempt
from build.parsers import s1_abbyy_normalizer as A
from build.parsers import s1_tesseract_runner as R
from build.tools.ocr_pipeline import reindex_manifest


VOLUME = 1


def _read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")


def _make_image(input_root: Path, stem: str) -> Path:
    image_path = input_root / "vol_01" / f"{stem}.jpg"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(f"image bytes for {stem}".encode("utf-8"))
    return image_path


def _make_sidecar(
    *,
    pages_dir: Path,
    image_path: Path,
    page_sequence: int,
    failure_class: str | None = None,
    canonical_leaf_id: int | None = None,
    edition_page_key: dict | None = None,
) -> None:
    extras = {"engine_version": "test-engine-1"}
    parsed_keys_index = [
        {
            "key": "engine_version",
            "handling": "extras_carried",
            "source_path": "subprocess.engine_version",
        }
    ]
    if failure_class:
        extras["failure_class"] = failure_class
        parsed_keys_index.append(
            {
                "key": "failure_class",
                "handling": "diagnostic_only",
                "source_path": "subprocess.failure_class",
            }
        )
    record = {
        "schema_version": "sidecar-page-v1",
        "manifest_id": "sm-sha256:" + "0" * 64,
        "rendering_id": R.RENDERING_ID,
        "page_native_id": image_path.stem,
        "page_sequence": page_sequence,
        "page_dimensions_native": {"width": 100, "height": 200, "unit": "pixel"},
        "blocks": [],
        "parsed_keys_index": sorted(parsed_keys_index, key=lambda item: item["key"]),
        "page_extras_carried": extras,
        "page_extras_carried_keys": sorted(extras),
        "page_extras_jcs_sha256": R._extras_hash(extras),
        "source_payload_sha256": R._prefixed_sha256_bytes(image_path.read_bytes()),
    }
    # R5: a body sidecar carries the int leaf; a leaf-less (non-body) sidecar is
    # marked clid_exempt so it satisfies the required-or-exempt schema.
    set_leaf_or_exempt(record, canonical_leaf_id)
    # edition_page_key is now schema-required on every sidecar-page-v1 record.
    # Use the caller-supplied key when given; otherwise synthesize a body key
    # anchored on the leaf (or page_sequence when leaf-less) so the hand-built
    # fixture validates.
    if edition_page_key is None:
        edition_page_key = body_edition_key(
            canonical_leaf_id if canonical_leaf_id is not None else page_sequence
        )
    record["edition_page_key"] = edition_page_key
    R._validate("sidecar-page-v1", record)
    _write_json(pages_dir / f"{image_path.stem}.json", record)


@pytest.fixture()
def synthetic_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    input_root = tmp_path / "raw" / "pages"
    output_root = tmp_path / "reports" / "s1-sidecars"
    monkeypatch.setattr(R, "DEFAULT_INPUT_ROOT", input_root)
    monkeypatch.setattr(R, "DEFAULT_OUTPUT_ROOT", output_root)
    monkeypatch.setattr(R, "REPO_ROOT", tmp_path)
    return tmp_path, input_root, output_root


def _seed_pages(
    input_root: Path,
    output_root: Path,
    *,
    count: int,
    failed: set[int] | None = None,
    leaf_ids: dict[int, int] | None = None,
) -> tuple[Path, Path, Path]:
    manifest_path, state_path, pages_dir = R._normal_manifest_paths(
        output_root, R.SOURCE_LINEAGE_ID, VOLUME
    )
    failed = failed or set()
    leaf_ids = leaf_ids or {}
    for sequence in range(1, count + 1):
        stem = f"page_{sequence:04d}"
        image_path = _make_image(input_root, stem)
        _make_sidecar(
            pages_dir=pages_dir,
            image_path=image_path,
            page_sequence=sequence,
            failure_class="subprocess_error" if sequence in failed else None,
            canonical_leaf_id=leaf_ids.get(sequence),
        )
    return manifest_path, state_path, pages_dir


def test_reindex_covers_all_disk_sidecars(synthetic_roots: tuple[Path, Path, Path]) -> None:
    _, input_root, output_root = synthetic_roots
    manifest_path, state_path, _ = _seed_pages(input_root, output_root, count=5)
    _write_json(manifest_path, {"pages": []})
    _write_json(state_path, {"emitted_pages": []})

    assert reindex_manifest.main(["--engine", "tesseract", "--volume", "1"]) == 0

    manifest = _read_json(manifest_path)
    state = _read_json(state_path)
    assert len(manifest["pages"]) == 5
    assert state["emitted_pages"] == [f"page_{sequence:04d}" for sequence in range(1, 6)]


def test_reindex_propagates_canonical_leaf_id(
    synthetic_roots: tuple[Path, Path, Path],
) -> None:
    # render_s2 reads canonical_leaf_id ONLY from the manifest page_ref (no sidecar
    # fallback), so reindex MUST copy the leaf coordinate off the sidecar; otherwise
    # the next S2 render silently un-leaf-keys every page.
    _, input_root, output_root = synthetic_roots
    manifest_path, _, _ = _seed_pages(
        input_root, output_root, count=3, leaf_ids={1: 100, 2: 101, 3: 102}
    )

    assert reindex_manifest.main(["--engine", "tesseract", "--volume", "1"]) == 0

    manifest = _read_json(manifest_path)
    leaf_by_native = {
        page["page_native_id"]: page.get("canonical_leaf_id") for page in manifest["pages"]
    }
    assert leaf_by_native == {
        "page_0001": 100,
        "page_0002": 101,
        "page_0003": 102,
    }


def test_reindex_propagates_edition_page_key(
    synthetic_roots: tuple[Path, Path, Path],
) -> None:
    _, input_root, output_root = synthetic_roots
    manifest_path, _, pages_dir = _seed_pages(input_root, output_root, count=1)
    image_path = input_root / "vol_01" / "page_0001.jpg"
    key = {"section": "body", "anchor": 7, "ordinal": 0}
    _make_sidecar(
        pages_dir=pages_dir,
        image_path=image_path,
        page_sequence=1,
        canonical_leaf_id=100,
        edition_page_key=key,
    )

    assert reindex_manifest.main(["--engine", "tesseract", "--volume", "1"]) == 0

    manifest = _read_json(manifest_path)
    assert manifest["pages"][0]["edition_page_key"] == key


def test_reindex_tolerates_sidecar_without_canonical_leaf_id(
    synthetic_roots: tuple[Path, Path, Path],
) -> None:
    # A sidecar that predates leaf-keying carries no canonical_leaf_id; reindex must
    # not invent one and must not crash. The page_ref simply omits the key.
    _, input_root, output_root = synthetic_roots
    manifest_path, _, _ = _seed_pages(
        input_root, output_root, count=2, leaf_ids={1: 200}
    )

    assert reindex_manifest.main(["--engine", "tesseract", "--volume", "1"]) == 0

    manifest = _read_json(manifest_path)
    page_one = next(p for p in manifest["pages"] if p["page_native_id"] == "page_0001")
    page_two = next(p for p in manifest["pages"] if p["page_native_id"] == "page_0002")
    assert page_one.get("canonical_leaf_id") == 200
    assert "canonical_leaf_id" not in page_two


def test_reindex_includes_extra_disk_sidecar_without_input_image(
    synthetic_roots: tuple[Path, Path, Path],
) -> None:
    _, input_root, output_root = synthetic_roots
    manifest_path, state_path, pages_dir = _seed_pages(input_root, output_root, count=2)
    extra_image = input_root / "vol_01" / "page_0003.jpg"
    extra_image.write_bytes(b"image bytes for extra sidecar")
    _make_sidecar(pages_dir=pages_dir, image_path=extra_image, page_sequence=3)
    extra_image.unlink()

    assert reindex_manifest.main(["--engine", "tesseract", "--volume", "1"]) == 0

    manifest = _read_json(manifest_path)
    state = _read_json(state_path)
    assert [page["page_native_id"] for page in manifest["pages"]] == [
        "page_0001",
        "page_0002",
        "page_0003",
    ]
    assert state["emitted_pages"] == ["page_0001", "page_0002", "page_0003"]


def test_reindex_rejects_distinct_sidecar_files_with_same_native_id(
    synthetic_roots: tuple[Path, Path, Path],
) -> None:
    _, input_root, output_root = synthetic_roots
    _, _, pages_dir = _seed_pages(input_root, output_root, count=1)
    duplicate_image = input_root / "vol_01" / "leaf_0001.jpg"
    duplicate_image.write_bytes(b"image bytes for page_0001")
    _make_sidecar(pages_dir=pages_dir, image_path=duplicate_image, page_sequence=1)
    duplicate_page = _read_json(pages_dir / "leaf_0001.json")
    duplicate_page["page_native_id"] = "page_0001"
    _write_json(pages_dir / "leaf_0001.json", duplicate_page)
    duplicate_image.unlink()

    with pytest.raises(ValueError, match="duplicate page_native_id 'page_0001'"):
        reindex_manifest.main(["--engine", "tesseract", "--volume", "1"])


def test_failed_sidecar_excluded_from_emitted_but_in_pages(
    synthetic_roots: tuple[Path, Path, Path],
) -> None:
    _, input_root, output_root = synthetic_roots
    manifest_path, state_path, _ = _seed_pages(input_root, output_root, count=3, failed={2})

    assert reindex_manifest.main(["--engine", "tesseract", "--volume", "1"]) == 0

    manifest = _read_json(manifest_path)
    state = _read_json(state_path)
    failed_page = next(page for page in manifest["pages"] if page["page_native_id"] == "page_0002")
    assert failed_page["status"] == "corrupt"
    assert failed_page["failure_class"] == "subprocess_error"
    assert "page_0002" not in state["emitted_pages"]
    assert manifest["manifest_cross_check"]["samples_inconclusive"] == 1


def test_reindexed_manifest_is_schema_valid(synthetic_roots: tuple[Path, Path, Path]) -> None:
    _, input_root, output_root = synthetic_roots
    manifest_path, _, _ = _seed_pages(input_root, output_root, count=2)

    assert reindex_manifest.main(["--engine", "tesseract", "--volume", "1"]) == 0

    R._validate("sidecar-manifest-v1", _read_json(manifest_path))


def test_idempotent(synthetic_roots: tuple[Path, Path, Path]) -> None:
    _, input_root, output_root = synthetic_roots
    manifest_path, state_path, _ = _seed_pages(input_root, output_root, count=4)

    assert reindex_manifest.main(["--engine", "tesseract", "--volume", "1"]) == 0
    first_manifest_pages = _read_json(manifest_path)["pages"]
    first_emitted_pages = _read_json(state_path)["emitted_pages"]
    assert reindex_manifest.main(["--engine", "tesseract", "--volume", "1"]) == 0

    assert _read_json(manifest_path)["pages"] == first_manifest_pages
    assert _read_json(state_path)["emitted_pages"] == first_emitted_pages


def test_no_pending_after_reindex(synthetic_roots: tuple[Path, Path, Path]) -> None:
    _, input_root, output_root = synthetic_roots
    _, state_path, pages_dir = _seed_pages(input_root, output_root, count=5)

    assert reindex_manifest.main(["--engine", "tesseract", "--volume", "1"]) == 0

    state = _read_json(state_path)
    already_done = set(state["emitted_pages"])
    pending = [
        image_path.stem
        for image_path in R._image_paths(input_root, VOLUME)
        if not (image_path.stem in already_done and (pages_dir / f"{image_path.stem}.json").exists())
    ]
    assert pending == []


def test_dry_run_writes_nothing(synthetic_roots: tuple[Path, Path, Path]) -> None:
    _, input_root, output_root = synthetic_roots
    manifest_path, state_path, _ = _seed_pages(input_root, output_root, count=3)
    _write_json(manifest_path, {"pages": [{"page_native_id": "page_0001"}]})
    _write_json(state_path, {"emitted_pages": ["page_0001"]})
    old_manifest = manifest_path.read_bytes()
    old_state = state_path.read_bytes()

    assert reindex_manifest.main(["--engine", "tesseract", "--volume", "1", "--dry-run"]) == 0

    assert manifest_path.read_bytes() == old_manifest
    assert state_path.read_bytes() == old_state


def test_missing_sidecar_warned(
    synthetic_roots: tuple[Path, Path, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, input_root, output_root = synthetic_roots
    manifest_path, state_path, _ = _seed_pages(input_root, output_root, count=2)
    _make_image(input_root, "page_0003")

    assert reindex_manifest.main(["--engine", "tesseract", "--volume", "1"]) == 0

    captured = capsys.readouterr()
    assert "WARNING" in captured.out
    assert "page_0003" in captured.out
    manifest = _read_json(manifest_path)
    state = _read_json(state_path)
    assert [page["page_native_id"] for page in manifest["pages"]] == ["page_0001", "page_0002"]
    assert state["emitted_pages"] == ["page_0001", "page_0002"]


def test_lineage_reindex_covers_imported_abbyy_sidecars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_root = tmp_path / "reports" / "s1-sidecars"
    monkeypatch.setattr(A, "DEFAULT_OUTPUT_ROOT", output_root)
    monkeypatch.setattr(A, "REPO_ROOT", tmp_path)

    lineage = "ia-abbyy-v1"
    manifest_path, state_path, pages_dir = A._normal_manifest_paths(output_root, lineage, VOLUME)
    rendering_id = f"{lineage}/schaff/encyclopedia/1908-1914/v1"
    for sequence in range(1, 4):
        page_native_id = f"page_{sequence:04d}"
        sidecar = {
            "schema_version": "sidecar-page-v1",
            "manifest_id": "sm-sha256:" + "1" * 64,
            "rendering_id": rendering_id,
            "page_native_id": page_native_id,
            "page_sequence": sequence,
            "page_dimensions_native": {"width": 100, "height": 200, "unit": "pixel"},
            "blocks": [],
            "parsed_keys_index": [],
            "page_extras_carried": {"engine_version": "abbyy-test"},
            "page_extras_carried_keys": ["engine_version"],
            "page_extras_jcs_sha256": A._extras_hash({"engine_version": "abbyy-test"}),
            "source_payload_sha256": "sha256:" + str(sequence) * 64,
            "edition_page_key": body_edition_key(sequence),
        }
        _write_json(pages_dir / f"{page_native_id}.json", sidecar)

    _write_json(
        manifest_path,
        {
            "schema_version": "sidecar-manifest-v1",
            "manifest_id": "sm-sha256:" + "1" * 64,
            "work_id": A.WORK_ID,
            "edition_id": A.EDITION_ID,
            "volume": VOLUME,
            "rendering_id": rendering_id,
            "engine_family": "abbyy",
            "engine_version": "abbyy-test",
            "source_lineage_id": lineage,
            "source_files": [{"path": "source.json", "sha256": "sha256:" + "2" * 64}],
            "pages": [{"page_native_id": "page_0001"}],
            "manifest_cross_check": {
                "samples_checked": 1,
                "samples_matched": 1,
                "samples_inconclusive": 0,
                "failed_samples": [],
            },
            "bundle_extras_carried": {},
            "bundle_extras_carried_keys": [],
            "bundle_extras_jcs_sha256": A.EMPTY_EXTRAS_SHA256,
            "created_at": "2026-01-01T00:00:00Z",
        },
    )
    _write_json(state_path, {"manifest_id": "sm-sha256:" + "1" * 64, "emitted_pages": ["page_0001"]})

    assert reindex_manifest.main(["--lineage", lineage, "--volume", "1"]) == 0

    manifest = _read_json(manifest_path)
    state = _read_json(state_path)
    assert [page["page_native_id"] for page in manifest["pages"]] == [
        "page_0001",
        "page_0002",
        "page_0003",
    ]
    assert state["emitted_pages"] == ["page_0001", "page_0002", "page_0003"]


def test_all_lineages_reindexes_existing_abbyy_dirs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_root = tmp_path / "reports" / "s1-sidecars"
    monkeypatch.setattr(A, "DEFAULT_OUTPUT_ROOT", output_root)
    monkeypatch.setattr(A, "REPO_ROOT", tmp_path)

    for lineage in ("ia-abbyy-v1", "ia-abbyy-haucgoog-v1"):
        manifest_path, state_path, pages_dir = A._normal_manifest_paths(output_root, lineage, VOLUME)
        rendering_id = f"{lineage}/schaff/encyclopedia/1908-1914/v1"
        for sequence in range(1, 3):
            page_native_id = f"page_{sequence:04d}"
            sidecar = {
                "schema_version": "sidecar-page-v1",
                "manifest_id": "sm-sha256:" + "1" * 64,
                "rendering_id": rendering_id,
                "page_native_id": page_native_id,
                "page_sequence": sequence,
                "page_dimensions_native": {"width": 100, "height": 200, "unit": "pixel"},
                "blocks": [],
                "parsed_keys_index": [],
                "page_extras_carried": {"engine_version": "abbyy-test"},
                "page_extras_carried_keys": ["engine_version"],
                "page_extras_jcs_sha256": A._extras_hash({"engine_version": "abbyy-test"}),
                "source_payload_sha256": "sha256:" + str(sequence) * 64,
                "edition_page_key": body_edition_key(sequence),
            }
            _write_json(pages_dir / f"{page_native_id}.json", sidecar)
        _write_json(
            manifest_path,
            {
                "schema_version": "sidecar-manifest-v1",
                "manifest_id": "sm-sha256:" + "1" * 64,
                "work_id": A.WORK_ID,
                "edition_id": A.EDITION_ID,
                "volume": VOLUME,
                "rendering_id": rendering_id,
                "engine_family": "abbyy",
                "engine_version": "abbyy-test",
                "source_lineage_id": lineage,
                "source_files": [{"path": "source.json", "sha256": "sha256:" + "2" * 64}],
                "pages": [{"page_native_id": "page_0001"}],
                "manifest_cross_check": {
                    "samples_checked": 1,
                    "samples_matched": 1,
                    "samples_inconclusive": 0,
                    "failed_samples": [],
                },
                "bundle_extras_carried": {},
                "bundle_extras_carried_keys": [],
                "bundle_extras_jcs_sha256": A.EMPTY_EXTRAS_SHA256,
                "created_at": "2026-01-01T00:00:00Z",
            },
        )
        _write_json(state_path, {"manifest_id": "sm-sha256:" + "1" * 64, "emitted_pages": ["page_0001"]})

    assert reindex_manifest.main(["--all-lineages"]) == 0

    for lineage in ("ia-abbyy-v1", "ia-abbyy-haucgoog-v1"):
        manifest_path, state_path, _ = A._normal_manifest_paths(output_root, lineage, VOLUME)
        assert len(_read_json(manifest_path)["pages"]) == 2
        assert _read_json(state_path)["emitted_pages"] == ["page_0001", "page_0002"]
