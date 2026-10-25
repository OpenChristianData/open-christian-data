"""Seal the illustrated DocSouth Walters nested-text stage."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from build.tei import docsouth_tei2_illustrated_walters as source
from build.tools import prepare_docsouth_tei2_illustrated_walters as direct_source
from build.tools import stage_docsouth_tei2_illustrated_walters as staging
from ocd_kernel.tei.install_accepted import _files, _io_path
from build.tools.docsouth_review import freeze as _shared_main


ROOT = Path(__file__).resolve().parents[2]
FREEZE = ROOT / "plans/2026-09-22-source-preflight/docsouth-tei2-illustrated-walters-freeze-20260927.json"
STAGE_HOME = Path("D:/Library/Open Christian Data/candidate-reviews/docsouth-illustrated-walters-stages-20260927-v2")
CONTRACT = "ocd-docsouth-tei2-illustrated-walters-freeze-v1"


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def main() -> None:
    return _shared_main(CONTRACT=CONTRACT, FREEZE=FREEZE, ROOT=ROOT, STAGE_HOME=STAGE_HOME,
        _sha=_sha, direct_source=direct_source, source=source, staging=staging)


if __name__ == "__main__":
    main()
