"""Run Kraken Greek specialist S1 page OCR sidecars through the engine venv subprocess.

Identical to s1_kraken_runner.py except SOURCE_LINEAGE_ID and RENDERING_ID reflect
the Greek specialist lane. ENGINE_FAMILY is still "kraken" so family_independence.py
collapses both Kraken lanes to one independence block by declaration.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jsonschema

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib.engine_inventory import ENGINE_SPECS, venv_python  # noqa: E402
from build.lib.edition_page_key import edition_page_keys_by_sha  # noqa: E402
from build.lib.nsh_leaf_model import resolve_leaf, set_leaf_or_exempt  # noqa: E402
from build.lib.ocr_prerun_log import format_prerun_summary, format_unresolved_leaf_note  # noqa: E402
from build.lib.ocr_store_paths import S1_SIDECARS_ROOT  # noqa: E402
from build.lib.ocr_throttle import subprocess_kwargs_for_throttle as _subprocess_kwargs_for_throttle  # noqa: E402
from build.lib.page_order import volume_image_paths  # noqa: E402
from build.lib.paths import REPO_ROOT  # noqa: E402
from build.lib.schema_enums import get_enum  # noqa: E402


WORK_ID = "schaff-herzog-encyclopedia"
EDITION_ID = "1908-1914"
SOURCE_LINEAGE_ID = "kraken-greek-py312-v1"
RENDERING_ID = f"{SOURCE_LINEAGE_ID}/schaff/encyclopedia/1908-1914/v1"
ENGINE_FAMILY = "kraken"
ENGINE_SPEC_NAME = "kraken-greek"
# Currentness marker checked by _sidecar_is_done before a page counts as "done".
# Bump only when an output-contract change should force re-OCR. Legacy sidecars
# written before 2026-06-09 (e6a08a98) read None here and fail the gate; backfill
# without re-OCR via build/tools/ocr_pipeline/stamp_s1_cache_version.py. See the
# pipeline README for the full reuse model.
S1_SIDECAR_CACHE_VERSION = "s1-sidecar-currentness-v1"
RUNNER_SCRIPT = Path("build") / "tools" / "ocr_runners" / "kraken_greek_page.py"
SUBPROCESS_TIMEOUT = 300
DEFAULT_INPUT_ROOT = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"
DEFAULT_OUTPUT_ROOT = S1_SIDECARS_ROOT
SCHEMA_DIR = REPO_ROOT / "schemas" / "v1"
EMPTY_EXTRAS_SHA256 = (
    "sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
)
# CPU-throttle modes (env + priority) are centralized in build/lib/ocr_throttle.py
# (imported above as _subprocess_kwargs_for_throttle).


@dataclass(frozen=True)
class NormalizationSummary:
    manifest: dict[str, Any]
    manifest_path: Path
    state_path: Path
    emitted_pages: int
    skipped_pages: int
    failed_pages: int


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def _build_manifest_snapshot(
    manifest_id: str,
    volume: int,
    engine_version: str,
    source_files: list[dict[str, Any]],
    page_refs: list[dict[str, Any]],
    failed_pages: int,
    created_at: str,
) -> dict[str, Any]:
    return {
        "schema_version": "sidecar-manifest-v1",
        "manifest_id": manifest_id,
        "work_id": WORK_ID,
        "edition_id": EDITION_ID,
        "volume": volume,
        "rendering_id": RENDERING_ID,
        "engine_family": ENGINE_FAMILY,
        "engine_version": engine_version,
        "source_lineage_id": SOURCE_LINEAGE_ID,
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
        "bundle_extras_jcs_sha256": EMPTY_EXTRAS_SHA256,
        "created_at": created_at,
    }


def _sidecar_is_done(
    page_path: Path,
    *,
    canonical_leaf_id: int | None,
    source_payload_sha256: str,
) -> bool:
    """Return True iff a successful sidecar exists and matches this run."""
    if not page_path.exists():
        return False
    try:
        data = _read_json(page_path)
        return (
            isinstance(data, dict)
            and data.get("page_extras_carried", {}).get("failure_class") is None
            and data.get("schema_version") == "sidecar-page-v1"
            and data.get("rendering_id") == RENDERING_ID
            and data.get("source_payload_sha256") == source_payload_sha256
            # Leaf invalidates a sidecar only when a DEFINITE current leaf disagrees.
            # When the leaf cannot be resolved (canonical_leaf_id is None -- e.g. the
            # source manifest is transiently absent/renamed), fall back to sha-only
            # currentness so a stamped, content-identical sidecar is NOT re-OCR'd (C1).
            and (canonical_leaf_id is None or data.get("canonical_leaf_id") == canonical_leaf_id)
            and data.get("page_extras_carried", {}).get("runner_cache_version")
            == S1_SIDECAR_CACHE_VERSION
        )
    except Exception:  # noqa: BLE001
        return False


def _schema(name: str) -> dict[str, Any]:
    return _read_json(SCHEMA_DIR / f"{name}.schema.json")


def _validate(schema_name: str, record: dict[str, Any]) -> None:
    jsonschema.validate(instance=record, schema=_schema(schema_name))


def _jcs_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _prefixed_sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _prefixed_sha256_json(value: Any) -> str:
    return _prefixed_sha256_bytes(_jcs_bytes(value))


def _raw_artifact_path(pages_dir: Path, page_native_id: str, suffix: str) -> Path:
    return pages_dir.parent / "raw" / f"{page_native_id}{suffix}"


def _raw_artifact_ref(path: Path, repo_root: Path) -> dict[str, str]:
    return {
        "path": _relative_path(path, repo_root),
        "sha256": _prefixed_sha256_bytes(path.read_bytes()),
    }


def _observation_token_id(seed: dict[str, Any]) -> str:
    return "ot-sha256:" + hashlib.sha256(_jcs_bytes(seed)).hexdigest()


def _extras_hash(extras: dict[str, Any]) -> str:
    if not extras:
        return EMPTY_EXTRAS_SHA256
    return _prefixed_sha256_json(extras)


def _relative_path(path: Path, repo_root: Path) -> str:
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def _volume_label(volume: int) -> str:
    return f"vol_{volume:02d}"


def _load_source_manifest(input_root: Path, volume: int) -> dict[str, Any] | None:
    p = Path(input_root) / f"{_volume_label(volume)}.manifest.json"
    return _read_json(p) if p.exists() else None


def _stamp_edition_page_key(record: dict[str, Any], key: dict[str, Any] | None) -> None:
    record.pop("edition_page_key", None)
    if key is not None:
        record["edition_page_key"] = dict(key)


def _line_token_seed(
    canonical_leaf_id: int | None,
    page_native_id: str,
    page_sequence: int,
    block_index: int,
    line_index: int,
    source_raw: str,
    bbox_native: Any,
) -> dict[str, Any]:
    base = {
        "rendering_id": RENDERING_ID,
        "block_index": block_index,
        "line_index": line_index,
        "source_raw": source_raw,
        "bbox_native": bbox_native,
    }
    if canonical_leaf_id is not None:
        base["canonical_leaf_id"] = canonical_leaf_id
    else:
        base["page_native_id"] = page_native_id
        base["page_sequence"] = page_sequence
    return base


def _word_token_seed(
    canonical_leaf_id: int | None,
    page_native_id: str,
    page_sequence: int,
    block_index: int,
    line_index: int,
    word_index: int,
    source_raw: str,
    bbox_native: Any,
) -> dict[str, Any]:
    seed = _line_token_seed(
        canonical_leaf_id,
        page_native_id,
        page_sequence,
        block_index,
        line_index,
        source_raw,
        bbox_native,
    )
    seed["word_index"] = word_index
    return seed


def _page_sequence(index: int, path: Path) -> int:
    match = re.fullmatch(r".*?(\d+)", path.stem)
    if not match:
        return index
    return int(match.group(1))


def _normal_manifest_paths(output_root: Path, source_lineage_id: str, volume: int) -> tuple[Path, Path, Path]:
    run_dir = output_root / source_lineage_id / _volume_label(volume)
    return run_dir / "manifest.json", run_dir / "manifest.state.json", run_dir / "pages"


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"emitted_pages": []}
    state = _read_json(path)
    if not isinstance(state, dict) or not isinstance(state.get("emitted_pages"), list):
        raise ValueError(f"Invalid manifest state marker: {path}")
    return state


def _assert_locked_enums() -> None:
    engine_families = get_enum("sidecar-manifest-v1", "engine_family")
    page_statuses = get_enum("sidecar-manifest-v1", "pages", "status")
    if ENGINE_FAMILY not in engine_families:
        raise RuntimeError(f"sidecar-manifest-v1 engine_family enum missing {ENGINE_FAMILY!r}")
    for status in ("eligible", "corrupt"):
        if status not in page_statuses:
            raise RuntimeError(f"sidecar-manifest-v1 page_status enum missing {status!r}")


def _preflight_kraken_models(_model_dir: Path | None = None) -> None:
    local_dir = _model_dir or (Path(os.path.expanduser("~")) / "ocr-engines" / "kraken-models")
    models = list(local_dir.glob("*.mlmodel")) + list(local_dir.glob("*.safetensors"))
    if not models:
        raise RuntimeError(
            f"No Kraken models found at {local_dir}\n"
            f"Run: py -3 build/tools/download_ocr_models.py"
        )
    empty = [m for m in models if m.stat().st_size == 0]
    if empty:
        raise RuntimeError(
            f"Kraken model file is empty (zero bytes): {empty[0]}\n"
            f"Re-download the model: py -3 build/tools/download_ocr_models.py"
        )


def _build_manifest_id(volume: int, source_file_sha256: str) -> str:
    payload = {
        "source_lineage_id": SOURCE_LINEAGE_ID,
        "rendering_id": RENDERING_ID,
        "volume": volume,
        "source_file_sha256": source_file_sha256,
    }
    return "sm-sha256:" + hashlib.sha256(_jcs_bytes(payload)).hexdigest()


def _image_paths(input_root: Path, volume: int) -> list[Path]:
    volume_dir = input_root / _volume_label(volume)
    return volume_image_paths(volume_dir, include_front_back=True)


def _select_pages(images: list[Path], pages: list[int] | None) -> list[Path]:
    """Filter image list to 1-based page sequence numbers.

    pages=None returns all images. pages=[] is rejected by the caller.
    Raises if the requested pages match no images (all out-of-range).
    """
    if pages is None:
        return images
    page_set = set(pages)
    selected = [
        p for i, p in enumerate(images, start=1)
        if _page_sequence(i, p) in page_set
    ]
    if not selected:
        raise ValueError(
            f"pages {sorted(page_set)} matched no images in volume "
            f"({len(images)} image(s) available)"
        )
    return selected


def _source_files(paths: list[Path], repo_root: Path) -> tuple[list[dict[str, str]], str]:
    refs = [{"path": _relative_path(path, repo_root), "sha256": _prefixed_sha256_bytes(path.read_bytes())} for path in paths]
    return refs, _prefixed_sha256_json(refs)


def _diagnostic_page_record(
    *,
    manifest_id: str,
    page_native_id: str,
    page_sequence: int,
    canonical_leaf_id: int | None,
    source_payload_sha256: str,
    failure_class: str,
    error: str | None,
) -> dict[str, Any]:
    page_extras = {"failure_class": failure_class}
    if error:
        page_extras["error"] = error
    record = {
        "schema_version": "sidecar-page-v1",
        "manifest_id": manifest_id,
        "rendering_id": RENDERING_ID,
        "page_native_id": page_native_id,
        "page_sequence": page_sequence,
        "page_dimensions_native": {"width": None, "height": None, "unit": "unknown"},
        "blocks": [],
        "parsed_keys_index": [
            {"key": key, "handling": "diagnostic_only", "source_path": f"subprocess.{key}"}
            for key in sorted(page_extras)
        ],
        "page_extras_carried": page_extras,
        "page_extras_carried_keys": sorted(page_extras),
        "page_extras_jcs_sha256": _extras_hash(page_extras),
        "source_payload_sha256": source_payload_sha256,
    }
    set_leaf_or_exempt(record, canonical_leaf_id)
    return record


def _observed_blocks(
    page: dict[str, Any],
    canonical_leaf_id: int | None,
    page_native_id: str,
    page_sequence: int,
) -> list[dict[str, Any]]:
    records = []
    for block_index, block in enumerate(page.get("blocks", []), start=1):
        lines = []
        for line_index, line in enumerate(block.get("lines", []), start=1):
            words = []
            for word_index, word in enumerate(line.get("words", []), start=1):
                source_raw = str(word.get("source_raw", ""))
                bbox_native = word.get("bbox_native")
                words.append(
                    {
                        "observation_token_id": _observation_token_id(
                            _word_token_seed(
                                canonical_leaf_id,
                                page_native_id,
                                page_sequence,
                                block_index,
                                line_index,
                                word_index,
                                source_raw,
                                bbox_native,
                            )
                        ),
                        "word_native_id": str(word.get("word_id") or f"word-{block_index:04d}-{line_index:04d}-{word_index:04d}"),
                        "source_raw": source_raw,
                        "confidence": word.get("confidence"),
                        "bbox_native": bbox_native,
                    }
                )
            source_raw = str(line.get("source_raw", ""))
            bbox_native = line.get("bbox_native")
            lines.append(
                {
                    "observation_token_id": _observation_token_id(
                        _line_token_seed(
                            canonical_leaf_id,
                            page_native_id,
                            page_sequence,
                            block_index,
                            line_index,
                            source_raw,
                            bbox_native,
                        )
                    ),
                    "line_native_id": str(line.get("line_id") or f"line-{block_index:04d}-{line_index:04d}"),
                    "source_raw": source_raw,
                    "confidence": line.get("confidence"),
                    "bbox_native": bbox_native,
                    "words": words,
                }
            )
        records.append(
            {
                "block_id": str(block.get("block_id") or f"block-{block_index:04d}"),
                "block_type": str(block.get("block_type") or "text"),
                "lines": lines,
                "bbox_native": block.get("bbox_native"),
            }
        )
    return records


def _page_record(
    *,
    manifest_id: str,
    page_native_id: str,
    page_sequence: int,
    canonical_leaf_id: int | None,
    source_payload_sha256: str,
    subprocess_payload: dict[str, Any],
    raw_artifact: dict[str, str] | None = None,
) -> dict[str, Any]:
    extras = {
        key: value
        for key, value in subprocess_payload.items()
        if key not in {"ok", "blocks", "page_width", "page_height"}
    }
    extras["runner_cache_version"] = S1_SIDECAR_CACHE_VERSION
    if raw_artifact is not None:
        extras["raw_artifact"] = {
            "engine": "kraken-greek",
            "format": "json",
            **raw_artifact,
        }
    record = {
        "schema_version": "sidecar-page-v1",
        "manifest_id": manifest_id,
        "rendering_id": RENDERING_ID,
        "page_native_id": page_native_id,
        "page_sequence": page_sequence,
        "page_dimensions_native": {
            "width": subprocess_payload.get("page_width"),
            "height": subprocess_payload.get("page_height"),
            "unit": "pixel",
        },
        "blocks": _observed_blocks(subprocess_payload, canonical_leaf_id, page_native_id, page_sequence),
        "parsed_keys_index": [
            {"key": key, "handling": "extras_carried", "source_path": f"subprocess.{key}"}
            for key in sorted(extras)
        ],
        "page_extras_carried": extras,
        "page_extras_carried_keys": sorted(extras),
        "page_extras_jcs_sha256": _extras_hash(extras),
        "source_payload_sha256": source_payload_sha256,
    }
    set_leaf_or_exempt(record, canonical_leaf_id)
    return record


def rekey_sidecar(
    record: dict[str, Any],
    *,
    canonical_leaf_id: int | None,
    page_native_id: str,
    page_sequence: int,
    manifest_id: str,
    raw_artifact_new_path: str | None = None,
) -> dict[str, Any]:
    """Return a re-keyed copy of a finished sidecar-page-v1 record."""
    result = copy.deepcopy(record)
    result["manifest_id"] = manifest_id
    result["page_native_id"] = page_native_id
    result["page_sequence"] = page_sequence
    set_leaf_or_exempt(result, canonical_leaf_id)
    for block_index, block in enumerate(result.get("blocks", []), start=1):
        for line_index, line in enumerate(block.get("lines", []), start=1):
            line["observation_token_id"] = _observation_token_id(
                _line_token_seed(
                    canonical_leaf_id,
                    page_native_id,
                    page_sequence,
                    block_index,
                    line_index,
                    line.get("source_raw", ""),
                    line.get("bbox_native"),
                )
            )
            for word_index, word in enumerate(line.get("words", []), start=1):
                word["observation_token_id"] = _observation_token_id(
                    _word_token_seed(
                        canonical_leaf_id,
                        page_native_id,
                        page_sequence,
                        block_index,
                        line_index,
                        word_index,
                        word.get("source_raw", ""),
                        word.get("bbox_native"),
                    )
                )
    extras = result["page_extras_carried"]
    raw_artifact = extras.get("raw_artifact")
    if raw_artifact_new_path is not None and isinstance(raw_artifact, dict):
        raw_artifact["path"] = raw_artifact_new_path
    result["page_extras_carried_keys"] = sorted(extras)
    result["page_extras_jcs_sha256"] = _extras_hash(extras)
    _validate("sidecar-page-v1", result)
    return result


def _run_page(
    image_path: Path,
    timeout: int,
    throttle_mode: str = "full-speed",
    raw_output_path: Path | None = None,
) -> tuple[dict[str, Any] | None, str | None, str | None]:
    engine_spec = next(spec for spec in ENGINE_SPECS if spec.name == ENGINE_SPEC_NAME)
    cmd = [str(venv_python(engine_spec)), str(RUNNER_SCRIPT), "--image", str(image_path)]
    if raw_output_path is not None:
        cmd.extend(["--raw-output", str(raw_output_path)])
    throttle_kwargs = _subprocess_kwargs_for_throttle(throttle_mode)
    try:
        # text=False: kraken_page.py writes UTF-8 bytes to stdout.buffer to
        # avoid cp1252 codec errors on Windows; decode here as UTF-8.
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=False,
            timeout=timeout,
            check=True,
            **throttle_kwargs,
        )
    except subprocess.TimeoutExpired as exc:
        return None, "subprocess_timeout", f"{type(exc).__name__}: {str(exc)[:200]}"
    except subprocess.CalledProcessError as exc:
        stdout_text = (exc.stdout or b"").decode("utf-8", errors="replace")
        try:
            payload = json.loads(stdout_text.strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError):
            payload = {}
        stderr_text = (exc.stderr or b"").decode("utf-8", errors="replace")
        return None, str(payload.get("failure_class") or "subprocess_error"), str(payload.get("error") or stderr_text.strip()[:200])
    stdout_text = result.stdout.decode("utf-8", errors="replace")
    try:
        payload = json.loads(stdout_text.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        return None, "json_parse_error", f"{type(exc).__name__}: {str(exc)[:200]}"
    if not payload.get("ok"):
        return None, str(payload.get("failure_class") or "subprocess_error"), str(payload.get("error") or "")
    return payload, None, None


def normalize_volume(
    *,
    volume: int,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    input_root: Path = DEFAULT_INPUT_ROOT,
    repo_root: Path = REPO_ROOT,
    throttle_mode: str = "full-speed",
    pages: list[int] | None = None,
    force: bool = False,
    shutdown_event: threading.Event | None = None,
) -> NormalizationSummary:
    if pages is not None and not pages:
        raise ValueError(
            "pages must be non-empty when provided; omit to process whole volume"
        )
    _assert_locked_enums()
    _preflight_kraken_models()
    output_root = Path(output_root)
    input_root = Path(input_root)
    repo_root = Path(repo_root)
    images = _select_pages(_image_paths(input_root, volume), pages)
    source_files, source_file_sha256 = _source_files(images, repo_root)
    manifest_id = _build_manifest_id(volume, source_file_sha256)
    source_manifest = _load_source_manifest(input_root, volume)

    edition_key_by_sha = (
        edition_page_keys_by_sha(source_manifest) if source_manifest is not None else {}
    )

    def _edition_key_for(sha: str) -> dict[str, Any] | None:
        return edition_key_by_sha.get(sha)

    def _leaf_id_for(sha: str) -> int | None:
        if source_manifest is None:
            return None
        try:
            leaf_num, _pn, _stem = resolve_leaf(source_manifest, sha)
            return leaf_num
        except ValueError as exc:
            # A recovered-gap / front-back page legitimately has no body leaf
            # (clid_exempt) and joins via edition_page_key instead -- stay quiet.
            # Warn only when the page resolves to NEITHER key (a real defect that
            # also fails sidecar-page-v1 validation downstream).
            note = format_unresolved_leaf_note(
                lineage=SOURCE_LINEAGE_ID,
                volume=volume,
                sha=sha,
                reason=str(exc),
                edition_key=edition_key_by_sha.get(sha),
            )
            if note is not None:
                print(note, flush=True)
            return None

    manifest_path, state_path, pages_dir = _normal_manifest_paths(output_root, SOURCE_LINEAGE_ID, volume)
    state = _load_state(state_path)
    already_done = set(str(value) for value in state.get("emitted_pages", []))
    emitted_state = set(already_done)
    emitted_pages = 0
    skipped_pages = 0
    failed_pages = 0
    page_refs = []
    engine_version = ""
    _run_started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # R6a pre-run reuse summary -- emitted BEFORE any engine call so a redo
    # regression (0 reused / all to OCR on an already-done volume) is obvious.
    # Streaming runner: a cheap pre-pass counts reuse (sha re-read is trivial at
    # ~11 Greek-apparatus pages/volume).
    _reused = 0
    if not force:
        for _img in images:
            _sha = _prefixed_sha256_bytes(_img.read_bytes())
            if _sidecar_is_done(
                pages_dir / f"{_img.stem}.json",
                canonical_leaf_id=_leaf_id_for(_sha),
                source_payload_sha256=_sha,
            ):
                _reused += 1
    print(format_prerun_summary(SOURCE_LINEAGE_ID, volume, len(images), _reused), flush=True)

    for index, image_path in enumerate(images, start=1):
        page_sequence = _page_sequence(index, image_path)
        page_native_id = image_path.stem
        page_path = pages_dir / f"{page_native_id}.json"
        raw_path = _raw_artifact_path(pages_dir, page_native_id, ".kraken-greek.raw.json")
        source_payload_sha256 = _prefixed_sha256_bytes(image_path.read_bytes())
        canonical_leaf_id = _leaf_id_for(source_payload_sha256)
        edition_page_key = _edition_key_for(source_payload_sha256)
        failure_class = None
        if not force and _sidecar_is_done(
            page_path,
            canonical_leaf_id=canonical_leaf_id,
            source_payload_sha256=source_payload_sha256,
        ):
            skipped_pages += 1
            failure_class = None  # sidecar already confirmed clean by _sidecar_is_done
        else:
            payload, failure_class, error = _run_page(
                image_path,
                SUBPROCESS_TIMEOUT,
                throttle_mode=throttle_mode,
                raw_output_path=raw_path,
            )
            if failure_class:
                page_record = _diagnostic_page_record(
                    manifest_id=manifest_id,
                    page_native_id=page_native_id,
                    page_sequence=page_sequence,
                    canonical_leaf_id=canonical_leaf_id,
                    source_payload_sha256=source_payload_sha256,
                    failure_class=failure_class,
                    error=error,
                )
            else:
                engine_version = str(payload.get("engine_version") or engine_version)
                page_record = _page_record(
                    manifest_id=manifest_id,
                    page_native_id=page_native_id,
                    page_sequence=page_sequence,
                    canonical_leaf_id=canonical_leaf_id,
                    source_payload_sha256=source_payload_sha256,
                    subprocess_payload=payload,
                    raw_artifact=_raw_artifact_ref(raw_path, repo_root),
                )
            _stamp_edition_page_key(page_record, edition_page_key)
            _validate("sidecar-page-v1", page_record)
            _write_json(page_path, page_record)
            emitted_pages += 1
            if not failure_class:
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
            "status": "corrupt" if failure_class else "eligible",
            "sidecar_page_path": _relative_path(page_path, repo_root),
            "source_payload_sha256": source_payload_sha256,
        }
        set_leaf_or_exempt(page_ref, canonical_leaf_id)
        _stamp_edition_page_key(page_ref, edition_page_key)
        if failure_class:
            page_ref["failure_class"] = failure_class
        page_refs.append(page_ref)
        _write_json(manifest_path, _build_manifest_snapshot(
            manifest_id, volume, engine_version, source_files,
            list(page_refs), failed_pages, _run_started_at,
        ))
        # Shutdown check -- fall through to manifest write so processed pages are saved.
        if shutdown_event is not None and shutdown_event.is_set():
            print(
                f"    {SOURCE_LINEAGE_ID} vol_{volume:02d}: {index}/{len(images)}"
                f" emitted={emitted_pages} skip={skipped_pages} fail={failed_pages}"
                f" -- shutdown",
                flush=True,
            )
            break

    manifest = _build_manifest_snapshot(
        manifest_id, volume, engine_version, source_files,
        page_refs, failed_pages, _run_started_at,
    )
    _validate("sidecar-manifest-v1", manifest)
    _write_json(manifest_path, manifest)
    _write_json(
        state_path,
        {
            "manifest_id": manifest_id,
            "emitted_pages": sorted(emitted_state),
            "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        },
    )
    return NormalizationSummary(
        manifest=manifest,
        manifest_path=manifest_path,
        state_path=state_path,
        emitted_pages=emitted_pages,
        skipped_pages=skipped_pages,
        failed_pages=failed_pages,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--volume", type=int, required=True)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = normalize_volume(volume=args.volume, output_root=args.output_root, input_root=args.input_root)
    print(
        f"{SOURCE_LINEAGE_ID}/{_volume_label(args.volume)}: "
        f"emitted={summary.emitted_pages} skipped={summary.skipped_pages} failed={summary.failed_pages}"
    )
    return 1 if summary.failed_pages else 0


if __name__ == "__main__":
    raise SystemExit(main())
