"""Freeze exact source, candidate, and complete two-edition Vita Lupi stage pins."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from build.tei import openmgh_vita_lupi_dual as source
from build.tools import stage_openmgh_vita_lupi_dual as staging
from ocd_kernel.tei.install_accepted import _files, _io_path


STAGE = Path("D:/Library/Open Christian Data/candidate-reviews/openmgh-vita-lupi-dual-stage-20260927-v1")
FREEZE = source.ROOT / "plans/2026-09-22-source-preflight/openmgh-vita-lupi-dual-freeze-20260927-v1.json"
CONTRACT = "ocd-openmgh-vita-lupi-dual-freeze-v1"


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def main() -> None:
    if _io_path(FREEZE).exists():
        raise ValueError("Vita Lupi freeze already exists")
    receipt = json.loads(_io_path(STAGE / "stage-receipt.json").read_bytes())
    if (receipt.get("contract") != staging.CONTRACT or receipt.get("status") != "staged-only"
            or receipt.get("installation") != "not-performed" or len(receipt.get("editions", [])) != 2
            or {item["code"] for item in receipt["editions"]} != set(source.WITNESSES)
            or receipt.get("projection_rows") != 2):
        raise ValueError("Vita Lupi two-edition stage scope differs")
    work = Path("library/works") / source.WORK_ID
    if _files(source.ROOT / work) != receipt["before"] or _files(STAGE / work) != receipt["after"]:
        raise ValueError("Vita Lupi stage/canonical file maps differ")
    selected = []
    for item in receipt["editions"]:
        code = item["code"]
        source_path, package_path, acquisition_receipt_path = source.paths(code)
        if (_sha(source.ROOT / source_path) != item["source_sha256"]
                or _sha(source.ROOT / package_path) != item["package_sha256"]
                or _sha(source.ROOT / acquisition_receipt_path) != item["receipt_sha256"]):
            raise ValueError(f"{code} retained authority changed")
        selected.append(dict(item))
    freeze = dict(contract=CONTRACT, status="review-ready-staged-only",
                  work_id=source.WORK_ID, canonical_root=source.ROOT.as_posix(),
                  stage_root=STAGE.as_posix(), stage_receipt=(STAGE / "stage-receipt.json").as_posix(),
                  stage_receipt_sha256=_sha(STAGE / "stage-receipt.json"),
                  stage_files=_files(STAGE), before=receipt["before"], after=receipt["after"],
                  direct_receipt=(staging.DIRECT / "receipt.json").as_posix(),
                  direct_receipt_sha256=staging.DIRECT_SHA, editions=selected,
                  selected_edition_count=2, total_sibling_work_divisions=57,
                  source_disposition="Two separately acquired, source-exclusive work divisions; every selected source node and header retained in its own edition. ZIPs are packages only.",
                  canonical_install="not-performed", corpus_refresh="not-performed",
                  rights_clearance="not-established", public_release="not-performed")
    _io_path(FREEZE).write_bytes((json.dumps(freeze, ensure_ascii=False, sort_keys=True,
                                            separators=(",", ":")) + "\n").encode())
    print(json.dumps(dict(freeze=FREEZE.as_posix(), sha256=_sha(FREEZE),
                          stage_files=len(freeze["stage_files"]), editions=2), sort_keys=True))


if __name__ == "__main__":
    main()
