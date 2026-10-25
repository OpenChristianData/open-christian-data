"""Reproduce the eight pinned bsb00000828 candidates in fresh processes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[2]
BATCH = ROOT / "plans/2026-09-22-source-preflight/openmgh-bsb828-held-candidates-20260926.json"
REPORT = ROOT / "plans/2026-09-22-source-preflight/openmgh-bsb828-held-reproduction-20260926.json"
SCRATCH = Path("C:/Scratch")


def _sha(path: Path) -> str:
    return hashlib.sha256(_io_path(path).read_bytes()).hexdigest()


def run() -> dict:
    if _io_path(REPORT).exists():
        raise ValueError("reproduction report already exists")
    batch = json.loads(BATCH.read_bytes())
    if batch.get("identity_count") != 8 or batch.get("validated_candidate_count") != 8:
        raise ValueError("held candidate batch is incomplete")
    if not SCRATCH.is_dir():
        raise ValueError("C:/Scratch is unavailable")
    scratch = Path(tempfile.mkdtemp(prefix="b82r-", dir=SCRATCH)).resolve(strict=True)
    try:
        rows = []
        for ordinal, entry in enumerate(batch["works"], 1):
            work_id = entry["work_id"]
            output = scratch / f"w{ordinal:02d}"
            result = subprocess.run(
                [sys.executable, "-m", "build.tools.reconstruct_candidate",
                 "--manifest", entry["manifest_path"], "--destination", str(output),
                 "--repository-root", str(ROOT)], cwd=ROOT, check=True,
                capture_output=True, text=True,
            )
            observed = {p.relative_to(_io_path(output)).as_posix(): _sha(p)
                        for p in _io_path(output).rglob("*") if p.is_file()}
            if observed != entry["output_file_sha256"]:
                raise ValueError(f"fresh-process candidate differs: {work_id}")
            summary = json.loads(result.stdout)
            rows.append({"work_id": work_id, "status": "byte-identical",
                         "file_count": len(observed), "candidate_sha256": entry["candidate_sha256"],
                         "summary": summary})
        report = {"contract": "ocd-openmgh-bsb828-held-reproduction-v1",
                  "status": "pass", "batch_path": BATCH.relative_to(ROOT).as_posix(),
                  "batch_sha256": _sha(BATCH), "process_count": len(rows), "files_compared": 7 * len(rows),
                  "works": rows}
        _io_path(REPORT).write_bytes((json.dumps(report, ensure_ascii=False, sort_keys=True,
                                                separators=(",", ":")) + "\n").encode())
        return report
    finally:
        if not scratch.is_relative_to(SCRATCH.resolve(strict=True)):
            raise RuntimeError("scratch cleanup target escaped C:/Scratch")
        shutil.rmtree(_io_path(scratch))


def main() -> int:
    result = run()
    print(json.dumps({"status": result["status"], "process_count": result["process_count"],
                      "files_compared": result["files_compared"],
                      "report": REPORT.relative_to(ROOT).as_posix(), "report_sha256": _sha(REPORT)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
