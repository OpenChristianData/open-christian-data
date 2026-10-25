"""Stage source-inspected bsb00000752 Latin narrative witnesses individually."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from build.tools import stage_openmgh_bsb830_next as staging
from ocd_kernel.library._common import PipelineError


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("raw/openmgh/bsb00000752/tei/bsb00000752.xml")
SOURCE_SHA = "620b80ade431a814ebf41296cdf88476d9a39741cdba1925c0cd75fb9772c98a"
BATCHES = {
    "inspected": (
        Path("plans/2026-09-22-source-preflight/openmgh-bsb752-inspected-batch-20260926.json"),
        "d1c92151e7d938325af05ec01644c7ce626fa81899bba1d87105116726511845",
    ),
    "addendum": (
        Path("plans/2026-09-22-source-preflight/openmgh-bsb752-remaining-six-20260926.json"),
        "18991e43e5767084fc6ff4ab1d56f314bbf1a23fe2a318223e20a1e6c6e14f1c",
    ),
}
WORKS = {
    "passio-sancti-germani-grandivallensis": ("inspected", "DOMINIS EXIMIIS ET SACRIS CULMINIBUS"),
    "passio-sancti-praeiecti": ("inspected", "Igitur sanctus Preiectus Arvernensium provincia"),
    "passio-sanctorum-kiliani-et-sociorum": ("inspected", "Fuit vir vitae venerabilis nomine Killena"),
    "revelatio-beati-baronti": ("inspected", "Memorare vobis volo, fratres karissimi"),
    "transitus-sancti-condedi": ("inspected", "Translato igitur ad caelestia regna"),
    "vita-beati-audoini": ("inspected", "Sanctorum vita virorum quamquam sit gloriosa"),
    "vita-sanctae-sadalbergae": ("inspected", "Igitur Sadlaberga in suburbano Leucorum"),
    "vita-sancti-ermenlandi": ("inspected", "Multorum iam per orbem universum"),
    "vita-sancti-frodoberti": ("addendum", "Fuit vir vitae valde venerabilis"),
    "vita-sancti-memmii": ("addendum", "In temporibus illis cum beatissimus Memmius"),
    "vita-sancti-menelei": ("addendum", "Claris ortus natalibus, beatus Meneleus"),
    "vita-sancti-wandregiseli": ("addendum", "Relegiosorum quorundam virorum vita"),
}


def receipt_path(work_id: str) -> Path:
    if work_id not in WORKS:
        raise PipelineError(f"work outside the twelve inspected bsb752 narratives: {work_id}")
    return ROOT / "plans/2026-09-22-source-preflight" / f"{work_id}-openmgh-bsb752-acceptance-stage-20260926.json"


def prepare(work_id: str, scratch: Path) -> dict:
    batch_key, clause = WORKS[work_id]
    batch, digest = BATCHES[batch_key]
    if hashlib.sha256((ROOT / batch).read_bytes()).hexdigest() != digest:
        raise PipelineError("original 752 inspection receipt changed")
    staging.SOURCE = SOURCE
    staging.SOURCE_SHA = SOURCE_SHA
    staging.BATCH = batch
    staging.CATEGORY = "prose"
    staging.IDS = {work_id: clause}
    return staging.prepare(ROOT, work_id, scratch, receipt_path(work_id))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work_id", choices=sorted(WORKS))
    parser.add_argument("--scratch", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.work_id, args.scratch)
    receipt = receipt_path(args.work_id)
    print(json.dumps({"work_id": args.work_id, "status": result["status"],
                      "receipt": receipt.as_posix(),
                      "receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
                      "accepted_master_sha256": result["accepted_master_sha256"],
                      "projection_rows": result["projection_rows"],
                      "installation": result["installation"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
