"""Rebuild S1 OCR manifest indexes from sidecars already present on disk."""

from __future__ import annotations

import argparse
import importlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[3]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib.page_order import volume_duplicate_stems  # noqa: E402
from build.lib.nsh_leaf_model import set_leaf_or_exempt  # noqa: E402


ENGINE_MODULES = {
    "tesseract": "build.parsers.s1_tesseract_runner",
    "surya": "build.parsers.s1_surya_runner",
    "kraken": "build.parsers.s1_kraken_runner",
    "kraken-greek": "build.parsers.s1_kraken_greek_runner",
}

GENERIC_REINDEX_MODULE = "build.parsers.s1_abbyy_normalizer"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_runner(engine: str) -> ModuleType:
    try:
        module_name = ENGINE_MODULES[engine]
    except KeyError as exc:
        raise ValueError(f"Unknown engine: {engine}") from exc
    return importlib.import_module(module_name)


def _old_count(runner: ModuleType, path: Path, key: str) -> int:
    if not path.exists():
        return 0
    value = runner._read_json(path)
    items = value.get(key, []) if isinstance(value, dict) else []
    return len(items) if isinstance(items, list) else 0


def _remember_page_native_id(
    seen: dict[str, Path],
    page_native_id: str,
    page_path: Path,
    *,
    source_lineage_id: str,
    volume: int,
) -> None:
    previous_path = seen.get(page_native_id)
    if previous_path is not None:
        raise ValueError(
            f"duplicate page_native_id {page_native_id!r} for "
            f"{source_lineage_id} vol_{volume:02d}: {previous_path} and {page_path}"
        )
    seen[page_native_id] = page_path


def _page_ref_from_sidecar(
    runner: ModuleType,
    *,
    page_native_id: str,
    page_path: Path,
    sidecar: dict[str, Any],
    repo_root: Path,
) -> tuple[dict[str, Any], bool, str]:
    extras = sidecar.get("page_extras_carried", {})
    if not isinstance(extras, dict):
        extras = {}
    failure_class = extras.get("failure_class")
    page_ref = {
        "page_native_id": page_native_id,
        "page_sequence": sidecar["page_sequence"],
        "status": "corrupt" if failure_class else "eligible",
        "sidecar_page_path": runner._relative_path(page_path, repo_root),
        "source_payload_sha256": sidecar["source_payload_sha256"],
    }
    # Propagate the leaf coordinate the same way the migration does
    # (migrate_s1_to_leaf_key writes it onto every rebuilt page_ref). render_s2
    # reads canonical_leaf_id ONLY from the manifest page_ref (C5), so dropping it
    # here silently un-leaf-keys every rendering on the next S2 render even though
    # the sidecars still carry it.
    set_leaf_or_exempt(page_ref, sidecar.get("canonical_leaf_id"))
    if "edition_page_key" in sidecar:
        page_ref["edition_page_key"] = dict(sidecar["edition_page_key"])
    if failure_class:
        page_ref["failure_class"] = str(failure_class)
    engine_version = ""
    if not failure_class:
        engine_version = str(extras.get("engine_version") or "")
    return page_ref, bool(failure_class), engine_version


def _reindex_volume(engine: str, volume: int, *, dry_run: bool) -> int:
    runner = _load_runner(engine)
    manifest_path, state_path, pages_dir = runner._normal_manifest_paths(
        runner.DEFAULT_OUTPUT_ROOT,
        runner.SOURCE_LINEAGE_ID,
        volume,
    )
    images = runner._image_paths(runner.DEFAULT_INPUT_ROOT, volume)
    if not images:
        raise ValueError(f"No input images for vol_{volume:02d}")

    input_vol_dir = images[0].parent
    duplicate_stems = volume_duplicate_stems(input_vol_dir)

    source_files, source_file_sha256 = runner._source_files(images, runner.REPO_ROOT)
    manifest_id = runner._build_manifest_id(volume, source_file_sha256)

    page_refs_by_sidecar_stem: dict[str, dict[str, Any]] = {}
    seen_page_native_ids: dict[str, Path] = {}
    emitted_pages: set[str] = set()
    failed_pages = 0
    engine_version = ""
    missing: list[str] = []

    for image_path in images:
        page_path = pages_dir / f"{image_path.stem}.json"
        if not page_path.exists():
            missing.append(image_path.stem)
            continue
        sidecar = runner._read_json(page_path)
        page_native_id = str(sidecar.get("page_native_id") or image_path.stem)
        _remember_page_native_id(
            seen_page_native_ids,
            page_native_id,
            page_path,
            source_lineage_id=runner.SOURCE_LINEAGE_ID,
            volume=volume,
        )
        page_ref, failed, sidecar_engine_version = _page_ref_from_sidecar(
            runner,
            page_native_id=page_native_id,
            page_path=page_path,
            sidecar=sidecar,
            repo_root=runner.REPO_ROOT,
        )
        if failed:
            failed_pages += 1
        else:
            emitted_pages.add(page_native_id)
            if not engine_version:
                engine_version = sidecar_engine_version
        page_refs_by_sidecar_stem[image_path.stem] = page_ref

    for page_path in sorted(pages_dir.glob("*.json")):
        sidecar_stem = page_path.stem
        if sidecar_stem in page_refs_by_sidecar_stem:
            continue
        if sidecar_stem in duplicate_stems:
            continue  # orphaned sidecar for a duplicate-role image; skip
        sidecar = runner._read_json(page_path)
        page_native_id = str(sidecar.get("page_native_id") or page_path.stem)
        _remember_page_native_id(
            seen_page_native_ids,
            page_native_id,
            page_path,
            source_lineage_id=runner.SOURCE_LINEAGE_ID,
            volume=volume,
        )
        page_ref, failed, sidecar_engine_version = _page_ref_from_sidecar(
            runner,
            page_native_id=page_native_id,
            page_path=page_path,
            sidecar=sidecar,
            repo_root=runner.REPO_ROOT,
        )
        if failed:
            failed_pages += 1
        else:
            emitted_pages.add(page_native_id)
            if not engine_version:
                engine_version = sidecar_engine_version
        page_refs_by_sidecar_stem[sidecar_stem] = page_ref

    page_refs = sorted(
        page_refs_by_sidecar_stem.values(),
        key=lambda item: (
            int(item.get("page_sequence", 0)),
            str(item.get("sidecar_page_path", "")),
        ),
    )

    if missing:
        print(
            f"WARNING: {len(missing)} input image(s) have no sidecar: {missing[:10]}"
        )

    manifest = {
        "schema_version": "sidecar-manifest-v1",
        "manifest_id": manifest_id,
        "work_id": runner.WORK_ID,
        "edition_id": runner.EDITION_ID,
        "volume": volume,
        "rendering_id": runner.RENDERING_ID,
        "engine_family": runner.ENGINE_FAMILY,
        "engine_version": engine_version,
        "source_lineage_id": runner.SOURCE_LINEAGE_ID,
        "source_files": source_files,
        "pages": page_refs,
        "manifest_cross_check": {
            "samples_checked": 1 if page_refs else 0,
            "samples_matched": 1 if page_refs and not failed_pages else 0,
            "samples_inconclusive": failed_pages,
            "failed_samples": [],
        },
        "bundle_extras_carried": {},
        "bundle_extras_carried_keys": [],
        "bundle_extras_jcs_sha256": runner.EMPTY_EXTRAS_SHA256,
        "created_at": _utc_now(),
    }
    runner._validate("sidecar-manifest-v1", manifest)
    state = {
        "manifest_id": manifest_id,
        "emitted_pages": sorted(emitted_pages),
        "updated_at": _utc_now(),
    }

    print(
        f"{engine} vol_{volume:02d}: manifest pages "
        f"{_old_count(runner, manifest_path, 'pages')} -> {len(page_refs)}, "
        f"state emitted_pages "
        f"{_old_count(runner, state_path, 'emitted_pages')} -> {len(emitted_pages)}"
    )
    if not dry_run:
        runner._write_json(manifest_path, manifest)
        runner._write_json(state_path, state)

    print(
        f"{engine} vol_{volume:02d}: manifest pages={len(page_refs)} "
        f"emitted_pages={len(emitted_pages)} failed={failed_pages} "
        f"missing_sidecar={len(missing)}"
    )
    return 0


def _reindex_lineage(source_lineage_id: str, volume: int, *, dry_run: bool) -> int:
    runner = importlib.import_module(GENERIC_REINDEX_MODULE)
    manifest_path, state_path, pages_dir = runner._normal_manifest_paths(
        runner.DEFAULT_OUTPUT_ROOT,
        source_lineage_id,
        volume,
    )
    if not manifest_path.exists():
        raise FileNotFoundError(f"no manifest for {source_lineage_id} vol_{volume:02d}: {manifest_path}")
    if not pages_dir.exists():
        raise FileNotFoundError(f"no sidecar pages for {source_lineage_id} vol_{volume:02d}: {pages_dir}")

    old_manifest = runner._read_json(manifest_path)
    if not isinstance(old_manifest, dict):
        raise ValueError(f"invalid manifest object: {manifest_path}")

    page_refs: list[dict[str, Any]] = []
    seen_page_native_ids: dict[str, Path] = {}
    emitted_pages: set[str] = set()
    failed_pages = 0
    engine_version = str(old_manifest.get("engine_version") or "")

    for page_path in sorted(pages_dir.glob("*.json")):
        sidecar = runner._read_json(page_path)
        if not isinstance(sidecar, dict):
            raise ValueError(f"invalid sidecar object: {page_path}")
        page_native_id = str(sidecar.get("page_native_id") or page_path.stem)
        _remember_page_native_id(
            seen_page_native_ids,
            page_native_id,
            page_path,
            source_lineage_id=source_lineage_id,
            volume=volume,
        )
        extras = sidecar.get("page_extras_carried", {})
        if not isinstance(extras, dict):
            extras = {}
        failure_class = extras.get("failure_class")
        if not failure_class:
            emitted_pages.add(page_native_id)
            if not engine_version:
                engine_version = str(extras.get("engine_version") or "")
        else:
            failed_pages += 1
        page_ref = {
            "page_native_id": page_native_id,
            "page_sequence": sidecar["page_sequence"],
            "status": "corrupt" if failure_class else "eligible",
            "sidecar_page_path": runner._relative_path(page_path, runner.REPO_ROOT),
            "source_payload_sha256": sidecar["source_payload_sha256"],
        }
        set_leaf_or_exempt(page_ref, sidecar.get("canonical_leaf_id"))
        if "edition_page_key" in sidecar:
            page_ref["edition_page_key"] = dict(sidecar["edition_page_key"])
        if failure_class:
            page_ref["failure_class"] = str(failure_class)
        page_refs.append(page_ref)

    if not page_refs:
        raise ValueError(f"no sidecars found for {source_lineage_id} vol_{volume:02d}")

    manifest = dict(old_manifest)
    manifest.update(
        {
            "source_lineage_id": source_lineage_id,
            "engine_version": engine_version,
            "pages": page_refs,
            "manifest_cross_check": {
                "samples_checked": 1,
                "samples_matched": 1 if not failed_pages else 0,
                "samples_inconclusive": failed_pages,
                "failed_samples": [],
            },
            "created_at": _utc_now(),
        }
    )
    runner._validate("sidecar-manifest-v1", manifest)
    state = {
        "manifest_id": str(manifest["manifest_id"]),
        "emitted_pages": sorted(emitted_pages),
        "updated_at": _utc_now(),
    }

    print(
        f"{source_lineage_id} vol_{volume:02d}: manifest pages "
        f"{_old_count(runner, manifest_path, 'pages')} -> {len(page_refs)}, "
        f"state emitted_pages "
        f"{_old_count(runner, state_path, 'emitted_pages')} -> {len(emitted_pages)}"
    )
    if not dry_run:
        runner._write_json(manifest_path, manifest)
        runner._write_json(state_path, state)
    print(
        f"{source_lineage_id} vol_{volume:02d}: manifest pages={len(page_refs)} "
        f"emitted_pages={len(emitted_pages)} failed={failed_pages}"
    )
    return 0


def _existing_lineage_volumes(output_root: Path, lineage_prefix: str = "ia-abbyy-") -> list[tuple[str, int]]:
    pairs: list[tuple[str, int]] = []
    if not output_root.exists():
        return pairs
    for lineage_dir in sorted(path for path in output_root.iterdir() if path.is_dir()):
        if not lineage_dir.name.startswith(lineage_prefix):
            continue
        for vol_dir in sorted(path for path in lineage_dir.iterdir() if path.is_dir()):
            if not vol_dir.name.startswith("vol_"):
                continue
            try:
                volume = int(vol_dir.name.removeprefix("vol_"))
            except ValueError:
                continue
            if (vol_dir / "pages").exists():
                pairs.append((lineage_dir.name, volume))
    return pairs


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=sorted(ENGINE_MODULES))
    parser.add_argument("--all-engines", action="store_true")
    parser.add_argument(
        "--all-lineages",
        action="store_true",
        help="Reindex every existing ia-abbyy-* lineage/volume directory under reports/s1-sidecars.",
    )
    parser.add_argument(
        "--lineage",
        help=(
            "Reindex an existing source_lineage_id from sidecars on disk, "
            "for imported lineages such as ia-abbyy-v1."
        ),
    )
    parser.add_argument("--volume", type=int, action="append")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    modes = sum(1 for value in (args.engine, args.all_engines, args.lineage, args.all_lineages) if value)
    if modes != 1:
        parser.error("choose exactly one of --engine, --all-engines, --lineage, or --all-lineages")
    if not args.all_lineages and not args.volume:
        parser.error("--volume is required unless --all-lineages is used")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.all_lineages:
        runner = importlib.import_module(GENERIC_REINDEX_MODULE)
        for lineage, volume in _existing_lineage_volumes(runner.DEFAULT_OUTPUT_ROOT):
            _reindex_lineage(lineage, volume, dry_run=args.dry_run)
        return 0
    if args.lineage:
        for volume in args.volume:
            _reindex_lineage(args.lineage, volume, dry_run=args.dry_run)
        return 0
    engines = sorted(ENGINE_MODULES) if args.all_engines else [args.engine]
    for engine in engines:
        runner = _load_runner(engine)
        for volume in args.volume:
            _, _, pages_dir = runner._normal_manifest_paths(
                runner.DEFAULT_OUTPUT_ROOT,
                runner.SOURCE_LINEAGE_ID,
                volume,
            )
            if args.all_engines and not pages_dir.exists():
                print(f"{engine} vol_{volume:02d}: skip: no sidecars")
                continue
            _reindex_volume(engine, volume, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
