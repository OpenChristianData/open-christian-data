"""Screen every declared accepted edition; findings are advisory, coverage gaps fail.

Run with ``python -m build.tools.lint_library_text --output <new-directory>``.
This reads current sidecars, never the generated corpus manifest or old reports.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from build.lib.text_lint import lint_xml_file
from ocd_kernel.lib.path_io import io_glob, io_path, resolve_path
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import load_editions
from ocd_kernel.tei.acceptance import load_acceptance


def digest(path: Path) -> str:
    return hashlib.sha256(io_path(path).read_bytes()).hexdigest()


def authorities(root: Path) -> dict[str, str]:
    paths = list(io_glob(root / "library/works", "*/work.json"))
    paths += list(io_glob(root / "library/works", "*/forms/*/editions/*/acceptance.json"))
    return {p.relative_to(root).as_posix(): digest(p) for p in sorted(paths)}


def scan_library(root: Path, output: Path) -> dict:
    root = resolve_path(root, strict=True)
    output = resolve_path(output)
    io_path(output).mkdir(parents=True, exist_ok=False)
    initial = authorities(root)
    software = {str(p): digest(p) for p in (Path(__file__), Path(__file__).parents[1] / "lib/text_lint.py",
                                          Path(__file__).parents[1] / "lib/text_xml_reader.py")}
    if not initial:
        raise ValueError("No library work authorities found")
    rows, declared, scanned = [], set(), {}
    totals = Counter()
    with io_path(output / "observations.jsonl").open("w", encoding="utf-8", newline="\n") as findings:
        for reference in sorted(p for p in initial if p.endswith("/work.json")):
            work_path = root / reference
            try:
                editions = load_editions(work_path)
            except (OSError, ValueError, PipelineError) as exc:
                rows.append({"work_path": reference, "status": "invalid_work", "error": str(exc)})
                continue
            for edition in editions:
                acceptance_path = edition.path.with_name("acceptance.json")
                relative = acceptance_path.relative_to(root).as_posix()
                declared.add(relative)
                row = {"work_id": edition.work_id, "textual_form_id": edition.textual_form_id,
                       "edition_id": edition.edition_id, "acceptance_path": relative}
                if relative not in initial:
                    row["status"] = "no_acceptance"
                    rows.append(row)
                    continue
                try:
                    acceptance = load_acceptance(acceptance_path)
                    expected_identity = {k: row[k] for k in ("work_id", "textual_form_id", "edition_id")}
                    if any(acceptance["identity"][k] != v for k, v in expected_identity.items()):
                        raise ValueError("Acceptance identity differs from declared edition")
                    promotion = acceptance.get("promotion", {})
                    if promotion.get("status") != "promoted":
                        raise ValueError("Acceptance is not promoted")
                    master = promotion["master"]
                    if master["path"] != edition.path.relative_to(root).as_posix():
                        raise ValueError("Accepted master path differs from declared edition")
                    if digest(edition.path) != master["sha256"] or io_path(edition.path).stat().st_size != master["bytes"]:
                        raise ValueError("Accepted master bytes/hash differ from acceptance")
                    report = lint_xml_file(io_path(edition.path))
                    if report["source_sha256"] != master["sha256"]:
                        raise ValueError("Master changed between acceptance check and text scan")
                    scanned[master["path"]] = master["sha256"]
                    row.update(status="scanned", master=master, groups=report["groups"],
                               units=report["coverage"]["units"], characters=report["coverage"]["characters"],
                               xml_reader=report["coverage"]["xml_reader"],
                               source_quality_uncertainty=acceptance.get("review", {}).get("source_quality_uncertainty", []))
                    row["groups_by_region"] = [{"region": region, "reading": reading, "rule": rule, "count": count}
                        for (region, reading, rule), count in Counter(
                            (o["region"], o["reading"], o["rule"]) for o in report["observations"]).items()]
                    totals.update({g["rule"]: g["count"] for g in report["groups"]})
                    for finding in report["observations"]:
                        finding.update(work_id=edition.work_id, edition_id=edition.edition_id,
                                       master_sha256=master["sha256"], master_path=master["path"],
                                       role=report["coverage"]["roles"][finding["locator"]])
                        findings.write(json.dumps(finding, ensure_ascii=True, sort_keys=True) + "\n")
                except (OSError, ValueError, PipelineError, RecursionError) as exc:
                    row.update(status="scan_failed", error=str(exc))
                rows.append(row)
            if len(rows) % 50 == 0:
                print(f"Accounted for {len(rows)} edition records", flush=True)
    for reference in sorted(p for p in initial if p.endswith("/acceptance.json") and p not in declared):
        rows.append({"acceptance_path": reference, "status": "orphan_acceptance"})
    drift = []
    drift.extend(p for p, pin in software.items() if digest(Path(p)) != pin)
    final = authorities(root)
    for reference in sorted(set(initial) | set(final)):
        if initial.get(reference) != final.get(reference):
            drift.append(reference)
    for reference, pin in scanned.items():
        try:
            if digest(root / reference) != pin:
                drift.append(reference)
        except OSError:
            drift.append(reference)
    statuses = Counter(row["status"] for row in rows)
    complete = not drift and not any(k not in {"scanned", "no_acceptance"} for k in statuses)
    summary = {"format": "ocd-library-text-screen-v1", "created_utc": datetime.now(timezone.utc).isoformat(),
               "status": "complete" if complete else "incomplete", "text_correctness": "not_assessed",
               "work_count": sum(p.endswith("/work.json") for p in initial), "statuses": dict(statuses),
               "observation_counts": dict(totals), "authorities": initial, "changed_during_scan": drift,
               "software": software,
               "limits": "All XML element text/tails including headers, notes, sic/corr and retained evidence. "
                         "Attributes/comments/PI values and cross-inline character sequences are not screened. "
                         "No spelling, grammar, intended-reading, source-fidelity, rights or publication judgment.",
               "editions": rows}
    io_path(output / "summary.json").write_text(json.dumps(summary, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    summary = scan_library(args.root, args.output)
    print(json.dumps({k: summary[k] for k in ("status", "work_count", "statuses", "observation_counts")}, sort_keys=True))
    return 0 if summary["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
