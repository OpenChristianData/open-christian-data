"""Validate TEI XML files against the vendored TEI P5 XSD."""
from __future__ import annotations

import argparse
from pathlib import Path

from lxml import etree

_SCHEMA: etree.XMLSchema | None = None
_SCHEMA_PATH = Path(__file__).parent / "vendor" / "xsd" / "tei_all.xsd"


def compiled_schema() -> etree.XMLSchema:
    global _SCHEMA
    if _SCHEMA is None:
        _SCHEMA = etree.XMLSchema(etree.parse(str(_SCHEMA_PATH)))
    return _SCHEMA


def validate_file(path: str | Path) -> list[str]:
    document_path = Path(path)
    document = etree.parse(str(document_path))
    schema = compiled_schema()
    if schema.validate(document):
        return []
    return [str(error) for error in schema.error_log]


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate TEI XML files against vendored TEI P5 XSD.")
    parser.add_argument("tei_files", nargs="+", type=Path)
    args = parser.parse_args()

    failed = False
    for tei_file in args.tei_files:
        errors = validate_file(tei_file)
        if errors:
            failed = True
            print(f"FAIL {tei_file.as_posix()}")
            for error in errors:
                print(f"  {error}")
        else:
            print(f"PASS {tei_file.as_posix()}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
