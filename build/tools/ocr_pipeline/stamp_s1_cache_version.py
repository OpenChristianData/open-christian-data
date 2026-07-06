"""Backfill ``runner_cache_version`` onto legacy S1 sidecars.

## Why this exists

Commit e6a08a98 (2026-06-09) added a ``runner_cache_version`` field to every
S1 sidecar's ``page_extras_carried`` and made the runners verify it before
treating a sidecar as done. The commit did NOT backfill sidecars written
earlier, so every pre-2026-06-09 sidecar carries no version field and now fails
the currentness gate -- a full re-run would re-OCR thousands of pages whose OCR
text is byte-identical to what a fresh run produces. The version value has only
ever been ``s1-sidecar-currentness-v1`` (never bumped), so a missing field means
"written before the field existed", not "produced by an incompatible runner".

This tool stamps the current version onto exactly those legacy sidecars that
already pass *every other* currentness check (image sha, leaf, schema,
rendering_id, no failure_class). A sidecar that fails any other check is left
untouched -- it genuinely needs re-OCR and the runner will redo it.

## Safety

- Dry-run by default. Pass ``--apply`` to write.
- Never stamps a sidecar with a recorded failure, sha mismatch, leaf mismatch,
  wrong schema/rendering_id, or a *different* (non-null) version value.
- Stamping mutates the sidecar's ``page_extras_carried``; the integrity fields
  ``page_extras_carried_keys`` + ``page_extras_jcs_sha256`` are recomputed with
  the runner's own hashing helpers (zero drift), then the record is re-validated
  against ``sidecar-page-v1`` before an atomic write.
- Idempotent: a second run stamps nothing (already-current sidecars are skipped).

## Usage (from repo root)

    py -3 build/tools/ocr_pipeline/stamp_s1_cache_version.py                # dry-run, all engines/vols
    py -3 build/tools/ocr_pipeline/stamp_s1_cache_version.py --apply        # write
    py -3 build/tools/ocr_pipeline/stamp_s1_cache_version.py --engines tesseract --volumes 3 --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[3]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

import build.parsers.s1_kraken_greek_runner as _kraken_greek  # noqa: E402
import build.parsers.s1_kraken_runner as _kraken  # noqa: E402
import build.parsers.s1_surya_runner as _surya  # noqa: E402
import build.parsers.s1_tesseract_runner as _tesseract  # noqa: E402
from build.lib.nsh_leaf_model import resolve_leaf  # noqa: E402
from build.lib.ocr_store_paths import S1_SIDECARS_ROOT  # noqa: E402
from build.lib.paths import REPO_ROOT  # noqa: E402

# Live-OCR runners only. ABBYY is imported OCR (no live cache-version reuse the
# same way) and is out of scope; add it here if it ever needs the same backfill.
ENGINE_RUNNERS = {
    "tesseract": _tesseract,
    "kraken": _kraken,
    "kraken-greek": _kraken_greek,
    "surya": _surya,
}

DEFAULT_ENGINES = ["tesseract", "kraken"]
DEFAULT_VOLUMES = list(range(1, 14))
DEFAULT_INPUT_ROOT = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json_atomic(path: Path, data: Any) -> None:
    """Atomic write (OUT-02): temp file then os.replace, so a partial write
    never poisons a sidecar a later run reads back."""
    tmp = path.with_name(path.name + f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def classify_sidecar(
    sidecar_path: Path,
    *,
    canonical_leaf_id: int | None,
    source_payload_sha256: str,
    runner: Any,
) -> str:
    """Classify one sidecar against the runner's currentness gate.

    Returns one of:
      - "missing"          : no sidecar file on disk
      - "already_current"  : passes runner._sidecar_is_done as-is
      - "stamp"            : fails ONLY because runner_cache_version is absent/None
      - "skip_not_current" : fails for any other reason (re-OCR territory)
    """
    if not sidecar_path.exists():
        return "missing"
    if runner._sidecar_is_done(
        sidecar_path,
        canonical_leaf_id=canonical_leaf_id,
        source_payload_sha256=source_payload_sha256,
    ):
        return "already_current"
    try:
        data = _read_json(sidecar_path)
    except (OSError, ValueError):
        return "skip_not_current"
    if not isinstance(data, dict):
        return "skip_not_current"
    extras = data.get("page_extras_carried", {})
    if not isinstance(extras, dict):
        return "skip_not_current"
    # The version must be the ONLY missing piece. Mirror every other condition
    # of runner._sidecar_is_done; the stamp post-condition (re-running the gate)
    # is the backstop if that gate ever grows a new check this misses.
    version_absent = extras.get("runner_cache_version") is None
    leaf_ok = (
        canonical_leaf_id is None
        or data.get("canonical_leaf_id") == canonical_leaf_id
    )
    other_checks_pass = (
        extras.get("failure_class") is None
        and data.get("schema_version") == "sidecar-page-v1"
        and data.get("rendering_id") == runner.RENDERING_ID
        and data.get("source_payload_sha256") == source_payload_sha256
        and leaf_ok
    )
    if version_absent and other_checks_pass:
        return "stamp"
    return "skip_not_current"


def stamp_sidecar(sidecar_path: Path, *, runner: Any) -> None:
    """Stamp the current cache version onto a legacy sidecar.

    No-op when the sidecar already carries the current version (idempotent).
    Raises when the sidecar carries a DIFFERENT version -- that is not a legacy
    backfill case and must not be silently clobbered (REL-02 fail-fast).
    """
    data = _read_json(sidecar_path)
    extras = data["page_extras_carried"]
    current = extras.get("runner_cache_version")
    if current == runner.S1_SIDECAR_CACHE_VERSION:
        return  # already current -- idempotent no-op, no disk write
    if current is not None:
        raise ValueError(
            f"{sidecar_path}: unexpected runner_cache_version {current!r} "
            f"(expected absent/None for a legacy backfill); refusing to clobber"
        )
    extras["runner_cache_version"] = runner.S1_SIDECAR_CACHE_VERSION
    data["page_extras_carried"] = extras
    data["page_extras_carried_keys"] = sorted(extras)
    data["page_extras_jcs_sha256"] = runner._extras_hash(extras)
    runner._validate("sidecar-page-v1", data)  # schema guard before writing
    _write_json_atomic(sidecar_path, data)


def stamp_volume(
    runner: Any,
    volume: int,
    *,
    input_root: Path,
    s1_root: Path,
    apply: bool,
) -> dict[str, int]:
    """Classify (and optionally stamp) every body sidecar for one (engine, vol).

    Enumerates the OCR-input images exactly as the runner does, resolves each
    image's sha + leaf the same way, and classifies the matching sidecar.
    """
    images = runner._image_paths(input_root, volume)
    _, _, pages_dir = runner._normal_manifest_paths(
        s1_root, runner.SOURCE_LINEAGE_ID, volume
    )
    source_manifest = runner._load_source_manifest(input_root, volume)

    counts = {
        "images": len(images),
        "stamped": 0,
        "already_current": 0,
        "skip_not_current": 0,
        "missing": 0,
    }
    for img in images:
        page_id = img.stem
        sidecar_path = pages_dir / f"{page_id}.json"
        sha = runner._prefixed_sha256_bytes(img.read_bytes())
        leaf: int | None = None
        if source_manifest is not None:
            try:
                leaf, _pn, _stem = resolve_leaf(source_manifest, sha)
            except ValueError:
                leaf = None
        status = classify_sidecar(
            sidecar_path,
            canonical_leaf_id=leaf,
            source_payload_sha256=sha,
            runner=runner,
        )
        if status == "stamp":
            if apply:
                stamp_sidecar(sidecar_path, runner=runner)
                # Post-condition: the runner's own gate must now accept it.
                if not runner._sidecar_is_done(
                    sidecar_path, canonical_leaf_id=leaf, source_payload_sha256=sha
                ):
                    raise RuntimeError(
                        f"{sidecar_path}: still not current after stamping -- "
                        "the currentness gate has a check this tool does not cover"
                    )
            counts["stamped"] += 1
        else:
            counts[status] += 1
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--engines", nargs="+", default=DEFAULT_ENGINES,
        choices=list(ENGINE_RUNNERS), metavar="ENGINE",
        help="S1 engines to backfill (default: tesseract kraken).",
    )
    parser.add_argument(
        "--volumes", type=int, nargs="+", default=DEFAULT_VOLUMES, metavar="N",
        help="Volume numbers (default: 1-13).",
    )
    parser.add_argument("--s1-root", type=Path, default=S1_SIDECARS_ROOT)
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument(
        "--apply", action="store_true", default=False,
        help="Write changes. Omit for a dry-run report (default).",
    )
    args = parser.parse_args(argv)

    volumes = sorted(set(args.volumes))
    invalid = [v for v in volumes if not (1 <= v <= 13)]
    if invalid:
        print(f"ERROR: --volumes out of range (1-13): {invalid}", flush=True)
        return 2

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"stamp_s1_cache_version [{mode}] engines={args.engines} volumes={volumes}", flush=True)

    grand = {"stamped": 0, "already_current": 0, "skip_not_current": 0, "missing": 0}
    for engine in args.engines:
        runner = ENGINE_RUNNERS[engine]
        for vol in volumes:
            try:
                counts = stamp_volume(
                    runner, vol,
                    input_root=args.input_root, s1_root=args.s1_root, apply=args.apply,
                )
            except FileNotFoundError:
                # No image dir / sidecar dir for this (engine, vol) -- nothing to do.
                continue
            verb = "stamped" if args.apply else "would stamp"
            print(
                f"  {engine} vol_{vol:02d}: {counts['stamped']} {verb}, "
                f"{counts['already_current']} already current, "
                f"{counts['skip_not_current']} need re-OCR, "
                f"{counts['missing']} missing",
                flush=True,
            )
            for k in grand:
                grand[k] += counts[k]

    verb = "stamped" if args.apply else "would stamp"
    print(
        f"TOTAL: {grand['stamped']} {verb}, {grand['already_current']} already current, "
        f"{grand['skip_not_current']} need re-OCR, {grand['missing']} missing",
        flush=True,
    )
    if not args.apply and grand["stamped"]:
        print("Dry-run only -- re-run with --apply to write.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
