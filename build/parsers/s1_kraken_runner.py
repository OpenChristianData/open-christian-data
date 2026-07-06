"""Run Kraken S1 page OCR sidecars through the engine venv subprocess."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

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
SOURCE_LINEAGE_ID = "kraken-py312-v1"
RENDERING_ID = f"{SOURCE_LINEAGE_ID}/schaff/encyclopedia/1908-1914/v1"
ENGINE_FAMILY = "kraken"
# Currentness marker written into every sidecar's page_extras_carried and
# checked by _sidecar_is_done (below) before a page is treated as "done".
# Bump this string only when a runner/output-contract change should force re-OCR.
# Landmine: this field was added 2026-06-09 (e6a08a98) WITHOUT backfilling
# existing sidecars, so pre-2026-06-09 sidecars read None here and fail the gate
# -> a naive re-run re-OCRs them needlessly. The value has never changed, so a
# missing field means "written before the field existed", not "incompatible".
# Backfill without re-OCR via build/tools/ocr_pipeline/stamp_s1_cache_version.py.
S1_SIDECAR_CACHE_VERSION = "s1-sidecar-currentness-v1"
RUNNER_SCRIPT = Path("build") / "tools" / "ocr_runners" / "kraken_page.py"
SUBPROCESS_TIMEOUT = 600
# Downscale images wider than this before inference; bboxes scaled back to native.
# blla.segment normalises internally so segmentation time is constant regardless of
# input width; only rpred.rpred (recognition) scales with input area. At 1800px the
# NSH scans (5034px wide) drop recognition time ~66% with <0.1% word-count change.
BATCH_MAX_WIDTH = 1800
# PyTorch CPU allocator fragments memory across sequential page inferences; after ~9
# pages in one subprocess the allocator slows enough to push normal pages past the
# timeout. Restarting every 7 pages keeps allocations in the fast region.
BATCH_MAX_PAGES = 7
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


class _ShutdownRequested(Exception):
    """Raised when the pipeline asks the Kraken batch worker to stop."""


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
    parsed = int(match.group(1))
    return parsed if parsed >= 1 else index


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
            "engine": "kraken",
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
    engine_spec = next(spec for spec in ENGINE_SPECS if spec.name == ENGINE_FAMILY)
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


def _run_batch(
    items: list[tuple[Path, Path | None]],
    timeout_per_page: int,
    throttle_mode: str = "full-speed",
    max_width: int = BATCH_MAX_WIDTH,
    max_pages: int = BATCH_MAX_PAGES,
    shutdown_event: threading.Event | None = None,
) -> Generator[tuple[dict[str, Any] | None, str | None, str | None], None, None]:
    """Yield (payload, failure_class, error) for each (image_path, raw_output_path) pair.

    Each subprocess handles at most max_pages items before being restarted. This
    prevents PyTorch CPU allocator fragmentation from accumulating across many pages
    in one process, which would otherwise cause normal pages to exceed the timeout
    after ~9 sequential inferences.

    Within each chunk: a hung page times out after timeout_per_page seconds; its
    subprocess is killed and a new subprocess starts for the remaining pages. Only
    the hung page is marked failed.

    A subprocess crash (exits early) yields synthetic errors for remaining pages in
    that chunk without restarting.
    """
    remaining = list(items)
    while remaining:
        chunk = remaining[:max_pages]
        restarting = False
        for i, result in enumerate(_run_chunk(chunk, timeout_per_page, throttle_mode, max_width, shutdown_event)):
            yield result
            if result[1] == "subprocess_timeout_batch":
                remaining = chunk[i + 1:] + remaining[max_pages:]
                restarting = True
                break
        if not restarting:
            remaining = remaining[max_pages:]


def _run_chunk(
    items: list[tuple[Path, Path | None]],
    timeout_per_page: int,
    throttle_mode: str = "full-speed",
    max_width: int = BATCH_MAX_WIDTH,
    shutdown_event: threading.Event | None = None,
) -> Generator[tuple[dict[str, Any] | None, str | None, str | None], None, None]:
    """Run one Kraken subprocess for the given items.

    On timeout: yields the timeout error for the hung page then returns.
    _run_batch restarts a new subprocess for any remaining items.
    On subprocess crash: yields synthetic errors for remaining items (no restart).
    """
    if not items:
        return

    manifest = [
        {"image": str(img), "raw_output": str(raw) if raw is not None else None}
        for img, raw in items
    ]
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(manifest, f)
        manifest_path = Path(f.name)

    try:
        engine_spec = next(spec for spec in ENGINE_SPECS if spec.name == ENGINE_FAMILY)
        cmd = [
            str(venv_python(engine_spec)),
            str(RUNNER_SCRIPT),
            "--batch-manifest-file", str(manifest_path),
        ]
        if max_width > 0:
            cmd += ["--max-width", str(max_width)]
        throttle_kwargs = _subprocess_kwargs_for_throttle(throttle_mode)

        process: subprocess.Popen[bytes] | None = None
        _reader_thread: threading.Thread | None = None

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **throttle_kwargs,
        )

        # Windows pipes don't support select(), so a raw stdout iteration blocks
        # forever if the subprocess hangs on a page. A reader thread pushes lines
        # into a queue so the main loop can apply a per-page deadline.
        _line_q: queue.Queue[bytes | None] = queue.Queue()

        def _reader(stream: Any, q: queue.Queue[bytes | None]) -> None:
            try:
                for line in stream:
                    q.put(line)
            finally:
                q.put(None)  # sentinel: stream done

        _reader_thread = threading.Thread(target=_reader, args=(process.stdout, _line_q), daemon=True)
        _reader_thread.start()

        process_alive = True
        timed_out = False
        emitted = 0
        for _ in items:
            if not process_alive:
                if timed_out:
                    return  # _run_batch restarts; don't mark remaining pages as failed
                yield None, "subprocess_error", "batch subprocess exited before producing all expected output"
                emitted += 1
                continue

            deadline = time.monotonic() + timeout_per_page
            result_payload: dict[str, Any] | None = None
            result_fc: str | None = None
            result_err: str | None = None

            while True:
                if shutdown_event is not None and shutdown_event.is_set():
                    try:
                        process.kill()
                    except OSError:
                        pass
                    process_alive = False
                    raise _ShutdownRequested

                time_left = deadline - time.monotonic()
                if time_left <= 0:
                    try:
                        process.kill()
                    except OSError:
                        pass
                    process_alive = False
                    timed_out = True
                    result_fc = "subprocess_timeout_batch"
                    result_err = (
                        f"Kraken produced no output for >{timeout_per_page}s; "
                        f"subprocess killed and page marked failed"
                    )
                    break

                try:
                    line_bytes = _line_q.get(timeout=min(time_left, 5.0))
                except queue.Empty:
                    continue  # re-check deadline

                if line_bytes is None:
                    process_alive = False
                    result_fc = "subprocess_error"
                    result_err = "batch subprocess exited before producing output for this page"
                    break

                line_text = line_bytes.decode("utf-8", errors="replace").strip()
                if not line_text:
                    continue  # blank line; deadline still applies

                try:
                    payload = json.loads(line_text)
                except json.JSONDecodeError as exc:
                    result_fc = "json_parse_error"
                    result_err = f"JSONDecodeError: {str(exc)[:200]}"
                    break

                if not payload.get("ok"):
                    result_fc = str(payload.get("failure_class") or "subprocess_error")
                    result_err = str(payload.get("error") or "")
                else:
                    result_payload = payload
                break

            if result_payload is not None:
                yield result_payload, None, None
            else:
                yield None, result_fc, result_err
            emitted += 1

            if timed_out:
                return  # Stop after the timeout error; _run_batch restarts

        # Safety net: subprocess crash may exit with fewer lines than expected.
        while emitted < len(items):
            yield None, "subprocess_error", "batch subprocess produced fewer output lines than expected"
            emitted += 1

    finally:
        # Kill process first so the reader thread unblocks, then join.
        # Reached on normal exit, crash, timeout return, and GeneratorExit (shutdown).
        if process is not None:
            if process.poll() is None:
                try:
                    process.kill()
                except OSError:
                    pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        if _reader_thread is not None:
            _reader_thread.join(timeout=5.0)
        manifest_path.unlink(missing_ok=True)


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

    # Pre-compute pending pages so we can batch them into a single subprocess.
    _pending_items: list[tuple[Path, Path | None]] = []  # (image_path, raw_path)
    _pending_native_ids: set[str] = set()
    for _img in images:
        _pid = _img.stem
        _pp = pages_dir / f"{_pid}.json"
        _sha = _prefixed_sha256_bytes(_img.read_bytes())
        _canonical_leaf_id = _leaf_id_for(_sha)
        if not force and _sidecar_is_done(
            _pp,
            canonical_leaf_id=_canonical_leaf_id,
            source_payload_sha256=_sha,
        ):
            continue
        _pending_items.append((_img, _raw_artifact_path(pages_dir, _pid, ".kraken.raw.json")))
        _pending_native_ids.add(_pid)

    # R6a pre-run reuse summary -- emitted BEFORE any engine call so a redo
    # regression (0 reused / all to OCR on an already-done volume) is obvious.
    print(
        format_prerun_summary(
            SOURCE_LINEAGE_ID, volume, len(images), len(images) - len(_pending_native_ids)
        ),
        flush=True,
    )

    _batch_results = _run_batch(
        _pending_items,
        timeout_per_page=SUBPROCESS_TIMEOUT,
        throttle_mode=throttle_mode,
        shutdown_event=shutdown_event,
    )

    _total_pages = len(images)
    _loop_start = time.monotonic()
    for index, image_path in enumerate(images, start=1):
        page_sequence = _page_sequence(index, image_path)
        page_native_id = image_path.stem
        page_path = pages_dir / f"{page_native_id}.json"
        raw_path = _raw_artifact_path(pages_dir, page_native_id, ".kraken.raw.json")
        source_payload_sha256 = _prefixed_sha256_bytes(image_path.read_bytes())
        canonical_leaf_id = _leaf_id_for(source_payload_sha256)
        edition_page_key = _edition_key_for(source_payload_sha256)
        failure_class = None
        if page_native_id not in _pending_native_ids:
            skipped_pages += 1
            failure_class = None  # sidecar already confirmed clean by _sidecar_is_done
        else:
            try:
                payload, failure_class, error = next(_batch_results)
            except _ShutdownRequested:
                _elapsed = time.monotonic() - _loop_start
                print(
                    f"    {SOURCE_LINEAGE_ID} vol_{volume:02d}: {index}/{_total_pages}"
                    f" emitted={emitted_pages} skip={skipped_pages} fail={failed_pages}"
                    f" {_elapsed:.0f}s elapsed -- shutdown",
                    flush=True,
                )
                break
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
            # Only record success in the state; failed pages are omitted so they
            # are retried on the next run rather than permanently skipped.
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
        # Shutdown check -- state and manifest are already persisted, stopping here loses no work.
        if shutdown_event is not None and shutdown_event.is_set():
            _elapsed = time.monotonic() - _loop_start
            print(
                f"    {SOURCE_LINEAGE_ID} vol_{volume:02d}: {index}/{_total_pages}"
                f" emitted={emitted_pages} skip={skipped_pages} fail={failed_pages}"
                f" {_elapsed:.0f}s elapsed -- shutdown",
                flush=True,
            )
            if page_native_id in _pending_native_ids:
                _batch_results.close()
            break
        if index % 25 == 0 or index == _total_pages:
            _elapsed = time.monotonic() - _loop_start
            _rate = index / _elapsed if _elapsed > 0 else 0
            _eta = (_total_pages - index) / _rate if _rate > 0 else 0
            print(
                f"    {SOURCE_LINEAGE_ID} vol_{volume:02d}: {index}/{_total_pages}"
                f" emitted={emitted_pages} skip={skipped_pages} fail={failed_pages}"
                f" {_elapsed:.0f}s elapsed"
                + (f" eta={_eta:.0f}s" if _rate > 0 and index < _total_pages else ""),
                flush=True,
            )

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
