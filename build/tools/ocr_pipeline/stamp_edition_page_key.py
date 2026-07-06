"""Backfill ``edition_page_key`` onto existing live-engine S1 sidecars.

This is a zero-re-OCR disk backfill. It enumerates the same OCR-input images
as each live S1 runner, resolves each image SHA through the source manifest,
and stamps only the optional ``edition_page_key`` field onto existing sidecar
JSON records. It never creates a sidecar and never invokes an OCR engine.

Safety:

- Dry-run by default. Pass ``--apply`` to write.
- Idempotent: already keyed sidecars are no-ops.
- Unresolved SHAs are left untouched.
- A different existing key fails fast on apply unless ``--force-rekey`` is
  passed explicitly.
- Each write is schema-validated before an atomic replace.
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
from build.lib.edition_page_key import resolve_edition_page_key_by_sha  # noqa: E402
from build.lib.ocr_store_paths import S1_SIDECARS_ROOT  # noqa: E402
from build.lib.paths import REPO_ROOT  # noqa: E402

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
    tmp = path.with_name(path.name + f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def classify_sidecar(sidecar_path: Path, *, edition_page_key: dict[str, Any] | None) -> str:
    """Classify one sidecar for edition-key stamping.

    Returns one of:
      - ``missing``       : no sidecar on disk
      - ``unresolved``    : the image SHA does not resolve to an edition key
      - ``already_keyed`` : the sidecar already carries the same key
      - ``stamp``         : the sidecar exists and needs this key written
    """
    if not sidecar_path.exists():
        return "missing"
    if edition_page_key is None:
        return "unresolved"

    data = _read_json(sidecar_path)
    if not isinstance(data, dict):
        return "unresolved"
    current = data.get("edition_page_key")
    if current == edition_page_key:
        return "already_keyed"
    return "stamp"


def stamp_sidecar(
    sidecar_path: Path,
    *,
    edition_page_key: dict[str, Any],
    runner: Any,
    force_rekey: bool = False,
) -> None:
    """Set only ``edition_page_key`` on an existing sidecar and validate it."""
    data = _read_json(sidecar_path)
    if not isinstance(data, dict):
        raise ValueError(f"{sidecar_path}: sidecar JSON is not an object")

    current = data.get("edition_page_key")
    if current == edition_page_key:
        return
    if current is not None and not force_rekey:
        raise ValueError(
            f"{sidecar_path}: existing edition_page_key {current!r} differs "
            f"from resolved key {edition_page_key!r}; refusing to rekey without --force-rekey"
        )

    data["edition_page_key"] = dict(edition_page_key)
    runner._validate("sidecar-page-v1", data)
    _write_json_atomic(sidecar_path, data)


def stamp_volume(
    runner: Any,
    volume: int,
    *,
    input_root: Path,
    s1_root: Path,
    apply: bool,
    force_rekey: bool = False,
) -> dict[str, int]:
    """Classify and optionally stamp every sidecar for one engine/volume."""
    images = runner._image_paths(input_root, volume)
    _, _, pages_dir = runner._normal_manifest_paths(
        s1_root, runner.SOURCE_LINEAGE_ID, volume
    )
    source_manifest = runner._load_source_manifest(input_root, volume)

    counts = {
        "images": len(images),
        "stamped": 0,
        "already_keyed": 0,
        "unresolved": 0,
        "missing": 0,
    }
    for img in images:
        sidecar_path = pages_dir / f"{img.stem}.json"
        sha = runner._prefixed_sha256_bytes(img.read_bytes())
        edition_page_key = (
            resolve_edition_page_key_by_sha(source_manifest, sha)
            if source_manifest is not None
            else None
        )
        status = classify_sidecar(sidecar_path, edition_page_key=edition_page_key)
        if status == "stamp":
            if apply:
                if edition_page_key is None:
                    raise RuntimeError(f"{sidecar_path}: internal error: stamp without key")
                stamp_sidecar(
                    sidecar_path,
                    edition_page_key=edition_page_key,
                    runner=runner,
                    force_rekey=force_rekey,
                )
                data = _read_json(sidecar_path)
                if data.get("edition_page_key") != edition_page_key:
                    raise RuntimeError(f"{sidecar_path}: edition_page_key missing after stamp")
            counts["stamped"] += 1
        else:
            counts[status] += 1
    return counts


def _print_summary(engine: str, volume: int, counts: dict[str, int], *, apply: bool) -> None:
    verb = "stamped" if apply else "would stamp"
    print(
        f"  {engine} vol_{volume:02d}: {counts['stamped']} {verb}, "
        f"{counts['already_keyed']} already keyed, "
        f"{counts['unresolved']} unresolved, "
        f"{counts['missing']} missing",
        flush=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--engines",
        nargs="+",
        default=DEFAULT_ENGINES,
        choices=list(ENGINE_RUNNERS),
        metavar="ENGINE",
        help="S1 engines to backfill (default: tesseract kraken).",
    )
    parser.add_argument(
        "--volumes",
        type=int,
        nargs="+",
        default=DEFAULT_VOLUMES,
        metavar="N",
        help="Volume numbers (default: 1-13).",
    )
    parser.add_argument("--s1-root", type=Path, default=S1_SIDECARS_ROOT)
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Write changes. Omit for a dry-run report (default).",
    )
    parser.add_argument(
        "--force-rekey",
        action="store_true",
        default=False,
        help="Allow replacing a different existing edition_page_key on --apply.",
    )
    args = parser.parse_args(argv)

    volumes = sorted(set(args.volumes))
    invalid = [v for v in volumes if not (1 <= v <= 13)]
    if invalid:
        print(f"ERROR: --volumes out of range (1-13): {invalid}", flush=True)
        return 2
    if args.force_rekey and not args.apply:
        print("ERROR: --force-rekey is only meaningful with --apply", flush=True)
        return 2

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"stamp_edition_page_key [{mode}] engines={args.engines} volumes={volumes}", flush=True)

    grand = {"stamped": 0, "already_keyed": 0, "unresolved": 0, "missing": 0}
    for engine in args.engines:
        runner = ENGINE_RUNNERS[engine]
        for vol in volumes:
            try:
                counts = stamp_volume(
                    runner,
                    vol,
                    input_root=args.input_root,
                    s1_root=args.s1_root,
                    apply=args.apply,
                    force_rekey=args.force_rekey,
                )
            except FileNotFoundError:
                continue
            _print_summary(engine, vol, counts, apply=args.apply)
            for key in grand:
                grand[key] += counts[key]

    verb = "stamped" if args.apply else "would stamp"
    print(
        f"TOTAL: {grand['stamped']} {verb}, {grand['already_keyed']} already keyed, "
        f"{grand['unresolved']} unresolved, {grand['missing']} missing",
        flush=True,
    )
    if not args.apply and grand["stamped"]:
        print("Dry-run only -- re-run with --apply to write.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
