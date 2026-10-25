"""Freeze two exact bsb830 residual prose-part stages into one immutable review index."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from build.tools import prepare_openmgh_bsb830_residual_parts as source
from build.tools import stage_openmgh_bsb830_residual_parts as staging
from ocd_kernel.tei.install_accepted import _files, _io_path


ROOT = Path(__file__).resolve().parents[2]
FREEZE = ROOT / "plans/2026-09-22-source-preflight/openmgh-bsb830-residual-parts-freeze-20260928-v1.json"
CONTRACT = "ocd-openmgh-bsb830-residual-parts-freeze-v1"


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def prepare() -> dict:
    if _io_path(FREEZE).exists():
        raise ValueError("bsb830 two-work freeze already exists")
    direct_path = staging.DIRECT / "receipt.json"
    if _sha(direct_path) != staging.DIRECT_SHA:
        raise ValueError("bsb830 direct receipt changed")
    direct = json.loads(_io_path(direct_path).read_bytes())
    if (direct.get("contract") != source.CONTRACT
            or {item["work_id"] for item in direct.get("selected_works", [])} != set(source.SELECTIONS)
            or direct.get("selected_part_count") != 2 or len(direct.get("other_parts", [])) != 9):
        raise ValueError("bsb830 direct two-work partition differs")
    pins = []
    for work_id in sorted(source.SELECTIONS):
        stage = (Path("D:/Library/Open Christian Data/candidate-reviews") /
                 "openmgh-bsb830-residual-parts-stage-20260928-v1" / work_id)
        receipt_path = stage / "stage-receipt.json"
        record = json.loads(_io_path(receipt_path).read_bytes())
        entry = next(item for item in direct["selected_works"] if item["work_id"] == work_id)
        if (record.get("contract") != staging.CONTRACT or record.get("status") != "staged-only"
                or record.get("installation") != "not-performed" or record.get("work_id") != work_id
                or record.get("source_sha256") != source.SOURCE_SHA
                or record.get("direct_receipt_sha256") != staging.DIRECT_SHA
                or record.get("source_part_c14n_sha256") != entry["oracle"]["source_part_c14n_sha256"]
                or record.get("source_work_div_index") != entry["source_work_div_index"]
                or record.get("source_part_indexes") != entry["source_part_indexes"]
                or record.get("category") != "prose" or record.get("language") != "la"
                or record.get("projection_rows") != 1):
            raise ValueError(f"bsb830 stage scope differs: {work_id}")
        pins.append({
            "work_id": work_id, "stage_root": stage.as_posix(),
            "stage_receipt_sha256": _sha(receipt_path),
            "stage_files": _files(stage),
            "source_work_div_index": entry["source_work_div_index"],
            "source_part_indexes": entry["source_part_indexes"],
            "source_part_c14n_sha256": entry["oracle"]["source_part_c14n_sha256"],
            "candidate_sha256": entry["candidate_sha256"],
            "accepted_master_sha256": record["accepted_master_sha256"],
            "acceptance_sha256": record["acceptance_sha256"],
        })
    frozen = {
        "contract": CONTRACT, "status": "review-ready-staged-only",
        "canonical_root": ROOT.as_posix(), "canonical_install": "not-performed",
        "source_path": source.SOURCE.as_posix(), "source_sha256": source.SOURCE_SHA,
        "package_path": source.PACKAGE.as_posix(), "package_sha256": source.PACKAGE_SHA,
        "direct_receipt": direct_path.as_posix(), "direct_receipt_sha256": staging.DIRECT_SHA,
        "selected_part_count": 2, "other_parts": direct["other_parts"], "works": pins,
    }
    _io_path(FREEZE).write_bytes(source._json(frozen))
    return {"freeze": FREEZE.as_posix(), "freeze_sha256": _sha(FREEZE),
            "works": {item["work_id"]: item["stage_receipt_sha256"] for item in pins}}


if __name__ == "__main__":
    print(json.dumps(prepare(), sort_keys=True))
