"""One-shot retrofit: add provenance + fetched_at to vol_01 manifest pages 3, 6, 7, 9.

These pages were fetched from NewSchaffHerzogEncyclopediaOfReligious (alternate IA item)
in the same batch as pages 1, 2, 4, 5, 8 but the retrofit was incomplete. This script
adds the missing fields using the same provenance template as the already-retrofitted pages
and derives fetched_at from the on-disk file mtime.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages" / "vol_01.manifest.json"
SCHEMA_PATH = REPO_ROOT / "schemas" / "v1" / "source_manifest.schema.json"

PROVENANCE_TEMPLATE = {
    "source_item_id": "NewSchaffHerzogEncyclopediaOfReligious",
    "derivation": "direct",
    "crop_box": None,
    "replacement_reason": "missing from primary scan; fetched from alternate Internet Archive item",
    "validation_status": "bibliographic_matched",
    "dimension_variance": False,
}


def _file_mtime_utc(path: Path) -> str:
    mtime = path.stat().st_mtime
    return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()


def retrofit(manifest_path: Path, repo_root: Path) -> int:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    patched = 0

    for page in manifest["pages"]:
        if "ia_item_id" in page and "provenance" not in page:
            local_path = repo_root / page["local_path"]
            if not local_path.exists():
                print(f"  SKIP page {page['page_num']}: {local_path} not found")
                continue

            ia_leaf = int(page["ia_leaf_id"])
            page["provenance"] = {**PROVENANCE_TEMPLATE, "source_leaf": ia_leaf}
            page["fetched_at"] = _file_mtime_utc(local_path)
            patched += 1
            print(f"  patched page {page['page_num']}: source_leaf={ia_leaf} fetched_at={page['fetched_at']}")

    if patched == 0:
        print("Nothing to patch.")
        return 0

    tmp = manifest_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, manifest_path)
    print(f"Wrote {manifest_path} ({patched} pages patched)")

    # Validate against schema
    try:
        import jsonschema
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        jsonschema.validate(manifest, schema)
        print("Schema validation: OK")
    except ImportError:
        print("jsonschema not available; skipping schema check")
    except jsonschema.ValidationError as exc:
        print(f"Schema validation FAILED: {exc.message}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(retrofit(MANIFEST_PATH, REPO_ROOT))
