"""Stage three exact flat-ab Latin verse witnesses without inventing lines."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from build.tools import stage_openmgh_bsb830_next as staging


CLAUSES = {
    "defense-of-priests-sons": "Rex immortalis, quam longo tempore talis",
    "exiled-monk-calamities-of-the-church-of-liege": "Nunc agit bellum",
    "hunald-carmen-de-anulo-et-baculo": "Hactenus ex vetito peccata fuere timori",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work_id", choices=sorted(CLAUSES))
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    staging.CATEGORY = "poetry"
    staging.IDS = CLAUSES
    result = staging.prepare(staging.ROOT, args.work_id, args.scratch, args.receipt)
    print(json.dumps({key: result[key] for key in (
        "work_id", "status", "accepted_master_sha256", "projection_rows",
        "projection_status", "installation",
    )}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
