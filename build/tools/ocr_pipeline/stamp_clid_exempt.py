"""R-final (R5) migration -- stamp ``clid_exempt: true`` onto every on-disk page
record of the four leaf-keyed schemas that legitimately carries no
``canonical_leaf_id``, so the optional->required flip lands on conformant data.

Safety: the R6b verifier (verify_leaf_keying.py) OVERALL PASS proves every page
record lacking an int ``canonical_leaf_id`` is a legitimately-exempt non-body /
recovered-gap / alternate-scan-unmappable page -- so "no int clid => mark
clid_exempt" cannot mis-mark a body page. Quarantine subtrees (any path part
starting with ``.``) are skipped. Writes are atomic (write_json_atomic) and the
pass is idempotent (a record already carrying clid or clid_exempt is untouched).

Dry-run by default; pass --apply to write. Disk is ground truth (VER-01).

    py -3 build/tools/ocr_pipeline/stamp_clid_exempt.py            # dry-run
    py -3 build/tools/ocr_pipeline/stamp_clid_exempt.py --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

from build.lib.atomic_io import write_json_atomic
from build.lib.ocr_store_paths import (
    s1_sidecars_root,
    s2_renderings_root,
    wct_root,
)
from build.lib.paths import REPO_ROOT

_SCHEMA_DIR = REPO_ROOT / "schemas" / "v1"
_SCHEMA_CACHE: dict[str, dict] = {}


def _schema(name: str) -> dict:
    if name not in _SCHEMA_CACHE:
        _SCHEMA_CACHE[name] = json.loads(
            (_SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8")
        )
    return _SCHEMA_CACHE[name]


def _has_int_clid(record: dict) -> bool:
    v = record.get("canonical_leaf_id")
    return isinstance(v, int) and not isinstance(v, bool)


def stamp_page_record(record: dict) -> bool:
    """Mark one page record exempt iff it carries no int canonical_leaf_id and is
    not already marked. Returns True iff the record was changed (idempotent)."""
    if _has_int_clid(record):
        return False
    if record.get("clid_exempt") is True:
        return False
    record["clid_exempt"] = True
    return True


def _live(path: Path, repo_root: Path) -> bool:
    return not any(part.startswith(".") for part in path.relative_to(repo_root).parts)


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _process_sidecar_page(path: Path) -> bool:
    """sidecar-page-v1: one record per file. Returns True iff written."""
    doc = _load(path)
    if not isinstance(doc, dict):
        return False
    if stamp_page_record(doc):
        write_json_atomic(path, doc, _schema("sidecar-page-v1"))
        return True
    return False


def _process_manifest(path: Path) -> int:
    """sidecar-manifest-v1: stamp each page_ref. Returns count of refs changed."""
    doc = _load(path)
    if not isinstance(doc, dict):
        return 0
    changed = sum(1 for ref in doc.get("pages", []) if isinstance(ref, dict) and stamp_page_record(ref))
    if changed:
        write_json_atomic(path, doc, _schema("sidecar-manifest-v1"))
    return changed


def _process_rendering(path: Path) -> int:
    """rendering-v1 per-page split file: stamp each rendered_page in pages[]."""
    doc = _load(path)
    if not isinstance(doc, dict):
        return 0
    changed = sum(1 for pg in doc.get("pages", []) if isinstance(pg, dict) and stamp_page_record(pg))
    if changed:
        write_json_atomic(path, doc, _schema("rendering-v1"))
    return changed


def _process_wct(path: Path) -> bool:
    """word-confusion-table-v1: one record per page_*.json file."""
    doc = _load(path)
    if not isinstance(doc, dict):
        return False
    if stamp_page_record(doc):
        write_json_atomic(path, doc, _schema("word-confusion-table-v1"))
        return True
    return False


def migrate(repo_root: Path = REPO_ROOT, *, apply: bool = False) -> dict[str, int]:
    """Stamp clid_exempt across all four stores. In dry-run, counts the records
    that WOULD change without writing (stamp on a copy)."""
    repo_root = Path(repo_root)
    s1 = s1_sidecars_root(repo_root)
    s2 = s2_renderings_root(repo_root)
    wct = wct_root(repo_root)
    totals = {"sidecar_pages": 0, "manifest_refs": 0, "rendered_pages": 0, "wct_pages": 0,
              "files_written": 0}

    def _count_exempt_needed(doc_records: list[dict]) -> int:
        # dry-run accounting: a record needs stamping iff no int clid and not already exempt
        return sum(1 for r in doc_records
                   if isinstance(r, dict) and not _has_int_clid(r) and r.get("clid_exempt") is not True)

    # 1. sidecar-page-v1
    for path in s1.glob("*/vol_*/pages/*.json"):
        if not _live(path, repo_root):
            continue
        doc = _load(path)
        if not isinstance(doc, dict):
            continue
        if not _has_int_clid(doc) and doc.get("clid_exempt") is not True:
            totals["sidecar_pages"] += 1
            if apply and _process_sidecar_page(path):
                totals["files_written"] += 1

    # 2. sidecar-manifest-v1 page_refs
    for path in s1.glob("*/vol_*/manifest.json"):
        if not _live(path, repo_root):
            continue
        doc = _load(path)
        if not isinstance(doc, dict):
            continue
        n = _count_exempt_needed(doc.get("pages", []))
        if n:
            totals["manifest_refs"] += n
            if apply:
                _process_manifest(path)
                totals["files_written"] += 1

    # 3. rendering-v1 per-page split
    for path in s2.glob("vol_*/*/pages/*.json"):
        if not _live(path, repo_root):
            continue
        doc = _load(path)
        if not isinstance(doc, dict) or not isinstance(doc.get("pages"), list):
            continue
        n = _count_exempt_needed(doc.get("pages", []))
        if n:
            totals["rendered_pages"] += n
            if apply:
                _process_rendering(path)
                totals["files_written"] += 1

    # 4. word-confusion-table-v1
    for path in wct.glob("vol_*/page_*.json"):
        if not _live(path, repo_root):
            continue
        doc = _load(path)
        if not isinstance(doc, dict):
            continue
        if not _has_int_clid(doc) and doc.get("clid_exempt") is not True:
            totals["wct_pages"] += 1
            if apply and _process_wct(path):
                totals["files_written"] += 1

    return totals


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    ap.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    args = ap.parse_args(argv)
    totals = migrate(args.repo_root, apply=args.apply)
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"=== stamp_clid_exempt ({mode}) ===")
    print(f"  sidecar-page-v1 records to mark exempt : {totals['sidecar_pages']}")
    print(f"  sidecar-manifest page_refs to mark     : {totals['manifest_refs']}")
    print(f"  rendering-v1 rendered_pages to mark    : {totals['rendered_pages']}")
    print(f"  word-confusion-table-v1 pages to mark  : {totals['wct_pages']}")
    print(f"  files written                          : {totals['files_written']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
