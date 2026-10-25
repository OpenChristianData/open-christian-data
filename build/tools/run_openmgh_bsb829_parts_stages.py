"""Stage the exact 24 durable bsb829 native-part packages outside the repository."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from hashlib import sha256
import json
from pathlib import Path

from build.tools.preflight_openmgh_bsb829_parts import preflight
from build.tools.stage_openmgh_bsb829_parts_acceptance import prepare
from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[2]
PACKAGES = Path(r"D:\Library\Open Christian Data\candidate-reviews\openmgh-bsb829-parts-packages-20260926\receipt.json")
STAGES = Path(r"D:\Library\Open Christian Data\candidate-reviews\b829-parts-stages-20260926")
RECEIPTS = Path("plans/2026-09-22-source-preflight/openmgh-bsb829-parts-stages-20260926")


def _one(index: int, work_id: str) -> tuple[int, dict]:
    stage = STAGES / f"w{index:02d}"
    receipt = ROOT / RECEIPTS / f"{work_id}-stage.json"
    if not Path(_io_path(receipt)).exists():
        result = prepare(ROOT, PACKAGES, work_id, stage, receipt)
    else:
        result = json.loads(Path(_io_path(receipt)).read_bytes())
    checked = preflight(receipt)
    if checked["work_id"] != work_id or checked["projection_rows"] != 1:
        raise ValueError(f"stage preflight differs: {work_id}")
    return index, {"work_id": work_id, "receipt_path": (RECEIPTS / receipt.name).as_posix(),
                   "receipt_sha256": sha256(Path(_io_path(receipt)).read_bytes()).hexdigest(),
                   "accepted_master_sha256": result["accepted_master_sha256"],
                   "preflight": checked["status"]}


def run() -> dict:
    packages = json.loads(Path(_io_path(PACKAGES)).read_bytes())
    if packages["contract"] != "ocd-openmgh-bsb829-parts-packages-v1" or len(packages["works"]) != 24:
        raise ValueError("durable 24-package receipt changed")
    STAGES.mkdir(parents=True, exist_ok=True)
    (ROOT / RECEIPTS).mkdir(parents=True, exist_ok=True)
    numbered = {}
    with ProcessPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(_one, index, item["work_id"]): index
                   for index, item in enumerate(packages["works"], start=1)}
        for future in as_completed(futures):
            index, row = future.result()
            numbered[index] = row
            print(f"{index}/24 {row['work_id']}: {row['preflight']}", flush=True)
    rows = [numbered[index] for index in range(1, 25)]
    return {"contract": "ocd-openmgh-bsb829-parts-stages-v1", "status": "staged-only",
            "package_receipt": PACKAGES.as_posix(),
            "package_receipt_sha256": sha256(Path(_io_path(PACKAGES)).read_bytes()).hexdigest(),
            "stages": rows, "canonical_install": "not-performed"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, default=ROOT / RECEIPTS / "receipt.json")
    args = parser.parse_args()
    result = run()
    output = args.receipt.absolute()
    if output.exists() and output.read_bytes() != (json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n").encode():
        raise ValueError("existing aggregate receipt differs")
    output.write_text(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps({"stages": len(result["stages"]), "receipt": str(output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
