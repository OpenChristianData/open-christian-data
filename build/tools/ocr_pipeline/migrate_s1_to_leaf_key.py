"""Dry-run and apply tool for migrating primary S1 sidecars to leaf keys.

Transaction design for --apply:

Per engine/volume cell, the tool preflights free disk space, writes an
append-only journal in the cell run directory, and stages newly written sidecar
JSON in pages/.migrate-staging before replacing final paths. Raw artifacts are
renamed in-place on the same volume, their embedded image path is rewritten,
and their sha256 is recomputed before runner.rekey_sidecar is called. Original
sidecars and content-gone orphans are moved to a quarantine directory, never
deleted. The journal records enough source/destination paths for a later
manual recovery pass. Quarantine retention and purge are intentionally left to
a post-apply verification session.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[3]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib.nsh_leaf_model import (  # noqa: E402
    body_leaf_sha_duplicates,
    expected_image_name,
    gap_by_sha,
    leaf_by_sha,
    resolve_leaf,
    set_leaf_or_exempt,
)
from build.lib.ocr_store_paths import S1_SIDECARS_ROOT  # noqa: E402
from build.lib.page_order import volume_image_paths  # noqa: E402
from build.lib.paths import REPO_ROOT  # noqa: E402
from build.parsers import (  # noqa: E402
    s1_kraken_greek_runner,
    s1_kraken_runner,
    s1_surya_runner,
    s1_tesseract_runner,
)

ENGINE_REGISTRY = {
    "tesseract": {"runner": s1_tesseract_runner, "suffix": ".tesseract.hocr"},
    "kraken": {"runner": s1_kraken_runner, "suffix": ".kraken.raw.json"},
    "surya": {"runner": s1_surya_runner, "suffix": ".surya.raw.json"},
    "kraken-greek": {"runner": s1_kraken_greek_runner, "suffix": ".kraken-greek.raw.json"},
}

COUNT_KEYS = (
    "recovered",
    "relocated",
    "recovered-gap",
    "needs-alternate",
    "preserved-non-body",
    "orphan",
    "need-first-OCR",
    "dup-sha-fanout",
    "anomaly",
)


@dataclass(frozen=True)
class SidecarRef:
    stem: str
    path: Path
    record: dict[str, Any]


@dataclass(frozen=True)
class RekeyPlan:
    old_stem: str
    new_stem: str
    sha256: str
    leaf_num: int | None
    page_num: int | None
    image_path: Path
    sidecar_path: Path
    duplicate_sha: bool = False


@dataclass(frozen=True)
class OrphanPlan:
    stem: str
    path: Path
    sha256: str


@dataclass
class CellResult:
    engine: str
    source_lineage_id: str
    volume: int
    manifest_id: str | None = None
    counts: dict[str, int] = field(default_factory=lambda: {key: 0 for key in COUNT_KEYS})
    rekeys: list[RekeyPlan] = field(default_factory=list)
    preserved_non_body: list[SidecarRef] = field(default_factory=list)
    orphans: list[OrphanPlan] = field(default_factory=list)
    anomalies: list[str] = field(default_factory=list)
    needs_alternate: list[str] = field(default_factory=list)
    skipped: bool = False


def _volume_label(volume: int) -> str:
    return f"vol_{volume:02d}"


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def _successful_sidecar(record: dict[str, Any]) -> bool:
    return (
        record.get("schema_version") == "sidecar-page-v1"
        and record.get("page_extras_carried", {}).get("failure_class") is None
    )


def _load_successful_sidecars(pages_dir: Path) -> list[SidecarRef]:
    result: list[SidecarRef] = []
    if not pages_dir.exists():
        return result
    for path in sorted(pages_dir.glob("*.json")):
        record = _read_json(path)
        if isinstance(record, dict) and _successful_sidecar(record):
            result.append(SidecarRef(stem=path.stem, path=path, record=record))
    return result


def _load_source_manifest(input_root: Path, volume: int) -> tuple[Path, dict[str, Any]] | None:
    path = Path(input_root) / f"{_volume_label(volume)}.manifest.json"
    if not path.exists():
        return None
    data = _read_json(path)
    if not isinstance(data, dict):
        raise ValueError(f"Invalid source manifest JSON object: {path}")
    return path, data


def _manifest_id_for(runner: Any, *, volume: int, images: list[Path], repo_root: Path) -> tuple[str, list[dict[str, str]]]:
    source_files, source_file_sha256 = runner._source_files(images, repo_root)
    return runner._build_manifest_id(volume, source_file_sha256), source_files


def _body_image_paths(input_root: Path, volume: int) -> list[Path]:
    """Body-only image set for historical S1 sidecar migration."""
    return volume_image_paths(input_root / _volume_label(volume))


def _leaf_stem(leaf: dict[str, Any]) -> str:
    image_name = expected_image_name(leaf)
    if image_name is None:
        raise ValueError(f"leaf {leaf.get('leaf_num')} has no expected image name")
    return Path(image_name).stem


def _index_first_by_sha(sidecars: list[SidecarRef]) -> dict[str, SidecarRef]:
    by_sha: dict[str, SidecarRef] = {}
    for sidecar in sidecars:
        sha = sidecar.record.get("source_payload_sha256")
        if isinstance(sha, str) and sha not in by_sha:
            by_sha[sha] = sidecar
    return by_sha


def classify_cell(
    runner: Any,
    *,
    volume: int,
    input_root: Path | None = None,
    output_root: Path | None = None,
    repo_root: Path | None = None,
) -> CellResult:
    input_root = Path(input_root or runner.DEFAULT_INPUT_ROOT)
    output_root = Path(output_root or runner.DEFAULT_OUTPUT_ROOT)
    repo_root = Path(repo_root or REPO_ROOT)
    engine = _engine_name_for_runner(runner)
    result = CellResult(engine=engine, source_lineage_id=runner.SOURCE_LINEAGE_ID, volume=volume)
    loaded = _load_source_manifest(input_root, volume)
    if loaded is None:
        result.skipped = True
        return result
    _manifest_path, source_manifest = loaded
    leaves_by_sha = leaf_by_sha(source_manifest)
    dup_body = body_leaf_sha_duplicates(source_manifest)
    gaps_by_sha = gap_by_sha(source_manifest)
    images = _body_image_paths(input_root, volume)
    _manifest_path_out, _state_path, pages_dir = runner._normal_manifest_paths(output_root, runner.SOURCE_LINEAGE_ID, volume)
    sidecars = _load_successful_sidecars(pages_dir)
    sidecar_by_sha = _index_first_by_sha(sidecars)

    current_shas: set[str] = set()
    planned_dup_shas: set[str] = set()
    for index, image_path in enumerate(images, start=1):
        sha = runner._prefixed_sha256_bytes(image_path.read_bytes())
        current_shas.add(sha)
        sidecar = sidecar_by_sha.get(sha)
        if sidecar is None:
            result.counts["need-first-OCR"] += 1
            continue
        if sha in dup_body:
            if sha in planned_dup_shas:
                continue
            planned_dup_shas.add(sha)
            for leaf in dup_body[sha]:
                new_stem = _leaf_stem(leaf)
                result.rekeys.append(
                    RekeyPlan(
                        old_stem=sidecar.stem,
                        new_stem=new_stem,
                        sha256=sha,
                        leaf_num=leaf["leaf_num"],
                        page_num=leaf.get("page_num"),
                        image_path=input_root / _volume_label(volume) / f"{new_stem}.jpg",
                        sidecar_path=sidecar.path,
                        duplicate_sha=True,
                    )
                )
                result.counts["dup-sha-fanout"] += 1
            continue
        try:
            leaf_num, page_num, expected_stem = resolve_leaf(source_manifest, sha)
        except ValueError as exc:
            gap = gaps_by_sha.get(sha)
            if gap is not None:
                # Recovered-gap page (P2 recovered-gap model): a real body page the
                # primary scan skipped, recovered into gaps[] with no spine leaf.
                # The S1 emit already handles this (runner._leaf_id_for returns None
                # on resolve_leaf failure and emits without canonical_leaf_id), so we
                # migrate it the same way -- keyed on its current stem, leaf_num None
                # -- which keeps the migrated sidecar byte-identical to a fresh emit.
                result.counts["recovered-gap"] += 1
                result.rekeys.append(
                    RekeyPlan(
                        old_stem=sidecar.stem,
                        new_stem=sidecar.stem,
                        sha256=sha,
                        leaf_num=None,
                        page_num=gap.get("page_num"),
                        image_path=image_path,
                        sidecar_path=sidecar.path,
                    )
                )
                continue
            matches = leaves_by_sha.get(sha, [])
            if len(matches) > 1 and any(leaf.get("kind") == "body" for leaf in matches):
                # The image's content sha is shared across several leaves where one
                # is body and the rest are non-body -- the signature of an all-black
                # or blank body scan colliding with blank front/back matter. The body
                # page needs an alternate-source image (it cannot be a real distinct
                # body page if its bytes equal a blank leaf). Hold it -- no rekey plan,
                # not quarantined -- and surface it for alternate-source recovery
                # rather than guessing a leaf or calling it a tool anomaly.
                body_n = sum(1 for leaf in matches if leaf.get("kind") == "body")
                result.counts["needs-alternate"] += 1
                result.needs_alternate.append(
                    f"{sha}: shared across {len(matches)} leaves ({body_n} body) -- needs alternate-source page"
                )
                continue
            result.anomalies.append(f"{sha}: {exc}")
            result.counts["anomaly"] += 1
            continue
        if sidecar.stem == expected_stem:
            result.counts["recovered"] += 1
        else:
            result.counts["relocated"] += 1
        result.rekeys.append(
            RekeyPlan(
                old_stem=sidecar.stem,
                new_stem=expected_stem,
                sha256=sha,
                leaf_num=leaf_num,
                page_num=page_num,
                image_path=image_path,
                sidecar_path=sidecar.path,
            )
        )

    for sidecar in sidecars:
        sha = sidecar.record.get("source_payload_sha256")
        if not isinstance(sha, str) or sha in current_shas:
            continue
        matches = leaves_by_sha.get(sha, [])
        if any(leaf.get("kind") != "body" for leaf in matches):
            result.preserved_non_body.append(sidecar)
            result.counts["preserved-non-body"] += 1
        else:
            result.orphans.append(OrphanPlan(stem=sidecar.stem, path=sidecar.path, sha256=sha))
            result.counts["orphan"] += 1
    return result


def _engine_name_for_runner(runner: Any) -> str:
    for name, entry in ENGINE_REGISTRY.items():
        if entry["runner"] is runner:
            return name
    raise ValueError(f"Runner is not a primary S1 engine: {runner!r}")


def _runner_suffix(runner: Any) -> str:
    return str(ENGINE_REGISTRY[_engine_name_for_runner(runner)]["suffix"])


def _append_journal(journal: Path, **entry: Any) -> None:
    entry["at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    journal.parent.mkdir(parents=True, exist_ok=True)
    with journal.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(entry, ensure_ascii=True, sort_keys=True) + "\n")


def _move_with_retry(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    last_exc: OSError | None = None
    for attempt in range(5):
        try:
            src.replace(dst)
            return
        except OSError as exc:
            last_exc = exc
            time.sleep(0.05 * (attempt + 1))
    if last_exc is not None:
        raise last_exc


def _rewrite_raw_artifact(path: Path, *, old_image_path: Path, new_image_path: Path, suffix: str) -> None:
    if suffix == ".tesseract.hocr":
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace(str(old_image_path), str(new_image_path)), encoding="utf-8", newline="\n")
        return
    payload = _read_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"Raw JSON artifact is not an object: {path}")
    payload["image_path"] = str(new_image_path)
    _write_json(path, payload)


def _snapshot_rekey_sources(
    runner: Any,
    plans: list[RekeyPlan],
    *,
    suffix: str,
    pages_dir: Path,
    snapshot_dir: Path,
    journal: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, Path], dict[str, Path]]:
    record_snapshots: dict[str, dict[str, Any]] = {}
    raw_snapshots: dict[str, Path] = {}
    sidecar_snapshots: dict[str, Path] = {}
    if not plans:
        return record_snapshots, raw_snapshots, sidecar_snapshots
    # A leftover snapshot dir means a prior apply crashed mid-run: it holds the only
    # copy of un-recovered source sidecars/raws (irreplaceable OCR -- re-OCR is never
    # run). Fail fast (REL-02) instead of deleting it, so the staged sources can be
    # recovered by hand before re-running.
    if snapshot_dir.exists():
        raise RuntimeError(
            f"Leftover migration snapshot at {snapshot_dir} -- a prior apply was "
            f"interrupted. Recover the staged sources under it, then remove the dir "
            f"before re-running."
        )
    raw_snapshot_dir = snapshot_dir / "raw"
    sidecar_snapshot_dir = snapshot_dir / "pages"
    raw_snapshot_dir.mkdir(parents=True, exist_ok=True)
    sidecar_snapshot_dir.mkdir(parents=True, exist_ok=True)
    for old_stem in sorted({plan.old_stem for plan in plans}):
        old_sidecar = pages_dir / f"{old_stem}.json"
        record = _read_json(old_sidecar)
        if not isinstance(record, dict):
            raise ValueError(f"Sidecar JSON is not an object: {old_sidecar}")
        record_snapshots[old_stem] = record
        old_raw = runner._raw_artifact_path(pages_dir, old_stem, suffix)
        if old_raw.exists():
            staged_raw = raw_snapshot_dir / old_raw.name
            _move_with_retry(old_raw, staged_raw)
            raw_snapshots[old_stem] = staged_raw
        staged_sidecar = sidecar_snapshot_dir / old_sidecar.name
        _move_with_retry(old_sidecar, staged_sidecar)
        sidecar_snapshots[old_stem] = staged_sidecar
        # Record where each source was staged so a crash mid-write-loop is
        # recoverable by journal replay (not only by knowing the dir convention).
        _append_journal(
            journal,
            op="snapshot_source",
            stem=old_stem,
            staged_sidecar=str(staged_sidecar),
            staged_raw=str(raw_snapshots[old_stem]) if old_stem in raw_snapshots else None,
        )
    return record_snapshots, raw_snapshots, sidecar_snapshots


def _preflight_free_space(run_dir: Path, planned_bytes: int) -> None:
    usage = shutil.disk_usage(run_dir if run_dir.exists() else run_dir.parent)
    required = max(planned_bytes * 2, 1024 * 1024)
    if usage.free < required:
        raise RuntimeError(f"Insufficient free space for cell preflight: free={usage.free} required={required}")


def _relative_or_abs(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _apply_rekey_plan(
    runner: Any,
    plan: RekeyPlan,
    *,
    suffix: str,
    pages_dir: Path,
    staging_dir: Path,
    quarantine_dir: Path,
    journal: Path,
    repo_root: Path,
    manifest_id: str,
    record_snapshots: dict[str, dict[str, Any]],
    raw_snapshots: dict[str, Path],
    sidecar_snapshots: dict[str, Path],
    quarantined_source_stems: set[str],
) -> None:
    old_sidecar = pages_dir / f"{plan.old_stem}.json"
    new_sidecar = pages_dir / f"{plan.new_stem}.json"
    old_raw = runner._raw_artifact_path(pages_dir, plan.old_stem, suffix)
    new_raw = runner._raw_artifact_path(pages_dir, plan.new_stem, suffix)
    old_image_path = plan.image_path.parent / f"{plan.old_stem}.jpg"
    new_image_path = plan.image_path

    if old_raw != new_raw:
        staged_raw = raw_snapshots.get(plan.old_stem)
        if staged_raw is None:
            raise FileNotFoundError(f"Missing raw artifact for {plan.old_stem}: {old_raw}")
        _append_journal(journal, op="move_raw", src=str(old_raw), dst=str(new_raw))
        new_raw.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(staged_raw, new_raw)
    elif plan.old_stem in raw_snapshots:
        new_raw.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(raw_snapshots[plan.old_stem], new_raw)
    if new_raw.exists():
        _rewrite_raw_artifact(new_raw, old_image_path=old_image_path, new_image_path=new_image_path, suffix=suffix)

    record = copy.deepcopy(record_snapshots[plan.old_stem])
    extras = record.setdefault("page_extras_carried", {})
    raw_artifact = extras.get("raw_artifact")
    raw_rel_path: str | None = None
    if isinstance(raw_artifact, dict) and new_raw.exists():
        raw_rel_path = runner._relative_path(new_raw, repo_root)
        raw_artifact["sha256"] = runner._prefixed_sha256_bytes(new_raw.read_bytes())
    page_sequence = runner._page_sequence(plan.page_num or 1, new_image_path)
    rekeyed = runner.rekey_sidecar(
        record,
        canonical_leaf_id=plan.leaf_num,
        page_native_id=plan.new_stem,
        page_sequence=page_sequence,
        manifest_id=manifest_id,
        raw_artifact_new_path=raw_rel_path,
    )
    staged = staging_dir / f"{plan.new_stem}.json"
    _write_json(staged, rekeyed)
    _append_journal(journal, op="write_sidecar", src=str(staged), dst=str(new_sidecar))
    _move_with_retry(staged, new_sidecar)
    staged_source_sidecar = sidecar_snapshots[plan.old_stem]
    if plan.old_stem != plan.new_stem and plan.old_stem not in quarantined_source_stems:
        quarantined = quarantine_dir / "pages" / staged_source_sidecar.name
        _append_journal(journal, op="quarantine_sidecar", src=str(staged_source_sidecar), dst=str(quarantined))
        _move_with_retry(staged_source_sidecar, quarantined)
        quarantined_source_stems.add(plan.old_stem)


def _build_sidecar_manifest(
    runner: Any,
    *,
    volume: int,
    images: list[Path],
    pages_dir: Path,
    repo_root: Path,
    manifest_id: str,
    source_files: list[dict[str, str]],
) -> dict[str, Any]:
    page_refs = []
    for index, image_path in enumerate(images, start=1):
        page_path = pages_dir / f"{image_path.stem}.json"
        if not page_path.exists():
            continue
        record = _read_json(page_path)
        page_ref: dict[str, Any] = {
            "page_native_id": image_path.stem,
            "page_sequence": runner._page_sequence(index, image_path),
            "status": "eligible",
            "sidecar_page_path": runner._relative_path(page_path, repo_root),
            "source_payload_sha256": record["source_payload_sha256"],
        }
        set_leaf_or_exempt(page_ref, record.get("canonical_leaf_id"))
        page_refs.append(page_ref)
    return {
        "schema_version": "sidecar-manifest-v1",
        "manifest_id": manifest_id,
        "work_id": runner.WORK_ID,
        "edition_id": runner.EDITION_ID,
        "volume": volume,
        "rendering_id": runner.RENDERING_ID,
        "engine_family": runner.ENGINE_FAMILY,
        "engine_version": "",
        "source_lineage_id": runner.SOURCE_LINEAGE_ID,
        "source_files": source_files,
        "pages": page_refs,
        "manifest_cross_check": {
            "samples_checked": 1 if page_refs else 0,
            "samples_matched": 1 if page_refs else 0,
            "samples_inconclusive": 0,
            "failed_samples": [],
        },
        "bundle_extras_carried": {},
        "bundle_extras_carried_keys": [],
        "bundle_extras_jcs_sha256": runner.EMPTY_EXTRAS_SHA256,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def apply_cell(
    runner: Any,
    *,
    volume: int,
    input_root: Path | None = None,
    output_root: Path | None = None,
    repo_root: Path | None = None,
) -> CellResult:
    input_root = Path(input_root or runner.DEFAULT_INPUT_ROOT)
    output_root = Path(output_root or runner.DEFAULT_OUTPUT_ROOT)
    repo_root = Path(repo_root or REPO_ROOT)
    result = classify_cell(runner, volume=volume, input_root=input_root, output_root=output_root, repo_root=repo_root)
    if result.skipped:
        return result
    suffix = _runner_suffix(runner)
    manifest_path, state_path, pages_dir = runner._normal_manifest_paths(output_root, runner.SOURCE_LINEAGE_ID, volume)
    run_dir = pages_dir.parent
    staging_dir = pages_dir / ".migrate-staging"
    snapshot_dir = pages_dir / ".migrate-snapshot"
    quarantine_dir = run_dir / "quarantine" / "migrate_s1_to_leaf_key"
    journal = run_dir / "migrate_s1_to_leaf_key.journal.jsonl"
    planned_bytes = sum(plan.sidecar_path.stat().st_size for plan in result.rekeys if plan.sidecar_path.exists())
    _preflight_free_space(run_dir, planned_bytes)
    staging_dir.mkdir(parents=True, exist_ok=True)
    images = _body_image_paths(input_root, volume)
    manifest_id, source_files = _manifest_id_for(runner, volume=volume, images=images, repo_root=repo_root)
    result.manifest_id = manifest_id
    _append_journal(
        journal,
        op="begin_cell",
        engine=result.engine,
        source_lineage_id=runner.SOURCE_LINEAGE_ID,
        volume=volume,
    )
    record_snapshots, raw_snapshots, sidecar_snapshots = _snapshot_rekey_sources(
        runner,
        result.rekeys,
        suffix=suffix,
        pages_dir=pages_dir,
        snapshot_dir=snapshot_dir,
        journal=journal,
    )
    # Quarantine orphans BEFORE the rekey writes. An orphan's stem can equal a
    # relocation's new_stem (systematic at an up-shift volume's top boundary: the
    # vacated stem holds stale content AND receives relocated content). Run after
    # the rekey loop and the orphan move would clobber the freshly-written migrated
    # sidecar at that stem; run first and it preserves the original orphan content
    # and clears the stem for the relocation write.
    for orphan in result.orphans:
        if orphan.path.exists():
            quarantined = quarantine_dir / "orphans" / orphan.path.name
            _append_journal(journal, op="quarantine_orphan", src=str(orphan.path), dst=str(quarantined))
            _move_with_retry(orphan.path, quarantined)
    quarantined_source_stems: set[str] = set()
    for plan in result.rekeys:
        _apply_rekey_plan(
            runner,
            plan,
            suffix=suffix,
            pages_dir=pages_dir,
            staging_dir=staging_dir,
            quarantine_dir=quarantine_dir,
            journal=journal,
            repo_root=repo_root,
            manifest_id=manifest_id,
            record_snapshots=record_snapshots,
            raw_snapshots=raw_snapshots,
            sidecar_snapshots=sidecar_snapshots,
            quarantined_source_stems=quarantined_source_stems,
        )
    if snapshot_dir.exists():
        shutil.rmtree(snapshot_dir)  # standards: log/temp rotation
    # Only (re)write the manifest when this cell actually changed. A cell with no
    # rekeys and no orphans (e.g. every page is need-first-OCR -- nothing on disk
    # yet) must NOT have its manifest rebuilt to an empty pages[]: that would
    # clobber any pre-existing index. Pure re-indexing is reindex_manifest's job,
    # not migrate's.
    if not result.rekeys and not result.orphans:
        _append_journal(journal, op="end_cell", manifest_id=manifest_id, no_changes=True)
        return result
    sidecar_manifest = _build_sidecar_manifest(
        runner,
        volume=volume,
        images=images,
        pages_dir=pages_dir,
        repo_root=repo_root,
        manifest_id=manifest_id,
        source_files=source_files,
    )
    _write_json(manifest_path, sidecar_manifest)
    _write_json(
        state_path,
        {
            "manifest_id": manifest_id,
            "emitted_pages": sorted(page["page_native_id"] for page in sidecar_manifest["pages"]),
            "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        },
    )
    _append_journal(journal, op="end_cell", manifest_id=manifest_id)
    return result


# Only the canonical per-volume manifest -- NOT stale/backup variants like
# vol_11_rebuild.stale_scandata.manifest.json, which would otherwise parse to the
# same volume number and produce a duplicate (and stale) cell.
_VOL_MANIFEST_RE = re.compile(r"^vol_(\d+)\.manifest\.json$")


def _volumes_found(input_root: Path) -> list[int]:
    volumes: set[int] = set()
    for path in sorted(input_root.glob("vol_*.manifest.json")):
        match = _VOL_MANIFEST_RE.match(path.name)
        if match:
            volumes.add(int(match.group(1)))
    return sorted(volumes)


def _selected_engines(engine: str | None) -> list[str]:
    if engine is not None:
        if engine not in ENGINE_REGISTRY:
            raise ValueError(f"Unknown primary engine: {engine}")
        return [engine]
    return list(ENGINE_REGISTRY)


def dry_run(
    *,
    engine: str | None = None,
    volume: int | None = None,
    input_root: Path | None = None,
    output_root: Path | None = None,
    repo_root: Path | None = None,
) -> list[CellResult]:
    results = []
    for engine_name in _selected_engines(engine):
        runner = ENGINE_REGISTRY[engine_name]["runner"]
        root = Path(input_root or runner.DEFAULT_INPUT_ROOT)
        volumes = [volume] if volume is not None else _volumes_found(root)
        for vol in volumes:
            results.append(
                classify_cell(
                    runner,
                    volume=vol,
                    input_root=root,
                    output_root=Path(output_root or runner.DEFAULT_OUTPUT_ROOT),
                    repo_root=Path(repo_root or REPO_ROOT),
                )
            )
    return results


def _print_table(results: list[CellResult]) -> None:
    header = "engine volume " + " ".join(COUNT_KEYS)
    print(header)
    totals = {key: 0 for key in COUNT_KEYS}
    by_engine: dict[str, dict[str, int]] = {}
    for result in results:
        row = [
            result.engine,
            _volume_label(result.volume),
            *(str(result.counts[key]) for key in COUNT_KEYS),
        ]
        print(" ".join(row))
        engine_totals = by_engine.setdefault(result.engine, {key: 0 for key in COUNT_KEYS})
        for key in COUNT_KEYS:
            totals[key] += result.counts[key]
            engine_totals[key] += result.counts[key]
    for engine, counts in by_engine.items():
        print("TOTAL", engine, *(str(counts[key]) for key in COUNT_KEYS))
    print("TOTAL grand", *(str(totals[key]) for key in COUNT_KEYS))
    # Surface every anomaly (a successful sidecar whose content sha the CURRENT
    # source manifest cannot resolve to exactly one leaf -- manifest/disk drift,
    # PIPE-29). These pages are NOT re-OCR candidates (the OCR exists); they need
    # manifest reconciliation before rekey. Visible detail, not just a count.
    for result in results:
        for anomaly in result.anomalies:
            print(f"ANOMALY {result.engine} {_volume_label(result.volume)} {anomaly}")
    # Recovered-gap pages are migrated (benign); needs-alternate pages are HELD for
    # alternate-source recovery -- surface them so they are not silently deferred.
    for result in results:
        for note in result.needs_alternate:
            print(f"NEEDS-ALTERNATE {result.engine} {_volume_label(result.volume)} {note}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=sorted(ENGINE_REGISTRY), default=None)
    parser.add_argument("--volume", type=int, default=None)
    parser.add_argument("--apply", action="store_true", default=False)
    parser.add_argument("--input-root", type=Path, default=None)
    parser.add_argument("--output-root", type=Path, default=S1_SIDECARS_ROOT)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    results: list[CellResult] = []
    for engine_name in _selected_engines(args.engine):
        runner = ENGINE_REGISTRY[engine_name]["runner"]
        input_root = args.input_root or runner.DEFAULT_INPUT_ROOT
        volumes = [args.volume] if args.volume is not None else _volumes_found(input_root)
        for volume in volumes:
            try:
                if args.apply:
                    results.append(
                        apply_cell(
                            runner,
                            volume=volume,
                            input_root=input_root,
                            output_root=args.output_root,
                            repo_root=args.repo_root,
                        )
                    )
                else:
                    results.append(
                        classify_cell(
                            runner,
                            volume=volume,
                            input_root=input_root,
                            output_root=args.output_root,
                            repo_root=args.repo_root,
                        )
                    )
            except Exception as exc:  # noqa: BLE001
                result = CellResult(engine=engine_name, source_lineage_id=runner.SOURCE_LINEAGE_ID, volume=volume)
                result.counts["anomaly"] = 1
                result.anomalies.append(f"{type(exc).__name__}: {exc}")
                results.append(result)
                print(f"ERROR {engine_name} {_volume_label(volume)}: {type(exc).__name__}: {exc}", file=sys.stderr)
    _print_table(results)
    return 1 if any(result.anomalies for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
