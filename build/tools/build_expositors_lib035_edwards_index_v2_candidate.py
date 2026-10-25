"""Build formally validated, nonaccepted Edwards index-correction edition packages externally."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ocd_kernel.reconstruction import SourceManifest, reconstruct, validate

from build.tei.expositors_bible_lib035_readable_edwards_index_v2 import _convert
from build.tei.expositors_bible_lib035_readable_edwards_index_v2_oracle import _oracle
from build.tools.expositors_review import build_candidates as _shared_main

ROOT = Path(__file__).resolve().parents[2]
AUTHORITY = ROOT / 'sources/commentaries/expositors-bible/readable-edwards-index-v2'
MEMBERS = ('edwards-tc-expositorheb',)


def main() -> None:
    return _shared_main(AUTHORITY=AUTHORITY, MEMBERS=MEMBERS, ROOT=ROOT, _convert=_convert,
        _oracle=_oracle, __doc__=__doc__)


if __name__ == '__main__':
    main()
