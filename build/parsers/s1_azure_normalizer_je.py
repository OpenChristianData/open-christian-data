"""Normalize Azure AI Vision cloud sidecars into S1 sidecar records for the Jewish Encyclopedia.

JE-specific wrapper that reads page_NNNN.azure.json files produced by
run_cloud_ocr.ocr_azure() and emits sidecar-page-v1 records with JE metadata.

JE is a measurement oracle only — never publish, never add to data/.

Usage:
  py -3 build/parsers/s1_azure_normalizer_je.py \\
      --raw-dir .shrink-quarantine/je-surrogate-phase1-20260606/raw/jewish-encyclopedia/ia-pages/vol_02 \\
      --output-dir .shrink-quarantine/je-surrogate-phase1-20260606/reports/je-s1-sidecars/azure-ai-vision-v1/vol_02
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

# Reuse the validated Azure page-record builder — it is engine-specific, not
# work-specific, so importing it here is correct (TEST-02).
from build.parsers.s1_azure_normalizer import (  # noqa: E402
    _build_azure_page_record,
    _is_partial,
)
from build.parsers.s1_abbyy_normalizer import (  # noqa: E402
    EMPTY_EXTRAS_SHA256,
    _prefixed_sha256_bytes,
    _prefixed_sha256_json,
    _read_json,
    _write_json,
)
from build.lib.edition_page_key import body_edition_key  # noqa: E402
from build.lib.nsh_leaf_model import set_leaf_or_exempt  # noqa: E402
from build.lib.paths import REPO_ROOT  # noqa: E402


def _safe_relative_path(path: Path, repo_root: Path) -> str:
    """Return repo-root-relative posix path, falling back to absolute in test contexts."""
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()

logger = logging.getLogger("s1_azure_normalizer_je")

# ---------------------------------------------------------------------------
# JE-specific constants
# ---------------------------------------------------------------------------

WORK_ID = "jewish-encyclopedia.vol_02"
EDITION_ID = "1901-1906"
ENGINE_FAMILY = "azure_read"
ENGINE_ALIAS = "azure-ai-vision-v1"
RENDERING_ID = "azure-ai-vision/jewish-encyclopedia/1901-1906/v1"
SOURCE_LINEAGE_ID = "azure-ai-vision-v1"

_PAGE_NUM_RE = re.compile(r"^page_(\d{4})$")


# ---------------------------------------------------------------------------
# Input discovery
# ---------------------------------------------------------------------------

def _page_num_from_native_id(native_id: str) -> int | None:
    m = _PAGE_NUM_RE.match(native_id)
    return int(m.group(1)) if m else None


def _azure_je_page_files(raw_dir: Path) -> list[tuple[int, str, Path]]:
    """Return sorted (page_num, page_native_id, path) for each azure.json sidecar.

    Excludes *.azure.raw.json (raw API responses stored alongside sidecars).
    """
    results = []
    for path in sorted(raw_dir.glob("page_????.azure.json")):
        native_id = path.stem.replace(".azure", "")  # "page_0038.azure" -> "page_0038"
        page_num = _page_num_from_native_id(native_id)
        if page_num is None:
            logger.warning("Skipping unexpected filename: %s", path.name)
            continue
        results.append((page_num, native_id, path))
    return results


# ---------------------------------------------------------------------------
# Resume helper
# ---------------------------------------------------------------------------

def _sidecar_is_done(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        d = _read_json(path)
        return d.get("schema_version") == "sidecar-page-v1"
    except Exception:  # noqa: BLE001
        return False


def _stamp_je_page_identity(record: dict[str, Any], page_num: int) -> dict[str, Any]:
    set_leaf_or_exempt(record, None)
    record["edition_page_key"] = body_edition_key(page_num)
    return record


# ---------------------------------------------------------------------------
# Volume normalizer
# ---------------------------------------------------------------------------

def normalize_je_azure_volume(
    raw_dir: Path,
    output_dir: Path,
    *,
    force: bool = False,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    """Normalize JE Azure cloud sidecars into S1 sidecar records.

    Args:
        raw_dir: Directory containing page_NNNN.azure.json files.
        output_dir: Root output dir; pages written to output_dir/pages/.
        force: Re-emit even if a valid sidecar already exists.
        repo_root: Repo root for relative-path computation in manifests.

    Returns:
        Dict: emitted_pages, skipped_pages, skipped_partial, failed_pages,
        manifest_path.
    """
    raw_dir = Path(raw_dir)
    output_dir = Path(output_dir)
    repo_root = Path(repo_root)

    page_files = _azure_je_page_files(raw_dir)
    if not page_files:
        raise FileNotFoundError(f"No page_NNNN.azure.json sidecars found in {raw_dir}")

    pages_dir = output_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    emitted_pages = 0
    skipped_pages = 0
    skipped_partial = 0
    failed_pages = 0
    page_refs: list[dict[str, Any]] = []
    source_files: list[dict[str, Any]] = []
    file_hashes: list[str] = []
    engine_version = ""

    for page_num, page_native_id, path in page_files:
        rich = _read_json(path)
        if _is_partial(rich):
            skipped_partial += 1
            logger.warning("Skipping partial sidecar: %s", path.name)
            continue

        file_bytes = path.read_bytes()
        file_sha256 = _prefixed_sha256_bytes(file_bytes)
        file_hashes.append(file_sha256)
        source_files.append(
            {"path": _safe_relative_path(path, repo_root), "sha256": file_sha256}
        )
        if not engine_version:
            engine_version = str(rich.get("engine_version") or "")

        page_sha256 = _prefixed_sha256_json(rich)
        page_path = pages_dir / f"{page_native_id}.json"

        if not force and _sidecar_is_done(page_path):
            skipped_pages += 1
            page_refs.append(
                _stamp_je_page_identity({
                    "page_native_id": page_native_id,
                    "page_sequence": page_num,
                    "status": "eligible",
                    "sidecar_page_path": _safe_relative_path(page_path, repo_root),
                    "source_payload_sha256": page_sha256,
                }, page_num)
            )
        else:
            page_refs.append(
                _stamp_je_page_identity({
                    "page_native_id": page_native_id,
                    "page_sequence": page_num,
                    "status": "eligible",
                    "sidecar_page_path": _safe_relative_path(page_path, repo_root),
                    "source_payload_sha256": page_sha256,
                    "_pending_rich": rich,
                    "_pending_path": page_path,
                }, page_num)
            )

    if not source_files:
        raise FileNotFoundError(
            f"No non-partial azure.json sidecars found in {raw_dir}"
        )

    combined_hash = _prefixed_sha256_bytes(
        "".join(sorted(file_hashes)).encode("utf-8")
    )
    manifest_id = f"sm-{combined_hash}"

    clean_refs: list[dict[str, Any]] = []
    for ref in page_refs:
        rich = ref.pop("_pending_rich", None)
        page_path = ref.pop("_pending_path", None)

        if rich is not None and page_path is not None:
            try:
                record = _build_azure_page_record(
                    rich,
                    manifest_id=manifest_id,
                    rendering_id=RENDERING_ID,
                    page_native_id=ref["page_native_id"],
                    page_sequence=ref["page_sequence"],
                    source_payload_sha256=ref["source_payload_sha256"],
                )
                _stamp_je_page_identity(record, int(ref["page_sequence"]))
                _write_json(page_path, record)
                emitted_pages += 1
                logger.info("Emitted %s", ref["page_native_id"])
            except Exception as exc:  # noqa: BLE001
                failed_pages += 1
                logger.error("Failed %s: %s", ref["page_native_id"], exc)
                ref["status"] = "corrupt"

        clean_refs.append(ref)

    manifest = {
        "schema_version": "sidecar-manifest-v1",
        "manifest_id": manifest_id,
        "work_id": WORK_ID,
        "edition_id": EDITION_ID,
        "volume": 2,
        "rendering_id": RENDERING_ID,
        "engine_family": ENGINE_FAMILY,
        "engine_version": engine_version,
        "source_lineage_id": SOURCE_LINEAGE_ID,
        "source_files": source_files,
        "pages": clean_refs,
        "bundle_extras_carried": {},
        "bundle_extras_carried_keys": [],
        "bundle_extras_jcs_sha256": EMPTY_EXTRAS_SHA256,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    _write_json(output_dir / "manifest.json", manifest)

    logger.info(
        "JE Azure: emitted=%d skipped=%d partial=%d failed=%d",
        emitted_pages, skipped_pages, skipped_partial, failed_pages,
    )
    return {
        "emitted_pages": emitted_pages,
        "skipped_pages": skipped_pages,
        "skipped_partial": skipped_partial,
        "failed_pages": failed_pages,
        "manifest_path": output_dir / "manifest.json",
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Emit S1 Azure sidecars for JE Vol 2 from page_NNNN.azure.json files"
    )
    ap.add_argument(
        "--raw-dir", required=True, type=Path,
        help="Directory containing page_NNNN.azure.json files",
    )
    ap.add_argument(
        "--output-dir", required=True, type=Path,
        help="Output root; pages written to output-dir/pages/",
    )
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    result = normalize_je_azure_volume(args.raw_dir, args.output_dir, force=args.force)
    sys.stdout.write(
        f"emitted={result['emitted_pages']} "
        f"skipped={result['skipped_pages']} "
        f"partial={result['skipped_partial']} "
        f"failed={result['failed_pages']}\n"
    )
    return 0 if result["failed_pages"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
