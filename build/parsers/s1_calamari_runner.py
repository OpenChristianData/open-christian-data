"""Run Calamari S1 page OCR sidecars through the engine venv subprocess."""

# RETIRED 2026-05-31: Calamari tested on NSH scans; insufficient quality.
# Non-white background (~128 gray) required custom normalisation that still
# underperformed Kraken and Surya. File kept for audit trail; not invoked.

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jsonschema

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib.edition_page_key import edition_page_keys_by_sha  # noqa: E402
from build.lib.engine_inventory import ENGINE_SPECS, EngineSpec, venv_python  # noqa: E402
from build.lib.ocr_store_paths import S1_SIDECARS_ROOT  # noqa: E402
from build.lib.ocr_throttle import subprocess_kwargs_for_throttle as _subprocess_kwargs_for_throttle  # noqa: E402
from build.lib.page_order import volume_image_paths  # noqa: E402
from build.lib.paths import REPO_ROOT  # noqa: E402
from build.lib.schema_enums import get_enum  # noqa: E402


WORK_ID = "schaff-herzog-encyclopedia"
EDITION_ID = "1908-1914"
SOURCE_LINEAGE_ID = "calamari-py311-v1"
RENDERING_ID = f"{SOURCE_LINEAGE_ID}/schaff/encyclopedia/1908-1914/v1"
ENGINE_FAMILY = "calamari"
RUNNER_SCRIPT = Path("build") / "tools" / "ocr_runners" / "calamari_page.py"
# Calamari uses TensorFlow on CPU with a 5-checkpoint ensemble; 35 lines
# per page takes ~3-5 min with batching + 2000px width cap. 900s gives
# comfortable headroom for model load (~30s) + inference.
SUBPROCESS_TIMEOUT = 900
MAX_CHECKPOINTS: int = 0
DEFAULT_INPUT_ROOT = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"
DEFAULT_OUTPUT_ROOT = S1_SIDECARS_ROOT
SCHEMA_DIR = REPO_ROOT / "schemas" / "v1"
# Default pre-trained model for antiqua (Roman typeface) historical print.
# Calamari-OCR/calamari_models release 2.2, compatible with Calamari 2.3.x.
# Download via: py -3 build/tools/download_ocr_models.py
DEFAULT_CALAMARI_MODEL_DIR = (
    Path(os.path.expanduser("~")) / "ocr-engines" / "calamari-models" / "antiqua_historical"
)
RETIRED_ENGINE_SPEC = EngineSpec("calamari", "calamari", "calamari-py311", "calamari_ocr", "readiness")
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


def _source_files(paths: list[Path], repo_root: Path) -> tuple[list[dict[str, str]], str]:
    refs = [{"path": _relative_path(path, repo_root), "sha256": _prefixed_sha256_bytes(path.read_bytes())} for path in paths]
    return refs, _prefixed_sha256_json(refs)


def _diagnostic_page_record(
    *,
    manifest_id: str,
    page_native_id: str,
    page_sequence: int,
    source_payload_sha256: str,
    failure_class: str,
    error: str | None,
) -> dict[str, Any]:
    page_extras = {"failure_class": failure_class}
    if error:
        page_extras["error"] = error
    return {
        "schema_version": "sidecar-page-v1",
        "clid_exempt": True,
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


def _observed_blocks(page: dict[str, Any], page_sequence: int) -> list[dict[str, Any]]:
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
                            {
                                "rendering_id": RENDERING_ID,
                                "page_sequence": page_sequence,
                                "block_index": block_index,
                                "line_index": line_index,
                                "word_index": word_index,
                                "source_raw": source_raw,
                                "bbox_native": bbox_native,
                            }
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
                        {
                            "rendering_id": RENDERING_ID,
                            "page_sequence": page_sequence,
                            "block_index": block_index,
                            "line_index": line_index,
                            "source_raw": source_raw,
                            "bbox_native": bbox_native,
                        }
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
    source_payload_sha256: str,
    subprocess_payload: dict[str, Any],
) -> dict[str, Any]:
    extras = {
        key: value
        for key, value in subprocess_payload.items()
        if key not in {"ok", "blocks", "page_width", "page_height"}
    }
    return {
        "schema_version": "sidecar-page-v1",
        "clid_exempt": True,
        "manifest_id": manifest_id,
        "rendering_id": RENDERING_ID,
        "page_native_id": page_native_id,
        "page_sequence": page_sequence,
        "page_dimensions_native": {
            "width": subprocess_payload.get("page_width"),
            "height": subprocess_payload.get("page_height"),
            "unit": "pixel",
        },
        "blocks": _observed_blocks(subprocess_payload, page_sequence),
        "parsed_keys_index": [
            {"key": key, "handling": "extras_carried", "source_path": f"subprocess.{key}"}
            for key in sorted(extras)
        ],
        "page_extras_carried": extras,
        "page_extras_carried_keys": sorted(extras),
        "page_extras_jcs_sha256": _extras_hash(extras),
        "source_payload_sha256": source_payload_sha256,
    }


def _stamp_edition_page_key(record: dict[str, Any], key: dict[str, Any] | None) -> None:
    record.pop("edition_page_key", None)
    if key is not None:
        record["edition_page_key"] = dict(key)


def _resolve_model_dir() -> Path | None:
    """Return the default Calamari model directory if it exists, else None."""
    if DEFAULT_CALAMARI_MODEL_DIR.is_dir() and any(DEFAULT_CALAMARI_MODEL_DIR.iterdir()):
        return DEFAULT_CALAMARI_MODEL_DIR
    return None


def _run_page(
    image_path: Path,
    timeout: int,
    model_dir: Path,
    throttle_mode: str = "full-speed",
    max_checkpoints: int = MAX_CHECKPOINTS,
) -> tuple[dict[str, Any] | None, str | None, str | None]:
    engine_spec = next(
        (spec for spec in ENGINE_SPECS if spec.name == ENGINE_FAMILY),
        RETIRED_ENGINE_SPEC,
    )
    cmd = [str(venv_python(engine_spec)), str(RUNNER_SCRIPT), "--image", str(image_path)]
    cmd += ["--model", str(model_dir)]
    cmd += ["--max-checkpoints", str(max_checkpoints)]
    throttle_kwargs = _subprocess_kwargs_for_throttle(throttle_mode)
    try:
        # text=False: calamari_page.py writes UTF-8 bytes to stdout.buffer;
        # decode here to avoid cp1252 errors on non-Latin OCR characters.
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
    max_checkpoints: int = MAX_CHECKPOINTS,
) -> NormalizationSummary:
    _assert_locked_enums()
    model_dir = _resolve_model_dir()
    if model_dir is None:
        raise RuntimeError(
            f"Calamari model directory not found or empty: {DEFAULT_CALAMARI_MODEL_DIR}\n"
            f"Run: py -3 build/tools/download_ocr_models.py"
        )
    output_root = Path(output_root)
    input_root = Path(input_root)
    repo_root = Path(repo_root)
    images = _image_paths(input_root, volume)
    source_files, source_file_sha256 = _source_files(images, repo_root)
    manifest_id = _build_manifest_id(volume, source_file_sha256)
    # Calamari threads no leaf (clid_exempt -- see below), but edition_page_key
    # is required on every page; resolve it by sha from the source manifest.
    source_manifest_path = input_root / f"vol_{volume:02d}.manifest.json"
    source_manifest = _read_json(source_manifest_path) if source_manifest_path.exists() else None
    edition_key_by_sha = (
        edition_page_keys_by_sha(source_manifest) if source_manifest is not None else {}
    )
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

    for index, image_path in enumerate(images, start=1):
        page_sequence = _page_sequence(index, image_path)
        page_native_id = image_path.stem
        page_path = pages_dir / f"page_{page_sequence:04d}.json"
        source_payload_sha256 = _prefixed_sha256_bytes(image_path.read_bytes())
        failure_class = None
        if page_native_id in already_done and page_path.exists():
            skipped_pages += 1
            # Re-read failure_class from the prior-run page file so the manifest
            # correctly reflects whether this page actually succeeded.
            try:
                prior = _read_json(page_path)
                failure_class = prior.get("page_extras_carried", {}).get("failure_class")
            except Exception:  # noqa: BLE001
                # Page file is unreadable or malformed -- treat as corrupt so
                # the manifest does not silently promote it to eligible.
                failure_class = "page_file_corrupt"
        else:
            payload, failure_class, error = _run_page(
                image_path,
                SUBPROCESS_TIMEOUT,
                model_dir,
                throttle_mode=throttle_mode,
                max_checkpoints=max_checkpoints,
            )
            if failure_class:
                page_record = _diagnostic_page_record(
                    manifest_id=manifest_id,
                    page_native_id=page_native_id,
                    page_sequence=page_sequence,
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
                    source_payload_sha256=source_payload_sha256,
                    subprocess_payload=payload,
                )
            _stamp_edition_page_key(page_record, edition_key_by_sha.get(source_payload_sha256))
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
        # Calamari is outside the leaf-rekey set (R2 keyed tesseract/kraken/surya/
        # kraken-greek only; no calamari NSH cells exist) so it threads no leaf --
        # its records are clid_exempt under the R5 required-or-exempt schemas.
        page_ref = {
            "page_native_id": page_native_id,
            "page_sequence": page_sequence,
            "status": "corrupt" if failure_class else "eligible",
            "sidecar_page_path": _relative_path(page_path, repo_root),
            "source_payload_sha256": source_payload_sha256,
            "clid_exempt": True,
        }
        if failure_class:
            page_ref["failure_class"] = failure_class
        _stamp_edition_page_key(page_ref, edition_key_by_sha.get(source_payload_sha256))
        page_refs.append(page_ref)
        _write_json(manifest_path, _build_manifest_snapshot(
            manifest_id, volume, engine_version, source_files,
            list(page_refs), failed_pages, _run_started_at,
        ))

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
