"""Seal the eleven staged bsb752 nested-part works into one reviewed pin index."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from build.tools import prepare_openmgh_bsb752_nested as source
from build.tools import stage_openmgh_bsb752_nested as staging
from ocd_kernel.tei.install_accepted import _files, _io_path


ROOT = Path(__file__).resolve().parents[2]
FREEZE = ROOT / "plans/2026-09-22-source-preflight/openmgh-bsb752-nested-freeze-20260927.json"
STAGE_HOME = Path("D:/Library/Open Christian Data/candidate-reviews/openmgh-bsb752-nested-stages-20260927-v2")


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def main() -> None:
    direct = json.loads(_io_path(staging.DIRECT / "receipt.json").read_bytes())
    if _sha(staging.DIRECT / "receipt.json") != staging.DIRECT_SHA:
        raise ValueError("bsb752 direct receipt changed")
    entries = {item["work_id"]: item for item in direct["selected_works"]}
    if set(entries) != set(source.SELECTIONS):
        raise ValueError("bsb752 eleven-work source selection changed")
    pins = []
    for work_id in sorted(entries):
        stage = STAGE_HOME / work_id
        receipt_path = stage / "stage-receipt.json"
        record = json.loads(_io_path(receipt_path).read_bytes())
        work = Path("library/works") / work_id
        if (record.get("contract") != staging.CONTRACT or record.get("status") != "staged-only"
                or record.get("installation") != "not-performed" or record.get("work_id") != work_id
                or record.get("projection_rows") != 1 or record.get("direct_receipt_sha256") != staging.DIRECT_SHA
                or _files(ROOT / work) != record["before"] or _files(stage / work) != record["after"]
                or _sha(staging.REPRO / work_id / "candidate.tei.xml") != entries[work_id]["candidate_sha256"]):
            raise ValueError(f"bsb752 stage or candidate changed: {work_id}")
        pins.append(dict(work_id=work_id, source_work_div_index=record["source_work_div_index"],
                         source_part_indexes=record["source_part_indexes"],
                         source_part_c14n_sha256=record["source_part_c14n_sha256"],
                         start_xml_id=entries[work_id]["oracle"]["start_xml_id"],
                         end_xml_id=entries[work_id]["oracle"]["end_xml_id"],
                         stage_receipt=f"{work_id}/stage-receipt.json", stage_receipt_sha256=_sha(receipt_path),
                         stage_files=_files(stage), accepted_master_sha256=record["accepted_master_sha256"],
                         acceptance_sha256=record["acceptance_sha256"],
                         before_count=len(record["before"]), after_count=len(record["after"])))
    freeze = dict(contract="ocd-openmgh-bsb752-nested-freeze-v1", status="review-ready-staged-only",
                  canonical_root=ROOT.as_posix(), stage_home=STAGE_HOME.as_posix(),
                  source_path=source.SOURCE.as_posix(), source_sha256=source.SOURCE_SHA,
                  package_path=source.PACKAGE.as_posix(), package_sha256=source.PACKAGE_SHA,
                  package_disposition="acquisition package only; extracted XML is text authority",
                  acquisition_receipt_path=source.ACQUISITION_RECEIPT.as_posix(),
                  acquisition_receipt_sha256=source.ACQUISITION_RECEIPT_SHA,
                  direct_receipt=(staging.DIRECT / "receipt.json").as_posix(),
                  direct_receipt_sha256=staging.DIRECT_SHA,
                  reproduced_candidate_count=11, selected_parts=13,
                  held_parts=direct["held_parts"], other_source_divisions=direct["other_source_divisions"],
                  works=pins, canonical_install="not-performed")
    if _io_path(FREEZE).exists():
        raise ValueError("bsb752 freeze already exists")
    _io_path(FREEZE).write_bytes(source._json(freeze))
    print(json.dumps(dict(freeze=FREEZE.as_posix(), freeze_sha256=_sha(FREEZE), works=len(pins)), sort_keys=True))


if __name__ == "__main__":
    main()
