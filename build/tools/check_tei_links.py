"""Check TEI local link closure without changing the candidate or its package."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from lxml import etree
from build.lib.tei_link_check import check_links


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args(argv)
    try:
        data = args.candidate.read_bytes()
        report = check_links(data)
        if args.candidate.read_bytes() != data:
            raise ValueError("candidate changed during checking")
    except (OSError, ValueError, etree.XMLSyntaxError) as exc:
        print(json.dumps(dict(status="blocked", error=str(exc))), file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
