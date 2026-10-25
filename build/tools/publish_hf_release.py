"""Preview an exact v2 public release offline. Upload is deliberately unavailable."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ocd_kernel.library._common import PipelineError
from ocd_kernel.release.selection import load_release_selection
from ocd_kernel.release.public_allowlist import preview_release


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true", required=True)
    args = parser.parse_args(argv)
    try:
        result = preview_release(args.root, args.release, selection=load_release_selection(args.selection))
    except (PipelineError, OSError, ValueError) as exc:
        result = {"status": "fail", "errors": [str(exc)], "files": [], "upload_performed": False,
                  "publication_authorized": False}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
