"""Regenerate the two reviewed COLLAB-003 data notices with writer provenance.

This replays the original checkpoint bytes in a new external directory. It does
not rewrite the already installed notices or their historical rights receipts.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
from uuid import uuid4

from build.lib import writer_manifest

CHECKPOINT = "55bb917ba7d4b5f991900e189d87e33384cc8160"
PACKET = Path("plans/2026-08-31-library-pipeline-redesign/artifacts/public-docs-cleanup-20261021")
REVIEW_PINS = {
    "NOTICE_INSTALL.json": "5c2e8901457d6221004496f20f2cf6d4a5dd74a740a59aae4f44352c630229bc",
    "PATCH_MANIFEST.json": "c42a81a24758acd5ad87237166ce9b8507ee66dc658942e93c331b8db06b9d5e",
}
EDITS = {
    "data/doctrinal-documents/council-of-orange/README.md": (
        b"](www.onthewing.org/user/Creed_Council%20of%20Orange%20-%20Pelagianism.pdf)",
        b"](https://www.onthewing.org/user/Creed_Council%20of%20Orange%20-%20Pelagianism.pdf)",
    ),
    "data/structured-text/edwards-freedom-of-the-will/README.md": (
        b"[banner reference](/ccel/edwards/will/files/je_banner.jpg)",
        b"banner reference `/ccel/edwards/will/files/je_banner.jpg`",
    ),
}


def _git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", "--no-optional-locks", *args], cwd=root,
                          check=True, capture_output=True).stdout


def replay(root: Path, replay_root: Path) -> dict:
    root = Path(root).resolve(strict=True)
    replay_root = Path(replay_root).resolve()
    if replay_root.exists() or replay_root.is_relative_to(root) or root.is_relative_to(replay_root):
        raise ValueError("replay requires a new external directory")
    if _git(root, "rev-parse", "HEAD").decode().strip() != CHECKPOINT:
        raise ValueError("notice writer requires the reviewed checkpoint HEAD")
    reviews = {}
    for name, digest in REVIEW_PINS.items():
        raw = (root / PACKET / name).read_bytes()
        if sha256(raw).hexdigest() != digest:
            raise ValueError(f"reviewed notice evidence changed: {name}")
        reviews[name] = {row["path"]: row for row in json.loads(raw)["files"]}
    originals, outputs = {}, {}
    for name, (old, new) in EDITS.items():
        before = _git(root, "show", f"{CHECKPOINT}:{name}")
        installed, patch = (reviews[key][name] for key in REVIEW_PINS)
        if (sha256(before).hexdigest() != installed["before_sha256"]
                or installed["before_sha256"] != patch["before_sha256"] or before.count(old) != 1):
            raise ValueError(f"reviewed notice preimage differs: {name}")
        after = before.replace(old, new)
        if (sha256(after).hexdigest() != installed["after_sha256"]
                or installed["after_sha256"] != patch["sha256"]
                or after != (root / name).read_bytes()
                or after != (root / PACKET / "review-inputs" / name).read_bytes()
                or after.count(new) != 1 or after.replace(new, old) != before):
            raise ValueError(f"reviewed notice output differs: {name}")
        originals[name], outputs[name] = before, after
    run_id = "collab003-notice-links-" + datetime.now(timezone.utc).strftime("%Y-%m-%d") + "-" + uuid4().hex[:8]
    manifest = root / "review/writer-manifests" / (run_id + ".json")
    replay_root.mkdir(parents=True, exist_ok=False)
    try:
        for name, body in originals.items():
            path = replay_root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
        with writer_manifest.run(
            writer_identity="notice_link_amendment",
            writer_version="build/tools/replay_notice_link_amendments.py@v1.0.0",
            data_paths=[replay_root / name for name in EDITS],
            allowed_field_paths=[""],  # The root value is the complete Markdown document.
            repo_root=replay_root, manifests_dir=manifest.parent, run_id=run_id,
        ) as run:
            for name, body in outputs.items():
                path = replay_root / name
                path.write_bytes(body)
                if path.read_bytes() != body or (root / name).read_bytes() != body:
                    raise ValueError(f"notice changed during replay: {name}")
                changed = int(originals[name] != body)
                run.record_delta(path, entries_changed=changed, fields_changed=changed)
    finally:
        shutil.rmtree(replay_root)
    return {"status": "pass", "manifest": manifest.relative_to(root).as_posix(),
            "manifest_sha256": sha256(manifest.read_bytes()).hexdigest(),
            "checkpoint": CHECKPOINT, "reviewed_evidence_sha256": REVIEW_PINS,
            "canonical_notice_bytes_unchanged": True, "external_replay_removed": not replay_root.exists()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--replay-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(replay(args.root, args.replay_root), ensure_ascii=True))


if __name__ == "__main__":
    main()
