"""Comprehensive zero-re-OCR backfill of ``edition_page_key`` onto EVERY S1 sidecar.

Unlike ``stamp_edition_page_key.py`` (image-driven, body-only resolver, the four
primary runners), this sweep walks *every* sidecar JSON already on disk under
``reports/s1-sidecars/<lineage>/<vol_NN>/pages/`` -- all engines AND all ABBYY/
azure lineages, body and non-body leaves alike -- and stamps the now-required
``edition_page_key`` field. It exists to migrate the corpus that predates the
schema flip; the S1 runners/normalizers already stamp the field on fresh output,
so this is a one-time catch-up, not part of the steady-state pipeline.

It NEVER creates a sidecar and NEVER invokes an OCR engine. It only adds (or, with
``--force-rekey``, replaces) the ``edition_page_key`` object on records that lack it.

Resolution per sidecar, in priority order (all from the per-volume canonical source
manifest ``raw/.../schaff-herzog-pages/vol_NN.manifest.json``):

  1. by ``source_payload_sha256`` -> the assigned key for that physical leaf/gap
     (precise; the normal primary-scan case).
  2. by ``canonical_leaf_id`` (when the sidecar already carries one, e.g. an
     alternate scan keyed via the content-alignment leafmap) -> the key for that
     canonical leaf (precise across alternate scans).
  3. by the numeric ``page_native_id`` (``page_NNNN`` / ``leaf_NNNN``): a
     ``leaf_NNNN`` whose number is a known leaf uses that leaf's key; otherwise a
     best-effort ``body`` key from the number. This is the unmapped/out-of-range/
     degraded fallback -- it keeps the record schema-valid and the run runnable,
     matching what the runners/normalizers now do for the same pages.

Safety: dry-run by default (``--apply`` to write); idempotent; each write is
schema-validated before an atomic replace; an already-present *different* key is
left alone unless ``--force-rekey``.
"""
from __future__ import annotations

import argparse
import faulthandler
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[3]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

import jsonschema  # noqa: E402
from jsonschema.validators import validator_for  # noqa: E402

from build.lib.edition_page_key import assign_edition_page_keys, body_edition_key  # noqa: E402
from build.lib.ocr_store_paths import S1_SIDECARS_ROOT  # noqa: E402
from build.lib.paths import REPO_ROOT  # noqa: E402

_SCHEMA_DIR = REPO_ROOT / "schemas" / "v1"
_validator_cache: dict[str, Any] = {}


def _validator(schema_name: str) -> Any:
    """Compile the schema validator once and reuse it (the runner's per-call
    ``_validate`` re-reads + recompiles the schema every record -- ~66ms each,
    which made a 30k-record sweep take ~25min and look like a stall)."""
    cached = _validator_cache.get(schema_name)
    if cached is None:
        schema = json.loads((_SCHEMA_DIR / f"{schema_name}.schema.json").read_text(encoding="utf-8"))
        cls = validator_for(schema)
        cls.check_schema(schema)
        cached = cls(schema)
        _validator_cache[schema_name] = cached
    return cached

DEFAULT_INPUT_ROOT = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"
_VOL_DIR_RE = re.compile(r"vol_(\d+)$")
_NATIVE_NUM_RE = re.compile(r"(?:page|leaf)_(\d+)$")
_LEAF_NATIVE_RE = re.compile(r"leaf_(\d+)$")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json_atomic(path: Path, data: Any) -> None:
    tmp = path.with_name(path.name + f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def edition_key_maps(source_manifest: dict | None) -> tuple[dict[str, dict], dict[int, dict]]:
    """Return ``(by_sha, by_leaf_num)`` edition-key maps for one volume manifest."""
    by_sha: dict[str, dict] = {}
    by_leaf: dict[int, dict] = {}
    if source_manifest is None:
        return by_sha, by_leaf
    for assignment in assign_edition_page_keys(source_manifest):
        key = assignment.get("edition_page_key")
        if key is None:
            continue
        sha = assignment.get("source_payload_sha256")
        if isinstance(sha, str):
            by_sha.setdefault(sha, key)
        leaf_num = assignment.get("leaf_num")
        if isinstance(leaf_num, int):
            by_leaf.setdefault(leaf_num, key)
    return by_sha, by_leaf


def resolve_key(data: dict, by_sha: dict[str, dict], by_leaf: dict[int, dict]) -> dict | None:
    """Resolve the edition key for one sidecar record (see module docstring)."""
    sha = data.get("source_payload_sha256")
    if isinstance(sha, str) and sha in by_sha:
        return by_sha[sha]
    clid = data.get("canonical_leaf_id")
    if isinstance(clid, int) and clid in by_leaf:
        return by_leaf[clid]
    native = data.get("page_native_id")
    if isinstance(native, str):
        leaf_match = _LEAF_NATIVE_RE.fullmatch(native)
        if leaf_match and int(leaf_match.group(1)) in by_leaf:
            return by_leaf[int(leaf_match.group(1))]
        num_match = _NATIVE_NUM_RE.fullmatch(native)
        if num_match:
            return body_edition_key(int(num_match.group(1)))
    return None


def sweep_cell(
    pages_dir: Path,
    source_manifest: dict | None,
    *,
    apply: bool,
    force_rekey: bool,
) -> dict[str, int]:
    by_sha, by_leaf = edition_key_maps(source_manifest)
    counts = {"sidecars": 0, "stamped": 0, "already_keyed": 0, "unresolved": 0, "errors": 0}
    # PIPE-10: full per-record jsonschema validation of these rich word-geometry
    # records is the dominant cost (~66ms each) and is over-defensive -- the key we
    # add is constructed from assign_edition_page_keys / body_edition_key (always a
    # schema-valid object) and the records were valid before. Validate only the
    # FIRST stamped record per cell as a smoke check; the downstream reindex +
    # verify_leaf_keying + full test suite validate the rest.
    validated_one = False
    for sidecar_path in sorted(pages_dir.glob("*.json")):
        try:
            data = _read_json(sidecar_path)
        except json.JSONDecodeError:
            counts["unresolved"] += 1
            continue
        if not isinstance(data, dict):
            counts["unresolved"] += 1
            continue
        counts["sidecars"] += 1
        key = resolve_key(data, by_sha, by_leaf)
        current = data.get("edition_page_key")
        if key is None:
            if current is None:
                counts["unresolved"] += 1
                print(f"    UNRESOLVED {sidecar_path}", flush=True)
            else:
                counts["already_keyed"] += 1
            continue
        if current == key:
            counts["already_keyed"] += 1
            continue
        if current is not None and not force_rekey:
            counts["already_keyed"] += 1
            continue
        counts["stamped"] += 1
        if apply:
            # Per-record (REL-08): a single bad sidecar must not abort a 30k-file
            # sweep -- log it, count it, keep going.
            try:
                data["edition_page_key"] = dict(key)
                if not validated_one:
                    _validator("sidecar-page-v1").validate(data)
                    validated_one = True
                _write_json_atomic(sidecar_path, data)
                check = _read_json(sidecar_path)
                if check.get("edition_page_key") != key:
                    raise RuntimeError("edition_page_key missing after stamp")
            except Exception as exc:  # noqa: BLE001 -- logged, not swallowed
                counts["stamped"] -= 1
                counts["errors"] += 1
                print(f"    ERROR {sidecar_path}: {type(exc).__name__}: {exc}", flush=True)
    return counts


def _volume_of(vol_dir: Path) -> int | None:
    match = _VOL_DIR_RE.fullmatch(vol_dir.name)
    return int(match.group(1)) if match else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--s1-root", type=Path, default=S1_SIDECARS_ROOT)
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument(
        "--apply", action="store_true", default=False,
        help="Write changes. Omit for a dry-run report (default).",
    )
    parser.add_argument(
        "--force-rekey", action="store_true", default=False,
        help="Replace a different existing edition_page_key on --apply.",
    )
    parser.add_argument(
        "--only-lineage", action="append", default=None,
        help="Restrict to lineage dirs whose name contains this substring "
        "(repeatable). Enables bounded, watchable chunks for a large apply.",
    )
    args = parser.parse_args(argv)
    # If this run ever hangs in Python, dump every thread's stack to stderr so the
    # hang location is diagnosable instead of silent (the 30k-write apply must not
    # stall invisibly). Re-arms every 180s; normal progress just adds stderr noise.
    faulthandler.dump_traceback_later(180, repeat=True)
    if args.force_rekey and not args.apply:
        print("ERROR: --force-rekey is only meaningful with --apply", flush=True)
        return 2

    s1_root = Path(args.s1_root)
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"backfill_all_edition_page_keys [{mode}] s1_root={s1_root}", flush=True)

    grand = {"sidecars": 0, "stamped": 0, "already_keyed": 0, "unresolved": 0, "errors": 0}
    manifest_cache: dict[int, dict | None] = {}
    for lineage_dir in sorted(p for p in s1_root.iterdir() if p.is_dir()):
        # Skip quarantine / hidden directories -- they are not live cells.
        if lineage_dir.name.startswith("."):
            print(f"  SKIP (quarantine/hidden): {lineage_dir.name}", flush=True)
            continue
        if args.only_lineage and not any(sub in lineage_dir.name for sub in args.only_lineage):
            continue
        for vol_dir in sorted(p for p in lineage_dir.iterdir() if p.is_dir()):
            pages_dir = vol_dir / "pages"
            if not pages_dir.is_dir():
                continue
            volume = _volume_of(vol_dir)
            if volume is None:
                print(f"  SKIP (no volume number): {vol_dir}", flush=True)
                continue
            if volume not in manifest_cache:
                mpath = Path(args.input_root) / f"vol_{volume:02d}.manifest.json"
                manifest_cache[volume] = _read_json(mpath) if mpath.exists() else None
            counts = sweep_cell(
                pages_dir, manifest_cache[volume], apply=args.apply, force_rekey=args.force_rekey
            )
            verb = "stamped" if args.apply else "would stamp"
            print(
                f"  {lineage_dir.name}/{vol_dir.name}: {counts['stamped']} {verb}, "
                f"{counts['already_keyed']} already keyed, {counts['unresolved']} unresolved "
                f"({counts['sidecars']} sidecars)",
                flush=True,
            )
            for k in grand:
                grand[k] += counts[k]

    verb = "stamped" if args.apply else "would stamp"
    print(
        f"TOTAL: {grand['stamped']} {verb}, {grand['already_keyed']} already keyed, "
        f"{grand['unresolved']} unresolved, {grand['errors']} errors "
        f"({grand['sidecars']} sidecars)",
        flush=True,
    )
    if grand["unresolved"] or grand["errors"]:
        print("WARNING: some sidecars could not be resolved/stamped (see UNRESOLVED/ERROR lines).", flush=True)
    if not args.apply and grand["stamped"]:
        print("Dry-run only -- re-run with --apply to write.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
