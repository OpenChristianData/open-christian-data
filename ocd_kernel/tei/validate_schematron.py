"""Validate JE apparatus TEI XML files against critical Schematron rules."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from lxml import etree
from lxml.isoschematron import Schematron

_SCHEMA: Schematron | None = None
_SCHEMA_PATH = Path(__file__).parent / "vendor" / "schematron" / "je_critical.sch"
_SVRL_NS = {"svrl": "http://purl.oclc.org/dsdl/svrl"}


def compiled_schema() -> Schematron:
    global _SCHEMA
    if _SCHEMA is None:
        _SCHEMA = Schematron(
            etree.parse(str(_SCHEMA_PATH)),
            error_finder=Schematron.ASSERTS_AND_REPORTS,
            store_report=True,
        )
    return _SCHEMA


def validate_file(path: str | Path) -> list[str]:
    document_path = Path(path)
    document = etree.parse(str(document_path))
    schema = compiled_schema()
    if schema.validate(document):
        return []
    report = schema.validation_report
    if report is None:
        return [str(error) for error in schema.error_log]
    failures: list[str] = []
    for failed_assert in report.xpath("//svrl:failed-assert | //svrl:successful-report", namespaces=_SVRL_NS):
        location = failed_assert.get("location", "unknown location")
        text = " ".join(failed_assert.xpath("normalize-space(svrl:text)", namespaces=_SVRL_NS).split())
        failures.append(f"{document_path.as_posix()}: {location}: {text}")
    return failures


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate JE apparatus TEI XML files against critical Schematron rules.")
    parser.add_argument("tei_files", nargs="+", type=Path)
    args = parser.parse_args(argv)

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
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
