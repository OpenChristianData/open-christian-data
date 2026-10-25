"""Seal seven staged bsb830 simony poems into one exact reviewed pin index."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from build.tei import openmgh_bsb830_simony_seven as source
from build.tools import stage_openmgh_bsb830_simony_seven as staging
from ocd_kernel.tei.install_accepted import _files, _io_path


ROOT = Path(__file__).resolve().parents[2]
FREEZE = ROOT / "plans/2026-09-22-source-preflight/openmgh-bsb830-simony-seven-freeze-20260927-v2.json"
STAGE_HOME = Path("D:/Library/Open Christian Data/candidate-reviews/bsb830-simony-seven-stages-20260927-v2")
CONTRACT = "ocd-openmgh-bsb830-simony-seven-freeze-v1"


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def main() -> None:
    if _io_path(FREEZE).exists():
        raise ValueError("bsb830 simony freeze already exists")
    if _sha(staging.DIRECT / "receipt.json") != staging.DIRECT_SHA:
        raise ValueError("bsb830 simony direct receipt changed")
    direct = json.loads(_io_path(staging.DIRECT / "receipt.json").read_bytes())
    entries = {item["work_id"]: item for item in direct["selected_works"]}
    if set(entries) != set(source.SELECTED):
        raise ValueError("bsb830 simony seven-work scope differs")
    pins = []
    for work_id, entry in sorted(entries.items()):
        stage = STAGE_HOME / work_id
        receipt = stage / "stage-receipt.json"
        record = json.loads(_io_path(receipt).read_bytes())
        work = Path("library/works") / work_id
        if (record.get("contract") != staging.CONTRACT or record.get("status") != "staged-only"
                or record.get("installation") != "not-performed" or record.get("work_id") != work_id
                or record.get("projection_rows") != 1 or record.get("category") != "poetry"
                or record.get("language") != "la" or record.get("source_sha256") != source.SOURCE_SHA
                or record.get("source_selection_c14n_sha256") != entry["oracle"]["selection_c14n_sha256"]
                or record.get("source_oracle") != entry["oracle"]
                or _files(ROOT / work) != record["before"] or _files(stage / work) != record["after"]
                or _sha(staging.REPRO / work_id / "candidate.tei.xml") != entry["candidate_sha256"]):
            raise ValueError(f"bsb830 simony staged work differs: {work_id}")
        pins.append(dict(work_id=work_id, source_path=entry["source_path"],
                         source_sha256=entry["source_sha256"], source_bytes=entry["source_bytes"],
                         package_path=entry["package_path"], package_sha256=entry["package_sha256"],
                         acquisition_receipt_sha256=entry["acquisition_receipt_sha256"],
                         source_oracle=entry["oracle"], projection_rows=1,
                         source_division_ordinal=25,
                         source_child_start=record["source_child_start"],
                         source_child_end=record["source_child_end"],
                         catalog_first_xml_id=entry["oracle"]["catalog_first_xml_id"],
                         catalog_last_xml_id=entry["oracle"]["catalog_last_xml_id"],
                         source_selection_c14n_sha256=record["source_selection_c14n_sha256"],
                         direct_candidate_sha256=entry["candidate_sha256"],
                         stage_receipt=f"{work_id}/stage-receipt.json", stage_receipt_sha256=_sha(receipt),
                         stage_files=_files(stage), accepted_master_sha256=record["accepted_master_sha256"],
                         acceptance_sha256=record["acceptance_sha256"],
                         before_count=len(record["before"]), after_count=len(record["after"])))
    ordered = sorted((pin["source_child_start"], pin["source_child_end"]) for pin in pins)
    if ordered != [(4, 102), (103, 129), (130, 179), (180, 229), (230, 275), (276, 404), (405, 479)]:
        raise ValueError("bsb830 source node partition differs")
    frozen = dict(contract=CONTRACT, status="review-ready-staged-only", canonical_root=ROOT.as_posix(),
                  stage_home=STAGE_HOME.as_posix(), source_path=source.SOURCE.as_posix(),
                  source_sha256=source.SOURCE_SHA, package_path=source.PACKAGE.as_posix(),
                  package_sha256=source.PACKAGE_SHA,
                  package_disposition="acquisition package only; extracted XML is text authority",
                  acquisition_receipt_path=source.ACQUISITION_RECEIPT.as_posix(),
                  acquisition_receipt_sha256=source.ACQUISITION_RECEIPT_SHA,
                  direct_receipt=(staging.DIRECT / "receipt.json").as_posix(),
                  direct_receipt_sha256=staging.DIRECT_SHA,
                  source_division_ordinal=25, source_division_child_count=480,
                  shared_heading_child_indexes=[0, 1, 2, 3], selected_child_range=[4, 479],
                  selected_work_count=7, other_source_work_divisions=28,
                  works=pins, canonical_install="not-performed")
    _io_path(FREEZE).write_bytes(json.dumps(frozen, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n")
    print(json.dumps(dict(freeze=FREEZE.as_posix(), freeze_sha256=_sha(FREEZE), works=len(pins)), sort_keys=True))


if __name__ == "__main__":
    main()
