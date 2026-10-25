"""Print advisory observations; observations never imply incorrect source text."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from build.lib.text_lint import lint_file, lint_xml_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--pointer", action="append", help="Explicit JSON string-field pointer; repeat for multiple fields")
    parser.add_argument("--language", help="Caller-declared language; omitted means character rules only")
    parser.add_argument("--profile", choices=("conservative", "standard-ebooks"), default="conservative")
    parser.add_argument("--xml-segments", action="store_true", help="character-only checks of every XML text/tail segment")
    args = parser.parse_args(argv)
    try:
        if args.xml_segments:
            if args.pointer or args.language:
                raise ValueError("XML segment mode supports character checks only; omit pointers and language")
            result = lint_xml_file(args.source, profile=args.profile)
        else:
            result = lint_file(args.source, pointers=tuple(args.pointer) if args.pointer is not None else None,
                               language=args.language, profile=args.profile)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Unable to inspect {args.source}: {exc}\n")
    # ASCII escaping preserves exact code points on Windows console encodings.
    print(json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
