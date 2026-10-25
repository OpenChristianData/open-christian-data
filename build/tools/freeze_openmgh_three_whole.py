"""Freeze three exact single-work openMGH stages into one review index."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from build.tools import prepare_openmgh_three_whole as source
from build.tools import stage_openmgh_three_whole_acceptance as staging
from ocd_kernel.tei.install_accepted import _files, _io_path


ROOT = Path(__file__).resolve().parents[2]
HOME = Path("D:/Library/Open Christian Data/candidate-reviews/three-whole-stage-20260928-v1")
DIRECT = Path("D:/Library/Open Christian Data/candidate-reviews/openmgh-three-whole-direct-20260928-v1/receipt.json")
DIRECT_SHA = "0c7f16b03a222b1dcaa6ac430a67074e331dd68c6b8d5c47ed6721b1f457fd71"
FREEZE = ROOT / "plans/2026-09-22-source-preflight/openmgh-three-whole-freeze-20260928-v1.json"


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def prepare() -> dict:
    if _io_path(FREEZE).exists() or _sha(DIRECT) != DIRECT_SHA:
        raise ValueError("existing freeze or changed direct receipt")
    direct = json.loads(_io_path(DIRECT).read_bytes())
    selected = set(source.WORKS)
    if (direct.get("contract") != "ocd-openmgh-three-whole-direct-candidates-v1"
            or direct.get("status") != "nonaccepted"
            or {item["work_id"] for item in direct.get("works", [])} != selected
            or len(direct.get("works", [])) != len(selected)):
        raise ValueError("work direct partition differs")
    pins = []
    for work_id in sorted(selected):
        stage = HOME / work_id
        receipt_path = HOME / f"{work_id}-receipt.json"
        record = json.loads(_io_path(receipt_path).read_bytes())
        entry = next(item for item in direct["works"] if item["work_id"] == work_id)
        if (record.get("contract") != staging.CONTRACT or record.get("status") != "staged-only"
                or record.get("installation") != "not-performed" or record.get("work_id") != work_id
                or record.get("source_path") != entry["source_path"]
                or record.get("source_sha256") != entry["source_sha256"]
                or record.get("direct_receipt_sha256") != DIRECT_SHA
                or record.get("stage_root") != stage.as_posix()
                or record.get("category") != "prose" or record.get("language") != "la"
                or record.get("projection_rows") != 1):
            raise ValueError(f"stage scope differs: {work_id}")
        pins.append({
            "work_id": work_id, "stage_root": stage.as_posix(),
            "source_path": entry["source_path"], "source_sha256": entry["source_sha256"],
            "package_path": entry["package_path"], "package_sha256": entry["package_sha256"],
            "acquisition_receipt": entry["acquisition_receipt"],
            "acquisition_receipt_sha256": entry["acquisition_receipt_sha256"],
            "stage_receipt": receipt_path.as_posix(), "stage_receipt_sha256": _sha(receipt_path),
            "stage_files": _files(stage), "source_child_start": entry["independent_oracle"]["source_child_start"],
            "source_child_end": entry["independent_oracle"]["source_child_end"],
            "internal_page_break": entry["independent_oracle"]["internal_page_break"],
            "candidate_sha256": entry["candidate_sha256"],
            "accepted_master_sha256": record["accepted_master_sha256"],
            "acceptance_sha256": record["acceptance_sha256"],
        })
    frozen = {
        "contract": "ocd-openmgh-three-whole-freeze-v1",
        "status": "review-ready-staged-only", "canonical_root": ROOT.as_posix(),
        "canonical_install": "not-performed", "direct_receipt": DIRECT.as_posix(),
        "direct_receipt_sha256": DIRECT_SHA, "works": pins,
    }
    _io_path(FREEZE).write_bytes(source._json(frozen))
    return {"freeze": FREEZE.as_posix(), "freeze_sha256": _sha(FREEZE),
            "works": {pin["work_id"]: pin["stage_receipt_sha256"] for pin in pins}}


if __name__ == "__main__":
    print(json.dumps(prepare(), sort_keys=True))
