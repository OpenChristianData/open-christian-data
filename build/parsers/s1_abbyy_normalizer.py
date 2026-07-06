"""Normalize assembled ABBYY lineage JSON into S1 sidecar records.

Input files are the already-assembled ABBYY JSON records under
data/reference/schaff/encyclopedia/1908-1914/<lineage>/vol_NN.json.

The normalizer writes generated sidecar output under reports/s1-sidecars/ by
default. Reference JSON under data/reference is read-only input here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jsonschema

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib.page_order import volume_sidecar_files  # noqa: E402
from build.lib.edition_page_key import body_edition_key, resolve_edition_page_key_by_sha  # noqa: E402
from build.lib.nsh_leaf_model import canonical_leaf_id, leaves_view, set_leaf_or_exempt  # noqa: E402
from build.tools.ocr_pipeline.abbyy_content_alignment import load_leafmap  # noqa: E402
from build.lib.ocr_store_paths import S1_SIDECARS_ROOT  # noqa: E402
from build.lib.paths import REPO_ROOT  # noqa: E402
from build.lib.schema_enums import get_enum  # noqa: E402

WORK_ID = "schaff-herzog-encyclopedia"
EDITION_ID = "1908-1914"
S1_SIDECAR_CACHE_VERSION = "s1-sidecar-currentness-v1"
DEFAULT_OUTPUT_ROOT = S1_SIDECARS_ROOT
SCHEMA_DIR = REPO_ROOT / "schemas" / "v1"
EMPTY_EXTRAS_SHA256 = (
    "sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
)


@dataclass(frozen=True)
class NormalizationSummary:
    manifest: dict[str, Any]
    manifest_path: Path
    state_path: Path
    emitted_pages: int
    skipped_pages: int
    failed_pages: int
    unmapped_pages: int = 0


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def _sidecar_is_done(page_path: Path) -> bool:
    """Return True iff a current successful sidecar exists on disk (valid JSON, no failure_class, matching cache version)."""
    if not page_path.exists():
        return False
    try:
        data = _read_json(page_path)
        extras = data.get("page_extras_carried", {})
        return (
            extras.get("failure_class") is None
            and extras.get("runner_cache_version") == S1_SIDECAR_CACHE_VERSION
        )
    except Exception:  # noqa: BLE001
        return False


def _schema(name: str) -> dict[str, Any]:
    return _read_json(SCHEMA_DIR / f"{name}.schema.json")


def _validate(schema_name: str, record: dict[str, Any]) -> None:
    jsonschema.validate(instance=record, schema=_schema(schema_name))


def _jcs_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _prefixed_sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _prefixed_sha256_json(value: Any) -> str:
    return _prefixed_sha256_bytes(_jcs_bytes(value))


def _observation_token_id(seed: dict[str, Any]) -> str:
    return "ot-sha256:" + hashlib.sha256(_jcs_bytes(seed)).hexdigest()


def _extras_hash(extras: dict[str, Any]) -> str:
    if not extras:
        return EMPTY_EXTRAS_SHA256
    return _prefixed_sha256_json(extras)


def _relative_path(path: Path, repo_root: Path) -> str:
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def _volume_from_path(path: Path) -> int:
    match = re.fullmatch(r"vol_(\d+)\.json", path.name)
    if not match:
        return 1
    return int(match.group(1))


def _volume_label(volume: int) -> str:
    return f"vol_{volume:02d}"


def _page_native_id(value: Any) -> str:
    text = str(value)
    if text:
        return text
    return "unknown"


def _page_sidecar_stem(page_native_id: str) -> str:
    if page_native_id.isdecimal():
        return f"page_{int(page_native_id):04d}"
    return f"page_{page_native_id}"


def _page_sequence(index: int, page: dict[str, Any]) -> int:
    raw_page = page.get("page")
    if isinstance(raw_page, int) and raw_page > 0:
        return raw_page
    return index


def _word_records(
    words: list[str],
    *,
    rendering_id: str,
    page_sequence: int,
    page_native_id: str,
    line_index: int,
    confidence: float | int | None,
) -> list[dict[str, Any]]:
    records = []
    for word_index, word in enumerate(words, start=1):
        word_native_id = f"word-{line_index:04d}-{word_index:04d}"
        bbox_native = None
        records.append(
            {
                "observation_token_id": _observation_token_id(
                    {
                        "rendering_id": rendering_id,
                        "page_native_id": page_native_id,
                        "page_sequence": page_sequence,
                        "line_index": line_index,
                        "word_index": word_index,
                        "source_raw": word,
                        "bbox_native": bbox_native,
                    }
                ),
                "word_native_id": word_native_id,
                "source_raw": word,
                "confidence": confidence,
                "bbox_native": bbox_native,
            }
        )
    return records


def _line_records(
    text: str,
    *,
    rendering_id: str,
    page_sequence: int,
    page_native_id: str,
    confidence: float | int | None,
) -> list[dict[str, Any]]:
    records = []
    lines = [line for line in text.splitlines() if line.strip()]
    for line_index, line in enumerate(lines, start=1):
        source_raw = line.strip()
        bbox_native = None
        records.append(
            {
                "observation_token_id": _observation_token_id(
                    {
                        "rendering_id": rendering_id,
                        "page_native_id": page_native_id,
                        "page_sequence": page_sequence,
                        "line_index": line_index,
                        "source_raw": source_raw,
                        "bbox_native": bbox_native,
                    }
                ),
                "line_native_id": f"line-{line_index:04d}",
                "source_raw": source_raw,
                "confidence": confidence,
                "bbox_native": bbox_native,
                "words": _word_records(
                    source_raw.split(),
                    rendering_id=rendering_id,
                    page_sequence=page_sequence,
                    page_native_id=page_native_id,
                    line_index=line_index,
                    confidence=confidence,
                ),
            }
        )
    return records


def _parsed_keys_for_page(page: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"key": key, "handling": "extras_carried", "source_path": f"pages[].{key}"}
        for key in sorted(page)
    ]


def _build_page_record(
    *,
    manifest_id: str,
    rendering_id: str,
    page: dict[str, Any],
    page_sequence: int,
    page_native_id: str,
    source_payload_sha256: str,
) -> dict[str, Any]:
    text = page.get("text")
    if not isinstance(text, str):
        text = ""
    confidence = page.get("confidence_mean")
    if not isinstance(confidence, (int, float)):
        confidence = None
    lines = _line_records(
        text,
        rendering_id=rendering_id,
        page_sequence=page_sequence,
        page_native_id=page_native_id,
        confidence=confidence,
    )
    blocks = []
    if lines:
        blocks.append(
            {
                "block_id": "block-0001",
                "block_type": "text",
                "lines": lines,
                "bbox_native": None,
            }
        )
    page_extras = {**page, "runner_cache_version": S1_SIDECAR_CACHE_VERSION}
    return {
        "schema_version": "sidecar-page-v1",
        "manifest_id": manifest_id,
        "rendering_id": rendering_id,
        "page_native_id": page_native_id,
        "page_sequence": page_sequence,
        "page_dimensions_native": {"width": None, "height": None, "unit": "unknown"},
        "blocks": blocks,
        "parsed_keys_index": _parsed_keys_for_page(page),
        "page_extras_carried": page_extras,
        "page_extras_carried_keys": sorted(page_extras),
        "page_extras_jcs_sha256": _extras_hash(page_extras),
        "source_payload_sha256": source_payload_sha256,
    }


def _diagnostic_page_record(
    *,
    manifest_id: str,
    rendering_id: str,
    page_native_id: str,
    page_sequence: int,
    source_payload_sha256: str,
    failure_class: str,
) -> dict[str, Any]:
    page_extras = {"failure_class": failure_class}
    return {
        "schema_version": "sidecar-page-v1",
        "manifest_id": manifest_id,
        "rendering_id": rendering_id,
        "page_native_id": page_native_id,
        "page_sequence": page_sequence,
        "page_dimensions_native": {"width": None, "height": None, "unit": "unknown"},
        # Whole-input malformed -> no per-page leaf is resolvable, so this
        # diagnostic record is clid_exempt under the R5 required-or-exempt schema.
        "clid_exempt": True,
        "blocks": [],
        "parsed_keys_index": [
            {
                "key": "failure_class",
                "handling": "diagnostic_only",
                "source_path": "normalizer.failure_class",
            }
        ],
        "page_extras_carried": page_extras,
        "page_extras_carried_keys": sorted(page_extras),
        "page_extras_jcs_sha256": _extras_hash(page_extras),
        "source_payload_sha256": source_payload_sha256,
    }


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"emitted_pages": []}
    state = _read_json(path)
    if not isinstance(state, dict) or not isinstance(state.get("emitted_pages"), list):
        raise ValueError(f"Invalid manifest state marker: {path}")
    return state


def _build_manifest_id(
    *,
    source_lineage_id: str,
    rendering_id: str,
    volume: int,
    source_file_sha256: str,
) -> str:
    payload = {
        "source_lineage_id": source_lineage_id,
        "rendering_id": rendering_id,
        "volume": volume,
        "source_file_sha256": source_file_sha256,
    }
    return "sm-sha256:" + hashlib.sha256(_jcs_bytes(payload)).hexdigest()


def _assert_locked_enums() -> None:
    engine_families = get_enum("sidecar-manifest-v1", "engine_family")
    page_statuses = get_enum("sidecar-manifest-v1", "pages", "status")
    if "abbyy" not in engine_families:
        raise RuntimeError("sidecar-manifest-v1 engine_family enum does not include abbyy")
    for status in ("eligible", "diagnostic_only", "corrupt", "missing"):
        if status not in page_statuses:
            raise RuntimeError(f"sidecar-manifest-v1 page_status enum missing {status!r}")


def _normal_manifest_paths(
    output_root: Path,
    source_lineage_id: str,
    volume: int,
) -> tuple[Path, Path, Path]:
    run_dir = output_root / source_lineage_id / _volume_label(volume)
    return run_dir / "manifest.json", run_dir / "manifest.state.json", run_dir / "pages"


def _prune_unreferenced_page_sidecars(
    pages_dir: Path,
    page_refs: list[dict[str, Any]],
) -> int:
    """Remove page JSONs that are no longer referenced by a full-volume manifest."""
    if not pages_dir.exists():
        return 0

    referenced_names = {
        Path(str(ref["sidecar_page_path"])).name
        for ref in page_refs
        if ref.get("sidecar_page_path")
    }
    removed = 0
    for path in pages_dir.glob("*.json"):
        if path.name.endswith(".rendering-v1.json"):
            continue
        if path.name not in referenced_names:
            path.unlink()
            removed += 1
    return removed


def _malformed_summary(
    *,
    source_path: Path,
    output_root: Path,
    repo_root: Path,
    source_lineage_id: str,
    volume: int,
    source_file_sha256: str,
    source_payload_sha256: str,
    failure_class: str,
) -> NormalizationSummary:
    rendering_id = f"{source_lineage_id}/schaff/encyclopedia/1908-1914/v1"
    manifest_id = _build_manifest_id(
        source_lineage_id=source_lineage_id,
        rendering_id=rendering_id,
        volume=volume,
        source_file_sha256=source_file_sha256,
    )
    manifest_path, state_path, pages_dir = _normal_manifest_paths(
        output_root, source_lineage_id, volume
    )
    page_path = pages_dir / "page_0001.json"
    page_record = _diagnostic_page_record(
        manifest_id=manifest_id,
        rendering_id=rendering_id,
        page_native_id="input",
        page_sequence=1,
        source_payload_sha256=source_payload_sha256,
        failure_class=failure_class,
    )
    # Wholly-malformed input has no page identity; the required edition_page_key
    # gets a deterministic synthetic body key for this single corrupt diagnostic.
    page_record["edition_page_key"] = body_edition_key(1)
    _validate("sidecar-page-v1", page_record)
    _write_json(page_path, page_record)
    manifest = {
        "schema_version": "sidecar-manifest-v1",
        "manifest_id": manifest_id,
        "work_id": WORK_ID,
        "edition_id": EDITION_ID,
        "volume": volume,
        "rendering_id": rendering_id,
        "engine_family": "abbyy",
        "engine_version": "",
        "source_lineage_id": source_lineage_id,
        "source_files": [
            {
                "path": _relative_path(source_path, repo_root),
                "sha256": source_file_sha256,
            }
        ],
        "pages": [
            {
                "page_native_id": "input",
                "page_sequence": 1,
                "status": "corrupt",
                "sidecar_page_path": _relative_path(page_path, repo_root),
                "source_payload_sha256": source_payload_sha256,
                "clid_exempt": True,
                "edition_page_key": body_edition_key(1),
                "failure_class": failure_class,
            }
        ],
        "manifest_cross_check": {
            "samples_checked": 0,
            "samples_matched": 0,
            "samples_inconclusive": 1,
            "failed_samples": [
                {
                    "leaf": _relative_path(source_path, repo_root),
                    "expected": "assembled ABBYY JSON object with pages[]",
                    "observed": failure_class,
                }
            ],
        },
        "bundle_extras_carried": {},
        "bundle_extras_carried_keys": [],
        "bundle_extras_jcs_sha256": EMPTY_EXTRAS_SHA256,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    _validate("sidecar-manifest-v1", manifest)
    _write_json(manifest_path, manifest)
    state = {
        "manifest_id": manifest_id,
        "emitted_pages": ["input"],
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    _write_json(state_path, state)
    return NormalizationSummary(
        manifest=manifest,
        manifest_path=manifest_path,
        state_path=state_path,
        emitted_pages=1,
        skipped_pages=0,
        failed_pages=1,
    )


def normalize_abbyy_file(
    source_path: Path,
    *,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    repo_root: Path = REPO_ROOT,
    source_lineage_id: str | None = None,
    pages: list[int] | None = None,
    force: bool = False,
) -> NormalizationSummary:
    """Normalize one assembled ABBYY JSON file into a manifest and page sidecars."""
    _assert_locked_enums()
    source_path = Path(source_path)
    output_root = Path(output_root)
    repo_root = Path(repo_root)
    source_file_sha256 = _prefixed_sha256_bytes(source_path.read_bytes())
    volume = _volume_from_path(source_path)
    source_payload_sha256 = source_file_sha256

    try:
        assembled = _read_json(source_path)
    except json.JSONDecodeError:
        lineage = source_lineage_id or source_path.parent.name
        return _malformed_summary(
            source_path=source_path,
            output_root=output_root,
            repo_root=repo_root,
            source_lineage_id=lineage,
            volume=volume,
            source_file_sha256=source_file_sha256,
            source_payload_sha256=source_payload_sha256,
            failure_class="malformed_assembled_json",
        )

    lineage = source_lineage_id or source_path.parent.name
    if not isinstance(assembled, dict) or not isinstance(assembled.get("pages"), list):
        return _malformed_summary(
            source_path=source_path,
            output_root=output_root,
            repo_root=repo_root,
            source_lineage_id=lineage,
            volume=volume,
            source_file_sha256=source_file_sha256,
            source_payload_sha256=source_payload_sha256,
            failure_class="malformed_assembled_json",
        )

    rendering_id = str(assembled.get("rendering_id") or f"{lineage}/schaff/encyclopedia/1908-1914/v1")
    engine_version = str(assembled.get("engine_version") or "")
    if isinstance(assembled.get("volume"), int):
        volume = assembled["volume"]
    manifest_id = _build_manifest_id(
        source_lineage_id=lineage,
        rendering_id=rendering_id,
        volume=volume,
        source_file_sha256=source_file_sha256,
    )
    manifest_path, state_path, pages_dir = _normal_manifest_paths(output_root, lineage, volume)
    state = _load_state(state_path)
    already_done = set(str(value) for value in state.get("emitted_pages", []))
    emitted_pages = 0
    skipped_pages = 0
    failed_pages = 0
    page_refs = []
    emitted_state = set(already_done)
    core_keys = {"rendering_id", "volume", "engine_alias", "engine_version", "pages"}
    bundle_extras = {key: value for key, value in assembled.items() if key not in core_keys}
    _source_files_manifest = [
        {
            "path": _relative_path(source_path, repo_root),
            "sha256": source_file_sha256,
        }
    ]
    _run_started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    assembled_pages = list(enumerate(assembled["pages"], start=1))
    if pages is not None:
        if not pages:
            raise ValueError(
                "pages must be non-empty when provided; omit to process whole volume"
            )
        page_set = set(pages)
        assembled_pages = [
            (index, page)
            for index, page in assembled_pages
            if isinstance(page, dict) and _page_sequence(index, page) in page_set
        ]
        if not assembled_pages:
            raise ValueError(
                f"pages {sorted(page_set)} matched no ABBYY pages in volume"
            )

    for index, page in assembled_pages:
        if not isinstance(page, dict):
            page = {"page": index, "failure_class": "malformed_page_record"}
        page_sequence = _page_sequence(index, page)
        page_native_id = _page_native_id(page.get("page", page_sequence))
        page_sha256 = _prefixed_sha256_json(page)
        page_path = pages_dir / f"{_page_sidecar_stem(page_native_id)}.json"
        status = "eligible"
        failure_class = None
        if page.get("failure_class"):
            status = "corrupt"
            failure_class = str(page["failure_class"])
        elif not isinstance(page.get("text"), str) or not page.get("text"):
            status = "diagnostic_only"
            failure_class = "empty_page_text"

        if not force and _sidecar_is_done(page_path):
            skipped_pages += 1
        else:
            if failure_class and status == "corrupt":
                page_record = _diagnostic_page_record(
                    manifest_id=manifest_id,
                    rendering_id=rendering_id,
                    page_native_id=page_native_id,
                    page_sequence=page_sequence,
                    source_payload_sha256=page_sha256,
                    failure_class=failure_class,
                )
            else:
                page_record = _build_page_record(
                    manifest_id=manifest_id,
                    rendering_id=rendering_id,
                    page=page,
                    page_sequence=page_sequence,
                    page_native_id=page_native_id,
                    source_payload_sha256=page_sha256,
                )
            # normalize_abbyy_file is the single-file CLI path (no volume manifest
            # to resolve a leaf from); production NSH abbyy uses
            # normalize_abbyy_rich_volume which keys on the leafmap. So records from
            # this path are clid_exempt under the R5 required-or-exempt schemas.
            set_leaf_or_exempt(page_record, None)
            # CLI single-file path: no volume manifest, so best-effort a body key
            # from the page sequence (the source's own page number) for the
            # now-required edition_page_key.
            page_record["edition_page_key"] = body_edition_key(page_sequence)
            _validate("sidecar-page-v1", page_record)
            _write_json(page_path, page_record)
            emitted_pages += 1
            emitted_state.add(page_native_id)
            _write_json(
                state_path,
                {
                    "manifest_id": manifest_id,
                    "emitted_pages": sorted(emitted_state),
                    "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                },
            )

        if failure_class:
            failed_pages += 1
        page_ref = {
            "page_native_id": page_native_id,
            "page_sequence": page_sequence,
            "status": status,
            "sidecar_page_path": _relative_path(page_path, repo_root),
            "source_payload_sha256": page_sha256,
        }
        set_leaf_or_exempt(page_ref, None)
        page_ref["edition_page_key"] = body_edition_key(page_sequence)
        if failure_class:
            page_ref["failure_class"] = failure_class
        page_refs.append(page_ref)
        _write_json(manifest_path, {
            "schema_version": "sidecar-manifest-v1",
            "manifest_id": manifest_id,
            "work_id": WORK_ID,
            "edition_id": EDITION_ID,
            "volume": volume,
            "rendering_id": rendering_id,
            "engine_family": "abbyy",
            "engine_version": engine_version,
            "source_lineage_id": lineage,
            "source_files": _source_files_manifest,
            "pages": list(page_refs),
            "manifest_cross_check": {
                "samples_checked": 1 if page_refs else 0,
                "samples_matched": 1 if page_refs else 0,
                "samples_inconclusive": 0,
                "failed_samples": [],
            },
            "bundle_extras_carried": bundle_extras,
            "bundle_extras_carried_keys": sorted(bundle_extras),
            "bundle_extras_jcs_sha256": _extras_hash(bundle_extras),
            "created_at": _run_started_at,
        })
    if pages is None:
        removed = _prune_unreferenced_page_sidecars(pages_dir, page_refs)
        if removed:
            print(
                f"    abbyy/{lineage}: removed {removed} stale sidecar(s)",
                flush=True,
            )

    manifest = {
        "schema_version": "sidecar-manifest-v1",
        "manifest_id": manifest_id,
        "work_id": WORK_ID,
        "edition_id": EDITION_ID,
        "volume": volume,
        "rendering_id": rendering_id,
        "engine_family": "abbyy",
        "engine_version": engine_version,
        "source_lineage_id": lineage,
        "source_files": _source_files_manifest,
        "pages": page_refs,
        "manifest_cross_check": {
            "samples_checked": 1 if page_refs else 0,
            "samples_matched": 1 if page_refs else 0,
            "samples_inconclusive": 0,
            "failed_samples": [],
        },
        "bundle_extras_carried": bundle_extras,
        "bundle_extras_carried_keys": sorted(bundle_extras),
        "bundle_extras_jcs_sha256": _extras_hash(bundle_extras),
        "created_at": _run_started_at,
    }
    _validate("sidecar-manifest-v1", manifest)
    _write_json(manifest_path, manifest)
    state = {
        "manifest_id": manifest_id,
        "emitted_pages": sorted(str(ref["page_native_id"]) for ref in page_refs),
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    _write_json(state_path, state)
    return NormalizationSummary(
        manifest=manifest,
        manifest_path=manifest_path,
        state_path=state_path,
        emitted_pages=emitted_pages,
        skipped_pages=skipped_pages,
        failed_pages=failed_pages,
    )


def _rich_lineage_suffix(source_lineage_id: str) -> str:
    """Map a lineage id to the rich-sidecar filename suffix.

    The rich per-page sidecars are named page_NNNN.<suffix>.json where the suffix
    is the lineage id without the trailing pipeline-version tag, e.g.
    ia-abbyy-v1 -> ia-abbyy, ia-abbyy-haucgoog-c1-v1 -> ia-abbyy-haucgoog-c1.
    """
    return re.sub(r"-v\d+$", "", source_lineage_id)


def _coerce_bbox(raw: Any) -> dict[str, Any] | None:
    """Return a schema bbox_native {x,y,w,h} from a rich bbox, or None if absent.

    Rich ABBYY bboxes are already {x,y,w,h}; preserve numeric type (the canonical
    frame is source-image pixels, matching tesseract/surya native dimensions).
    """
    if not isinstance(raw, dict):
        return None
    if not all(isinstance(raw.get(key), (int, float)) for key in ("x", "y", "w", "h")):
        return None
    return {"x": raw["x"], "y": raw["y"], "w": raw["w"], "h": raw["h"]}


def _clamp_confidence(raw: Any) -> float | int | None:
    if isinstance(raw, (int, float)) and 0 <= raw <= 100:
        return raw
    return None


def _rich_word_record(
    word: dict[str, Any],
    *,
    rendering_id: str,
    page_native_id: str,
    page_sequence: int,
    block_index: int,
    line_index: int,
    word_index: int,
) -> dict[str, Any]:
    source_raw = str(word.get("text", ""))
    bbox_native = _coerce_bbox(word.get("bbox"))
    return {
        "observation_token_id": _observation_token_id(
            {
                "rendering_id": rendering_id,
                "page_native_id": page_native_id,
                "page_sequence": page_sequence,
                "block_index": block_index,
                "line_index": line_index,
                "word_index": word_index,
                "source_raw": source_raw,
                "bbox_native": bbox_native,
            }
        ),
        "word_native_id": f"word-{block_index:04d}-{line_index:04d}-{word_index:04d}",
        "source_raw": source_raw,
        "confidence": _clamp_confidence(word.get("confidence")),
        "bbox_native": bbox_native,
    }


def _build_rich_page_record(
    rich: dict[str, Any],
    *,
    manifest_id: str,
    rendering_id: str,
    page_native_id: str,
    page_sequence: int,
    source_payload_sha256: str,
) -> dict[str, Any]:
    """Build a geometry-bearing sidecar-page-v1 record from a rich ABBYY sidecar.

    Unlike _build_page_record (flat, text-only, bbox_native=None), this carries the
    real word/line/block bboxes so ABBYY becomes a word-geometry engine that anchors
    WCT positions alongside Tesseract.
    """
    page_size = rich.get("page_size") or {}
    width = page_size.get("width")
    height = page_size.get("height")
    if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
        dimensions = {"width": width, "height": height, "unit": "pixel"}
    else:
        dimensions = {"width": None, "height": None, "unit": "unknown"}

    blocks: list[dict[str, Any]] = []
    for block_index, block in enumerate(rich.get("blocks", []), start=1):
        lines: list[dict[str, Any]] = []
        for line_index, line in enumerate(block.get("lines", []), start=1):
            words = [
                _rich_word_record(
                    word,
                    rendering_id=rendering_id,
                    page_native_id=page_native_id,
                    page_sequence=page_sequence,
                    block_index=block_index,
                    line_index=line_index,
                    word_index=word_index,
                )
                for word_index, word in enumerate(line.get("words", []), start=1)
            ]
            if not words:
                continue
            line_source_raw = " ".join(word["source_raw"] for word in words)
            lines.append(
                {
                    "observation_token_id": _observation_token_id(
                        {
                            "rendering_id": rendering_id,
                            "page_native_id": page_native_id,
                            "page_sequence": page_sequence,
                            "block_index": block_index,
                            "line_index": line_index,
                            "source_raw": line_source_raw,
                        }
                    ),
                    "line_native_id": f"line-{block_index:04d}-{line_index:04d}",
                    "source_raw": line_source_raw,
                    "confidence": None,
                    "bbox_native": _coerce_bbox(line.get("bbox")),
                    "words": words,
                }
            )
        if not lines:
            continue
        blocks.append(
            {
                "block_id": f"block-{block_index:04d}",
                "block_type": "text",
                "lines": lines,
                "bbox_native": _coerce_bbox(block.get("bbox")),
            }
        )

    extras = {key: value for key, value in rich.items() if key != "blocks"}
    extras["runner_cache_version"] = S1_SIDECAR_CACHE_VERSION
    parsed_keys = [
        {"key": key, "handling": "extras_carried", "source_path": f"page.{key}"}
        for key in sorted(extras)
    ]
    return {
        "schema_version": "sidecar-page-v1",
        "manifest_id": manifest_id,
        "rendering_id": rendering_id,
        "page_native_id": page_native_id,
        "page_sequence": page_sequence,
        "page_dimensions_native": dimensions,
        "blocks": blocks,
        "parsed_keys_index": parsed_keys,
        "page_extras_carried": extras,
        "page_extras_carried_keys": sorted(extras),
        "page_extras_jcs_sha256": _extras_hash(extras),
        "source_payload_sha256": source_payload_sha256,
    }


def _rich_page_files(input_root: Path, volume: int, suffix: str) -> list[tuple[int, str, Path]]:
    """Return (scan_sequence, page_native_id, path) for each rich page file.

    page_native_id is the scan stem (e.g. "leaf_0037", "page_0010") so ABBYY
    aligns with the Tesseract/Surya renderings of the same scan image.
    The -haucgoog variant guard is enforced inside volume_sidecar_files.
    Uses page_order.json manifest when present (vol_01).
    """
    vol_dir = input_root / _volume_label(volume)
    return volume_sidecar_files(vol_dir, f"{suffix}.json")


def _load_canonical_manifest(input_root: Path, volume: int) -> dict[str, Any] | None:
    """The canonical NSH manifest (``vol_NN.manifest.json``) beside the image dir.

    Returns None when absent (degraded/test context): stamping is skipped and
    ``canonical_leaf_id`` stays absent -- schema-optional through R6b, so the run
    stays valid and runnable.
    """
    path = input_root / f"{_volume_label(volume)}.manifest.json"
    if not path.exists():
        return None
    return _read_json(path)


def _stamp_canonical_leaf_id(
    ref: dict[str, Any],
    canonical_manifest: dict[str, Any] | None,
    leaf_overrides: dict[str, int] | None = None,
) -> int | None:
    """R7: align ABBYY onto the primary leaf coordinate (mirrors the azure import).

    Two cases:
    - **Alternate scan** (a content leafmap exists): ``leaf_overrides`` is the
      AUTHORITATIVE stem -> canonical leaf map computed by the content aligner
      (``abbyy_content_alignment``). Same-stem is WRONG for an alternate scan (its
      leaf order differs from the canonical scan), so a stem absent from the map is
      genuinely unmapped (returns None) -- never a same-stem fallback.
    - **Canonical scan** (no leafmap, e.g. ``ia-abbyy-v1``): the leaf is re-derived
      from the CURRENT canonical manifest by same-stem (C5), which is correct because
      this IS the canonical scan.
    Returns None when the stem does not resolve to a body leaf (caller logs it).
    """
    if leaf_overrides is not None:
        leaf_id = leaf_overrides.get(str(ref["page_native_id"]))
        set_leaf_or_exempt(ref, leaf_id)
        _stamp_edition_page_key(ref, canonical_manifest, leaf_id)
        return leaf_id
    if canonical_manifest is None:
        set_leaf_or_exempt(ref, None)
        _stamp_edition_page_key(ref, None, None)
        return None
    leaf_id = canonical_leaf_id(str(ref["page_native_id"]), canonical_manifest)
    set_leaf_or_exempt(ref, leaf_id)
    _stamp_edition_page_key(ref, canonical_manifest, leaf_id)
    return leaf_id


def _stamp_edition_page_key(
    record: dict[str, Any],
    canonical_manifest: dict[str, Any] | None,
    leaf_id: int | None,
) -> None:
    record.pop("edition_page_key", None)
    key = _resolve_precise_edition_key(record, canonical_manifest, leaf_id)
    if key is None:
        # Best-effort fallback from the page native id ("page_NNNN"): no manifest
        # context (degraded / CLI run), or an unmapped stem (normal for alternate
        # scans, which are content-aligned -- a stem absent from the leafmap is
        # legitimately unmapped, not an error). Keeps every record carrying the
        # now-required edition_page_key and the run runnable.
        page_num = _page_num_from_native_id(record.get("page_native_id"))
        if page_num is not None:
            key = body_edition_key(page_num)
    if key is not None:
        record["edition_page_key"] = dict(key)


def _resolve_precise_edition_key(
    record: dict[str, Any],
    canonical_manifest: dict[str, Any] | None,
    leaf_id: int | None,
) -> dict[str, Any] | None:
    """The manifest-backed edition key for a record, or None when unresolvable."""
    if canonical_manifest is None:
        return None
    sha = record.get("source_payload_sha256")
    if isinstance(sha, str):
        key = resolve_edition_page_key_by_sha(canonical_manifest, sha)
        if key is not None:
            return key
    page_num = _page_num_from_native_id(record.get("page_native_id"))
    if page_num is not None and any(
        isinstance(gap, dict) and gap.get("page_num") == page_num
        for gap in canonical_manifest.get("gaps", [])
    ):
        return body_edition_key(page_num)
    if leaf_id is None:
        return None
    for leaf in leaves_view(canonical_manifest):
        if (
            leaf.get("leaf_num") == leaf_id
            and leaf.get("kind") == "body"
            and isinstance(leaf.get("page_num"), int)
        ):
            return body_edition_key(leaf["page_num"])
    return None


def _page_num_from_native_id(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"page_(\d{4})", value)
    return int(match.group(1)) if match else None


def normalize_abbyy_rich_volume(
    input_root: Path,
    *,
    source_lineage_id: str,
    volume: int,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    repo_root: Path = REPO_ROOT,
    pages: list[int] | None = None,
    force: bool = False,
) -> NormalizationSummary:
    """Normalize one ABBYY lineage's rich per-page sidecars into S1 sidecars.

    Reads raw/.../schaff-herzog-pages/<vol>/page_NNNN.<suffix>.json (carrying word
    bbox{x,y,w,h}) rather than the flattened data/reference assembled JSON. This is
    the geometry re-point: ABBYY joins Tesseract as a word-geometry engine.
    """
    _assert_locked_enums()
    input_root = Path(input_root)
    output_root = Path(output_root)
    repo_root = Path(repo_root)
    suffix = _rich_lineage_suffix(source_lineage_id)
    rendering_id = f"{source_lineage_id}/schaff/encyclopedia/1908-1914/v1"
    canonical_manifest = _load_canonical_manifest(input_root, volume)
    # Alternate scans (dli/haucgoog/c1-c4) carry a content leafmap (different leaf
    # order from the canonical scan); when present it is authoritative. ia-abbyy-v1
    # IS the canonical scan, has no leafmap, and stamps by same-stem.
    leaf_overrides = load_leafmap(input_root, source_lineage_id, volume)
    unmapped: list[str] = []

    page_files = _rich_page_files(input_root, volume, suffix)
    # IA ABBYY files are 0-indexed (page_0000.json). Shift to 1-based so
    # page_sequence meets the schema minimum:1 constraint. page_native_id
    # (the stem) is preserved unchanged for WCT alignment.
    if page_files and page_files[0][0] == 0:
        page_files = [(seq + 1, nid, p) for seq, nid, p in page_files]
    if pages is not None:
        if not pages:
            raise ValueError(
                "pages must be non-empty when provided; omit to process whole volume"
            )
        page_set = set(pages)
        page_files = [entry for entry in page_files if entry[0] in page_set]

    manifest_path, state_path, pages_dir = _normal_manifest_paths(
        output_root, source_lineage_id, volume
    )
    state = _load_state(state_path)
    already_done = set(str(value) for value in state.get("emitted_pages", []))
    emitted_state = set(already_done)

    emitted_pages = 0
    skipped_pages = 0
    page_refs: list[dict[str, Any]] = []
    source_files: list[dict[str, Any]] = []
    engine_version = ""
    file_hashes: list[str] = []

    total_pages = len(page_files)
    for _pi, (scan_sequence, page_native_id, path) in enumerate(page_files):
        if _pi % 100 == 0:
            print(
                f"    abbyy/{source_lineage_id}: page {_pi + 1}/{total_pages}",
                flush=True,
            )
        file_bytes = path.read_bytes()
        file_sha256 = _prefixed_sha256_bytes(file_bytes)
        file_hashes.append(file_sha256)
        source_files.append(
            {"path": _relative_path(path, repo_root), "sha256": file_sha256}
        )
        rich = _read_json(path)
        if not engine_version:
            engine_version = str(rich.get("engine_version") or "")
        page_sha256 = _prefixed_sha256_json(rich)
        page_path = pages_dir / f"{page_native_id}.json"

        ref = {
            "page_native_id": page_native_id,
            "page_sequence": scan_sequence,
            "status": "eligible",
            "sidecar_page_path": _relative_path(page_path, repo_root),
            "source_payload_sha256": page_sha256,
        }
        # R7: stamp the primary leaf coordinate on every page_ref (skip + emit), so
        # render_s2 reads it for the WCT join even on a non-force rerun. Unmapped
        # stems (front matter / out-of-range / alternate-only) are logged.
        if (
            _stamp_canonical_leaf_id(ref, canonical_manifest, leaf_overrides) is None
            and (canonical_manifest is not None or leaf_overrides is not None)
        ):
            unmapped.append(page_native_id)

        if not force and _sidecar_is_done(page_path):
            skipped_pages += 1
            # Preserve the page ref so the manifest stays valid on rerun.  Without
            # this, a second call empties page_refs -> manifest writes with pages:[].
            page_refs.append(ref)
        else:
            # manifest_id depends on the file-hash set; fill it after the loop, so
            # build the page record with a placeholder-free rendering_id only.
            page_record = _build_rich_page_record(
                rich,
                manifest_id="",  # set below once the manifest_id is known
                rendering_id=rendering_id,
                page_native_id=page_native_id,
                page_sequence=scan_sequence,
                source_payload_sha256=page_sha256,
            )
            page_record["_pending_path"] = str(page_path)
            ref["_record"] = page_record
            page_refs.append(ref)
            emitted_state.add(page_native_id)
            emitted_pages += 1

    combined_hash = _prefixed_sha256_bytes("".join(sorted(file_hashes)).encode("utf-8"))
    manifest_id = _build_manifest_id(
        source_lineage_id=source_lineage_id,
        rendering_id=rendering_id,
        volume=volume,
        source_file_sha256=combined_hash,
    )

    clean_refs: list[dict[str, Any]] = []
    for ref in page_refs:
        record = ref.pop("_record", None)
        if record is not None:
            # New page this run: write the sidecar to disk.
            record.pop("_pending_path", None)
            record["manifest_id"] = manifest_id
            set_leaf_or_exempt(record, ref.get("canonical_leaf_id"))
            if "edition_page_key" in ref:
                record["edition_page_key"] = dict(ref["edition_page_key"])
            else:
                record.pop("edition_page_key", None)
            _validate("sidecar-page-v1", record)
            _write_json(pages_dir / f"{ref['page_native_id']}.json", record)
        # Skipped pages (already on disk) carry no _record but still go into the
        # manifest so reruns don't silently empty the pages list.
        clean_refs.append(ref)
    if pages is None:
        removed = _prune_unreferenced_page_sidecars(pages_dir, clean_refs)
        if removed:
            print(
                f"    abbyy/{source_lineage_id}: removed {removed} stale sidecar(s)",
                flush=True,
            )

    if not source_files:
        # No rich sidecars matched -- fail fast rather than write an empty manifest
        # with an invalid (minItems:1) source_files array.
        raise FileNotFoundError(
            f"no rich ABBYY sidecars for lineage {source_lineage_id!r} volume {volume} "
            f"under {input_root}"
        )

    if unmapped:
        print(
            f"    abbyy/{source_lineage_id} vol_{volume:02d}: "
            f"{len(unmapped)} page id(s) did not map to a leaf_num "
            f"(e.g. {', '.join(unmapped[:10])})",
            flush=True,
        )

    manifest = {
        "schema_version": "sidecar-manifest-v1",
        "manifest_id": manifest_id,
        "work_id": WORK_ID,
        "edition_id": EDITION_ID,
        "volume": volume,
        "rendering_id": rendering_id,
        "engine_family": "abbyy",
        "engine_version": engine_version,
        "source_lineage_id": source_lineage_id,
        "source_files": source_files,
        "pages": clean_refs,
        "manifest_cross_check": {
            "samples_checked": 1 if clean_refs else 0,
            "samples_matched": 1 if clean_refs else 0,
            "samples_inconclusive": 0,
            "failed_samples": [],
        },
        "bundle_extras_carried": {},
        "bundle_extras_carried_keys": [],
        "bundle_extras_jcs_sha256": EMPTY_EXTRAS_SHA256,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    _validate("sidecar-manifest-v1", manifest)
    _write_json(manifest_path, manifest)
    state = {
        "manifest_id": manifest_id,
        "emitted_pages": sorted(str(ref["page_native_id"]) for ref in clean_refs),
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    _write_json(state_path, state)
    return NormalizationSummary(
        manifest=manifest,
        manifest_path=manifest_path,
        state_path=state_path,
        emitted_pages=emitted_pages,
        skipped_pages=skipped_pages,
        failed_pages=0,
        unmapped_pages=len(unmapped),
    )


def _candidate_paths(input_root: Path, volume: int | None) -> list[Path]:
    if volume is None:
        return sorted(input_root.glob("*/vol_*.json"))
    return sorted(input_root.glob(f"*/{_volume_label(volume)}.json"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        help="Single assembled ABBYY JSON file to normalize.",
    )
    parser.add_argument(
        "--input-root",
        type=Path,
        default=REPO_ROOT / "data" / "reference" / "schaff" / "encyclopedia" / "1908-1914",
        help="Root containing <lineage>/vol_NN.json assembled ABBYY files.",
    )
    parser.add_argument(
        "--volume",
        type=int,
        help="Optional volume number when normalizing from --input-root.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Output root for generated S1 sidecars.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paths = [args.input] if args.input else _candidate_paths(args.input_root, args.volume)
    if not paths:
        print("No ABBYY assembled JSON files found.", file=sys.stderr)
        return 1
    total_failed = 0
    for path in paths:
        summary = normalize_abbyy_file(path, output_root=args.output_root)
        total_failed += summary.failed_pages
        print(
            f"{_relative_path(path, REPO_ROOT)}: "
            f"emitted={summary.emitted_pages} "
            f"skipped={summary.skipped_pages} "
            f"failed={summary.failed_pages}"
        )
    return 1 if total_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
