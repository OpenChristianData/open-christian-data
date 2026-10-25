"""Freeze two exact bsb720 Heribert hymn stages into a review index."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from build.tools import prepare_openmgh_bsb720_heribert_hymns as source
from build.tools import stage_openmgh_bsb720_heribert_hymns_acceptance as staging
from ocd_kernel.tei.install_accepted import _files, _io_path


ROOT = Path(__file__).resolve().parents[2]
HOME = Path("D:/Library/Open Christian Data/candidate-reviews/openmgh-bsb720-heribert-hymns-stage-20260928-v1")
DIRECT = Path("D:/Library/Open Christian Data/candidate-reviews/openmgh-bsb720-heribert-hymns-direct-20260928-v1/receipt.json")
DIRECT_SHA = "929fbe0bfc7dc1da6887257dbce05477fa5fc30014f471a03b43570753ffb8fe"
FREEZE = ROOT / "plans/2026-09-22-source-preflight/openmgh-bsb720-heribert-hymns-freeze-20260928-v1.json"


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def prepare() -> dict:
    if _io_path(FREEZE).exists() or _sha(DIRECT) != DIRECT_SHA:
        raise ValueError("existing freeze or changed direct receipt")
    direct = json.loads(_io_path(DIRECT).read_bytes())
    selected = {work_id for work_id, _ in source.WORKS}
    if (direct.get("contract") != "ocd-openmgh-bsb720-heribert-hymns-direct-candidates-v1"
            or direct.get("status") != "nonaccepted"
            or {item["work_id"] for item in direct.get("works", [])} != selected):
        raise ValueError("two-hymn direct partition differs")
    pins = []
    for work_id in sorted(selected):
        stage = HOME / work_id
        receipt_path = HOME / f"{work_id}-receipt.json"
        record = json.loads(_io_path(receipt_path).read_bytes())
        entry = next(item for item in direct["works"] if item["work_id"] == work_id)
        if (record.get("contract") != staging.CONTRACT or record.get("status") != "staged-only"
                or record.get("installation") != "not-performed" or record.get("work_id") != work_id
                or record.get("source_sha256") != source.SOURCE_SHA256
                or record.get("direct_receipt_sha256") != DIRECT_SHA
                or record.get("stage_root") != stage.as_posix()
                or record.get("category") != "poetry" or record.get("language") != "la"
                or record.get("projection_rows") != 1):
            raise ValueError(f"stage scope differs: {work_id}")
        pins.append({
            "work_id": work_id, "stage_root": stage.as_posix(),
            "stage_receipt": receipt_path.as_posix(), "stage_receipt_sha256": _sha(receipt_path),
            "stage_files": _files(stage), "source_child_start": entry["independent_oracle"]["source_child_start"],
            "source_child_end": entry["independent_oracle"]["source_child_end"],
            "internal_page_break": entry["independent_oracle"]["internal_page_break"],
            "candidate_sha256": entry["candidate_sha256"],
            "accepted_master_sha256": record["accepted_master_sha256"],
            "acceptance_sha256": record["acceptance_sha256"],
        })
    frozen = {
        "contract": "ocd-openmgh-bsb720-heribert-hymns-freeze-v1",
        "status": "review-ready-staged-only", "canonical_root": ROOT.as_posix(),
        "canonical_install": "not-performed", "source_path": source.SOURCE.as_posix(),
        "source_sha256": source.SOURCE_SHA256, "package_path": source.PACKAGE.as_posix(),
        "package_sha256": source.PACKAGE_SHA256, "direct_receipt": DIRECT.as_posix(),
        "direct_receipt_sha256": DIRECT_SHA, "works": pins,
    }
    _io_path(FREEZE).write_bytes(source._json(frozen))
    return {"freeze": FREEZE.as_posix(), "freeze_sha256": _sha(FREEZE),
            "works": {pin["work_id"]: pin["stage_receipt_sha256"] for pin in pins}}


if __name__ == "__main__":
    print(json.dumps(prepare(), sort_keys=True))
