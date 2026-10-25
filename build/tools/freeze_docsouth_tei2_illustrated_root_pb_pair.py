"""Seal two illustrated DocSouth front/body/back stages."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from build.tei import docsouth_tei2_illustrated_root_pb_pair as source
from build.tools import prepare_docsouth_tei2_illustrated_root_pb_pair as direct_source
from build.tools import stage_docsouth_tei2_illustrated_root_pb_pair as staging
from ocd_kernel.tei.install_accepted import _files, _io_path


ROOT = Path(__file__).resolve().parents[2]
FREEZE = ROOT / "plans/2026-09-22-source-preflight/docsouth-tei2-illustrated-root-pb-pair-freeze-20260927.json"
STAGE_HOME = Path("D:/Library/Open Christian Data/candidate-reviews/docsouth-illustrated-root-pb-pair-stages-20260927-v2")
CONTRACT = "ocd-docsouth-tei2-illustrated-root-pb-pair-freeze-v1"


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def main() -> None:
    if _io_path(FREEZE).exists():
        raise ValueError("DocSouth freeze already exists")
    if _sha(staging.DIRECT / "receipt.json") != staging.DIRECT_SHA:
        raise ValueError("DocSouth direct receipt differs")
    direct = json.loads(_io_path(staging.DIRECT / "receipt.json").read_bytes())
    entries = {item["work_id"]: item for item in direct["selected_works"]}
    if set(entries) != set(direct_source.SELECTIONS):
        raise ValueError("DocSouth selection differs")
    pins = []
    for work_id, entry in sorted(entries.items()):
        stage = STAGE_HOME / work_id
        receipt = stage / "stage-receipt.json"
        record = json.loads(_io_path(receipt).read_bytes())
        work = Path("library/works") / work_id
        if (record.get("contract") != staging.CONTRACT or record.get("status") != "staged-only"
                or record.get("installation") != "not-performed" or record.get("work_id") != work_id
                or record.get("projection_rows") != entry["native_projection_rows"]
                or record.get("source_sha256") != entry["source_sha256"]
                or record.get("source_entity_declarations") != entry["producer"]["source_entity_declarations"]
                or record.get("source_rights_text_sha256") != entry["producer"]["source_rights_text_sha256"]
                or record.get("source_oracle") != entry["oracle"]
                or _files(ROOT / work) != record["before"] or _files(stage / work) != record["after"]
                or _sha(staging.REPRO / work_id / "candidate.tei.xml") != entry["candidate_sha256"]):
            raise ValueError(f"DocSouth stage or source differs: {work_id}")
        pins.append(dict(work_id=work_id, source_path=entry["source_path"],
                         source_sha256=entry["source_sha256"], source_bytes=entry["source_bytes"],
                         source_doctype=entry["producer"]["source_doctype"],
                         source_entity_declarations=entry["producer"]["source_entity_declarations"],
                         source_rights_text_sha256=entry["producer"]["source_rights_text_sha256"],
                         source_oracle=entry["oracle"],
                         acquisition_receipt_sha256=entry["acquisition_receipt_sha256"],
                         direct_candidate_sha256=entry["candidate_sha256"],
                         stage_receipt=f"{work_id}/stage-receipt.json", stage_receipt_sha256=_sha(receipt),
                         stage_files=_files(stage), accepted_master_sha256=record["accepted_master_sha256"],
                         acceptance_sha256=record["acceptance_sha256"],
                         projection_rows=entry["native_projection_rows"],
                         before_count=len(record["before"]), after_count=len(record["after"])))
    freeze = dict(contract=CONTRACT, status="review-ready-staged-only", canonical_root=ROOT.as_posix(),
                  stage_home=STAGE_HOME.as_posix(), inventory_path=source.INVENTORY.relative_to(ROOT).as_posix(),
                  inventory_sha256=_sha(source.INVENTORY),
                  direct_receipt=(staging.DIRECT / "receipt.json").as_posix(),
                  direct_receipt_sha256=staging.DIRECT_SHA, selected_work_count=2,
                  other_inventory_work_count=25, works=pins, canonical_install="not-performed")
    _io_path(FREEZE).write_bytes(json.dumps(freeze, sort_keys=True, indent=2, ensure_ascii=False).encode("utf-8") + b"\n")
    print(json.dumps(dict(freeze=FREEZE.as_posix(), freeze_sha256=_sha(FREEZE), works=len(pins)), sort_keys=True))


if __name__ == "__main__":
    main()
