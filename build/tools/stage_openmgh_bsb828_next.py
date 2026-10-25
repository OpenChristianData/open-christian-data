"""Stage only the eleven inspected bsb00000828 electronic prose witnesses."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from build.tools import stage_openmgh_bsb830_next as shared


SOURCE = Path("raw/openmgh/bsb00000828/tei/bsb00000828.xml")
SOURCE_SHA = "698ce3c035506c19292c4af5121f133cd5bf033c11eda238d2ed2338f3c872bd"
BATCH = Path("plans/2026-09-22-source-preflight/openmgh-bsb828-inspected-batch-20260926.json")
LATIN_CLAUSES = {
    "wido-monk-letter-to-archbishop-of-milan": "qui excellentiae vestrae summum discrimen audivimus",
    "humbert-three-books-against-simoniacs": "stulto cogimur, qui titulo frontis tractatus",
    "pseudo-udalric-letter-on-clerical-continence": "Domino et patri pervigili sanctae Romanae aecclesiae provisori",
    "gebhard-of-salzburg-letter-to-hermann": "sanctae Mettensis aecclesiae episcopo",
    "letter-to-hildebrand-under-theoderic-rubric": "auctoritatis assertione evidenti veritate",
    "peter-crassus-defense-of-henry-iv": "Henrico regi. 1. Haec aetas",
    "liber-canonum-against-henry": "Verbo Dei in utero Mariae virginis",
    "anselm-of-lucca-against-wibert": "Proprium est bonarum mentium",
    "wido-of-ferrara-on-hildebrands-schism": "negociis curiae vehementer urguebar",
    "bonizo-of-sutri-liber-ad-amicum": "quod hac tempestate mater",
    "clement-decree-to-orthodox-bishops": "Quantae et quam pestiferae scismaticorum",
}


def prepare(root: Path, work_id: str, scratch: Path, receipt: Path) -> dict:
    if work_id not in LATIN_CLAUSES:
        raise ValueError(f"work is outside the inspected bsb828 tranche: {work_id}")
    shared.SOURCE = SOURCE
    shared.SOURCE_SHA = SOURCE_SHA
    shared.BATCH = BATCH
    shared.IDS = LATIN_CLAUSES
    return shared.prepare(root, work_id, scratch, receipt)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work_id", choices=sorted(LATIN_CLAUSES))
    parser.add_argument("--root", type=Path, default=shared.ROOT)
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.root, args.work_id, args.scratch, args.receipt)
    print(json.dumps({key: result[key] for key in (
        "work_id", "status", "accepted_master_sha256", "projection_rows",
        "projection_status",
    )}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
