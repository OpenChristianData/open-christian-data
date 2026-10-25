"""Build formally validated, nonaccepted Denney edition packages externally."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ocd_kernel.reconstruction import SourceManifest, reconstruct, validate

from build.tei.expositors_bible_lib034_readable_denney_pair import _convert
from build.tei.expositors_bible_lib034_readable_denney_pair_oracle import _oracle
from build.tools.expositors_review import build_candidates as _shared_main

ROOT = Path(__file__).resolve().parents[2]
AUTHORITY = ROOT / 'sources/commentaries/expositors-bible/readable-denney-pair-v4'
MEMBERS = ('denney-expositor2cor', 'denney-expositorthess')


def main() -> None:
    return _shared_main(AUTHORITY=AUTHORITY, MEMBERS=MEMBERS, ROOT=ROOT, _convert=_convert,
        _oracle=_oracle, __doc__=__doc__)


if __name__ == '__main__':
    main()
