"""Generate writer manifests for the contributors patch (BSB + Schaff-Herzog).

Produces two manifests in review/writer-manifests/:
  meta-patch-2026-06-16-bsb-contributors.json
  meta-patch-2026-06-16-schaff-contributors.json

Run after patch_contributors.py has been applied.
"""

import hashlib
import json
import pathlib
import subprocess
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
MANIFESTS = ROOT / "review" / "writer-manifests"

SCHEMA_VERSION = "1.0.0"
WRITER = "patch-script"
STARTED_AT = "2026-06-16T12:00:00.000000+00:00"


def sha256_git(rel: str) -> str:
    """SHA256 of the file as it was in HEAD (before this patch)."""
    try:
        result = subprocess.run(
            ["git", "show", f"HEAD:{rel}"],
            capture_output=True, check=True, cwd=ROOT
        )
        return hashlib.sha256(result.stdout).hexdigest()
    except subprocess.CalledProcessError:
        return None  # new file, no prior state


def sha256_disk(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def make_manifest(run_id: str, writer_identity: str, rels: list[str]) -> dict:
    checksums = {}
    for rel in rels:
        before = sha256_git(rel)
        after = sha256_disk(rel)
        checksums[rel] = {
            "before_sha256": before,
            "after_sha256": after
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "writer": WRITER,
        "writer_version": "build/tools/patch_contributors.py@v1.0.0",
        "writer_identity": writer_identity,
        "run_id": run_id,
        "started_at": STARTED_AT,
        "data_paths": rels,
        "checksums": checksums,
    }


def main() -> None:
    bsb_dir = DATA / "bible-text" / "bsb"
    schaff_dir = DATA / "reference" / "schaff" / "encyclopedia" / "1908-1914" / "original"

    bsb_rels = sorted(
        str(p.relative_to(ROOT)).replace("\\", "/")
        for p in bsb_dir.glob("*.json")
    )
    schaff_rels = sorted(
        str(p.relative_to(ROOT)).replace("\\", "/")
        for p in schaff_dir.glob("vol_*.json")
    )

    bsb_manifest = make_manifest(
        "meta-patch-2026-06-16-bsb-contributors",
        "meta_patch_bsb_contributors",
        bsb_rels,
    )
    schaff_manifest = make_manifest(
        "meta-patch-2026-06-16-schaff-contributors",
        "meta_patch_schaff_contributors",
        schaff_rels,
    )

    MANIFESTS.mkdir(parents=True, exist_ok=True)

    for name, manifest in [
        ("meta-patch-2026-06-16-bsb-contributors.json", bsb_manifest),
        ("meta-patch-2026-06-16-schaff-contributors.json", schaff_manifest),
    ]:
        out = MANIFESTS / name
        tmp = out.with_suffix(".tmp")
        tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        import os; os.replace(tmp, out)
        print(f"Wrote {out.name} ({len(manifest['data_paths'])} files)")


if __name__ == "__main__":
    main()
