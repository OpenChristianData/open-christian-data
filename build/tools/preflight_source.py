"""Inventory retained XML/JSON sources before writing a converter."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from build.lib.source_preflight import check_rules, preflight


def _policy_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate policy key: {key}")
        result[key] = value
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="explicit retained file or directory")
    parser.add_argument("--encoding", default="utf-8", help="strict explicit decoding; default UTF-8")
    parser.add_argument("--policy", type=Path, help="JSON array of exact feature dispositions")
    parser.add_argument("--max-bytes", type=int, default=64 * 1024 * 1024)
    parser.add_argument("--html-member", help="exact ZIP HTML member for image-reference accounting")
    parser.add_argument("--repository-root", type=Path, help="resolve a logical source through configured storage")
    args = parser.parse_args(argv)
    try:
        rules = check_rules(json.loads(args.policy.read_text(encoding="utf-8"), object_pairs_hook=_policy_object)) if args.policy else None
        source = args.source
        if args.repository_root:
            from ocd_kernel.lib.storage_topology import resolve_repo_path
            source = resolve_repo_path(args.repository_root, args.source.as_posix())
        if source.suffix.lower() == ".zip":
            if rules is not None:
                raise ValueError("ZIP feature policies are unsupported; use member-level source profiles")
            from build.lib.source_archive import inventory_zip
            report = inventory_zip(source, html_member=args.html_member, encoding=args.encoding, max_bytes=args.max_bytes)
        else:
            if args.html_member:
                raise ValueError("--html-member requires a ZIP source")
            report = preflight(source, encoding=args.encoding, rules=rules, max_bytes=args.max_bytes)
    except (OSError, ValueError, LookupError) as exc:
        print(f"source preflight: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False))
    return 2 if report["status"] == "blocked" else 1 if report["status"] == "needs-disposition" else 0


if __name__ == "__main__":
    raise SystemExit(main())
