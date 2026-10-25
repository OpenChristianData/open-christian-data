"""Freeze the exact bsb754 Vita abbatum edition stage for review."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from build.tools import prepare_openmgh_bsb754_vita_abbatum as source
from build.tools import stage_openmgh_bsb754_vita_abbatum as staging
from ocd_kernel.tei.install_accepted import _files, _io_path


ROOT = Path(__file__).resolve().parents[2]
STAGE = Path("D:/Library/Open Christian Data/candidate-reviews/openmgh-bsb754-vita-abbatum-stage-20260928-v2")
RECEIPT = Path("D:/Library/Open Christian Data/candidate-reviews/openmgh-bsb754-vita-abbatum-stage-20260928-v2-receipt.json")
DIRECT = Path("D:/Library/Open Christian Data/candidate-reviews/openmgh-bsb754-vita-abbatum-direct-20260928-v1/receipt.json")
DIRECT_SHA = "80584e0907681fdbcc1c7c06b343caad948a5a7b3550129111a33c111cf7800a"
FREEZE = ROOT / "plans/2026-09-22-source-preflight/openmgh-bsb754-vita-abbatum-freeze-20260928-v1.json"
CONTRACT = "ocd-openmgh-bsb754-vita-abbatum-freeze-v1"


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def prepare() -> dict:
    if _io_path(FREEZE).exists() or _sha(DIRECT) != DIRECT_SHA:
        raise ValueError("existing freeze or changed direct receipt")
    direct = json.loads(_io_path(DIRECT).read_bytes())
    if (direct.get("contract") != "ocd-openmgh-bsb754-vita-abbatum-direct-v1"
            or direct.get("status") != "nonaccepted"
            or direct.get("work_id") != source.WORK_ID
            or direct.get("edition_id") != source.EDITION_ID):
        raise ValueError("direct work or edition scope differs")
    record = json.loads(_io_path(RECEIPT).read_bytes())
    if (record.get("contract") != staging.CONTRACT or record.get("status") != "staged-only"
            or record.get("installation") != "not-performed"
            or record.get("work_id") != source.WORK_ID
            or record.get("edition_id") != source.EDITION_ID
            or record.get("source_path") != source.SOURCE.as_posix()
            or record.get("source_sha256") != source.SOURCE_SHA256
            or record.get("other_source_path") != source.OTHER_SOURCE.as_posix()
            or record.get("other_source_sha256") != source.OTHER_SOURCE_SHA256
            or record.get("other_package_sha256") != source.OTHER_PACKAGE_SHA256
            or record.get("other_receipt_sha256") != source.OTHER_RECEIPT_SHA256
            or record.get("direct_receipt_sha256") != DIRECT_SHA
            or record.get("stage_root") != STAGE.as_posix()
            or record.get("category") != "prose" or record.get("language") != "la"
            or record.get("projection_rows") != 1):
        raise ValueError("bsb754 stage scope differs")
    frozen = {
        "contract": CONTRACT,
        "status": "review-ready-staged-only", "canonical_root": ROOT.as_posix(),
        "canonical_install": "not-performed", "direct_receipt": DIRECT.as_posix(),
        "direct_receipt_sha256": DIRECT_SHA,
        "work_id": source.WORK_ID, "edition_id": source.EDITION_ID,
        "other_edition_id": source.OTHER_EDITION_ID,
        "source_path": source.SOURCE.as_posix(), "source_sha256": source.SOURCE_SHA256,
        "package_path": source.PACKAGE.as_posix(), "package_sha256": source.PACKAGE_SHA256,
        "acquisition_receipt": source.RECEIPT.as_posix(),
        "acquisition_receipt_sha256": source.RECEIPT_SHA256,
        "other_source_path": source.OTHER_SOURCE.as_posix(),
        "other_source_sha256": source.OTHER_SOURCE_SHA256,
        "other_package_path": source.OTHER_PACKAGE.as_posix(),
        "other_package_sha256": source.OTHER_PACKAGE_SHA256,
        "other_receipt_path": source.OTHER_RECEIPT.as_posix(),
        "other_receipt_sha256": source.OTHER_RECEIPT_SHA256,
        "other_acquisition_path": direct["other_acquisition_path"],
        "other_acquisition_sha256": source.OTHER_ACQUISITION_SHA256,
        "stage_root": STAGE.as_posix(), "stage_receipt": RECEIPT.as_posix(),
        "stage_receipt_sha256": _sha(RECEIPT), "stage_files": _files(STAGE),
        "candidate_sha256": direct["candidate_sha256"],
        "selected_c14n_sha256": direct["independent_oracle"]["selected_c14n_sha256"],
        "internal_page_break": direct["independent_oracle"]["internal_page_break"],
        "before": record["before"], "after": record["after"],
        "accepted_master_sha256": record["accepted_master_sha256"],
        "acceptance_sha256": record["acceptance_sha256"],
    }
    _io_path(FREEZE).write_bytes(source._json(frozen))
    return {"freeze": FREEZE.as_posix(), "freeze_sha256": _sha(FREEZE),
            "stage_receipt_sha256": frozen["stage_receipt_sha256"]}


if __name__ == "__main__":
    print(json.dumps(prepare(), sort_keys=True))
