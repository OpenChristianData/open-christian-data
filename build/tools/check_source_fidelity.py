"""Read-only source/TEI comparison, parser corroboration and mutation qualification."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from lxml import etree

from build.lib.source_fidelity import compare, digest
from build.lib.source_fidelity_adapters import prepare, strict_json
from build.lib.source_fidelity_mutations import qualify
from build.lib.source_parser_corroboration import corroborate
from build.lib.tei_link_check import check_links


def verify(source: bytes, candidate: bytes, profile: dict, *, mutations: bool = False) -> dict:
    plan = prepare(source, profile)
    format_name = {"catechism-json": "json", "plain-text-lines": "text"}.get(profile["adapter"], "xml")
    parser_evidence = corroborate(source, format_name)
    report = compare(plan, candidate, parser_evidence)
    try:
        report["local_links"] = check_links(candidate)
    except (ValueError, etree.XMLSyntaxError) as exc:
        report["local_links"] = {"status": "incomplete", "reason": str(exc)}
    if report["local_links"]["status"] == "fail":
        report["status"] = "fail"
    elif report["local_links"]["status"] == "incomplete" and report["status"] == "pass":
        report["status"] = "incomplete"
    checkout = Path(__file__).resolve().parents[2]
    report["implementation_sha256"] = {
        rel: digest((checkout / rel).read_bytes()) for rel in (
            "build/lib/source_fidelity.py", "build/lib/source_fidelity_adapters.py",
            "build/lib/source_fidelity_mutations.py", "build/lib/source_parser_corroboration.py",
            "build/tools/check_source_fidelity.py", "build/lib/tei_link_check.py")}
    if mutations:
        report["mutation_qualification"] = (
            qualify(plan, candidate, parser_evidence) if report["status"] == "pass" else
            {"status": "not-run", "reason": "combined baseline did not pass", "cases": []}
        )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-sha256", required=True,
                        help="SHA-256 declared by the retained-source authority")
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--candidate-sha256",
                        help="optional SHA-256 of an already bound candidate/master")
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--mutations", action="store_true")
    args = parser.parse_args(argv)
    try:
        inputs = [args.source, args.candidate, args.profile]
        snapshots = [path.read_bytes() for path in inputs]
        source, candidate, profile_bytes = snapshots
        for label, declared, actual in (
            ("source", args.source_sha256, digest(source)),
            ("candidate", args.candidate_sha256, digest(candidate)),
        ):
            if declared is None:
                continue
            if re.fullmatch(r"[0-9a-f]{64}", declared) is None:
                raise ValueError(f"{label} SHA-256 must be 64 lowercase hexadecimal characters")
            if actual != declared:
                raise ValueError(f"{label} SHA-256 mismatch: expected {declared}, observed {actual}")
        report = verify(source, candidate, strict_json(profile_bytes), mutations=args.mutations)
        for path, snapshot in zip(inputs, snapshots):
            if path.read_bytes() != snapshot:
                raise ValueError(f"input changed during checking: {path}")
        report["input_binding"] = {
            "source": "matched",
            "candidate": "matched" if args.candidate_sha256 is not None else "not-declared",
        }
    except (OSError, ValueError, etree.XMLSyntaxError) as exc:
        print(json.dumps(dict(status="blocked", error=str(exc)), ensure_ascii=True), file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    if report["status"] != "pass":
        return 1
    if args.mutations and report["mutation_qualification"]["status"] != "pass":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
