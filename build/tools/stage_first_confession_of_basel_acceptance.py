"""Prepare the exact Basel electronic witness for guarded TEI acceptance.

This work-local route stages one complete promoted work. Public doctrinal-row
projection has its own unresolved proof-stream contract and is not asserted.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from build.tools import stage_creeds_json_acceptance as base


WORK_ID = "first-confession-of-basel"
ROUTE = {
    "manifest": "sources/doctrinal-documents/lib063-creeds-json/first-confession-of-basel/first-confession-of-basel.source-manifest.json",
    "candidate": "creeds-canon-variant-20260926/first-confession-of-basel",
    "package_sha256": "6864e920abc3edbcd2d33ada9f124755eb727b80e2fa2ddaf8b03b97f26aa338",
    "validation_sha256": "9750d373374a61119cb40d09f1c920b701ec944999905d8a2c5859dae86edf4a",
    "review": "plans/2026-09-22-source-preflight/first-confession-of-basel-stage-review-20260929.md",
    "review_sha256": "93ca22dbd44f283ec8508be91b618f69d7684ff99df7bdc4177f0795dd764e2d",
    "visual_loci": ["/Metadata", "/Data/0/Article", "/Data/6/Article", "/Data/12/Article"],
    "unreviewed": ["all remaining source/TEI visual locations", "full article and proof presentation", "full-document collation"],
}


def prepare(*, stage: Path, library: Path) -> dict[str, object]:
    if WORK_ID in base.ROUTES:
        raise ValueError("Basel acceptance route unexpectedly overlaps an existing route")
    base.ROUTES[WORK_ID] = ROUTE
    try:
        return base.prepare(WORK_ID, stage=stage, library=library)
    finally:
        del base.ROUTES[WORK_ID]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument(
        "--candidate-library", type=Path,
        default=Path("D:/Library/Open Christian Data/candidate-reviews"),
    )
    args = parser.parse_args()
    result = prepare(stage=args.stage, library=args.candidate_library)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
