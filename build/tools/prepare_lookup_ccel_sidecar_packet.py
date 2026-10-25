"""Prepare source-bound sidecars for the two retained CCEL lookup works."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from build.tools.library_lookup_ccel_binding import PREFLIGHT
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError, canonical_bytes, sha256_file


def _ref(root: Path, rel: str) -> dict[str, str]:
    path = resolve_repo_path(root, rel)
    if not path.is_file():
        raise PipelineError(f"missing lookup evidence: {rel}")
    return {"path": rel, "sha256": sha256_file(path)}


def prepare(root: Path) -> dict[str, object]:
    evidence = json.loads(resolve_repo_path(root, PREFLIGHT).read_text(encoding="utf-8"))
    if {item.get("work_id") for item in evidence.get("works", [])} != {
        "edwards-select-sermons", "spurgeons-morning-evening"
    }:
        raise PipelineError("two-work lookup preflight census differs")
    rows = []
    for item in evidence["works"]:
        wid = item["work_id"]
        work = json.loads(resolve_repo_path(root, item["work"]).read_text(encoding="utf-8"))
        state_rel = f"library/works/{wid}/state.json"
        state = json.loads(resolve_repo_path(root, state_rel).read_text(encoding="utf-8"))
        if work["textual_forms"] or state["targets"]:
            raise PipelineError(f"{wid} is no longer identity-only")
        source = resolve_repo_path(root, item["retained_source"])
        if (source.stat().st_size != item["retained_bytes"]
                or sha256_file(source) != item["retained_sha256"]):
            raise PipelineError(f"{wid} retained XML differs from preflight")
        if wid == "edwards-select-sermons":
            warnings = [
                "The retained XML has blank DC.Rights; public release rights for CCEL transcription and markup require separate review.",
                "The legacy config notes footnotes excluded by its parser; source-to-TEI accounting must assess the complete retained XML independently.",
                "The config records CCEL permission to parse; a public attribution deliverable and edition review remain open.",
            ]
        else:
            warnings = [
                "The retained XML states Public Domain in DC.Rights; CCEL and Logos electronic source rights and publication rights require separate review.",
                "The electronic header records editorial changes; equivalence to an 1865 print edition is unverified.",
                "The retained header includes a converter contact address; keep it in private evidence and review any public attribution projection.",
                "The retained XML has no proofreading status; source-to-TEI fidelity review remains open.",
            ]
        rows.append({
            "work_id": wid,
            "work": _ref(root, item["work"]),
            "state": _ref(root, state_rel),
            "lookup_source_evidence": _ref(root, PREFLIGHT),
            "config": _ref(root, item["config"]),
            "primary_source": {"path": item["retained_source"], "bytes": item["retained_bytes"],
                               "sha256": item["retained_sha256"]},
            "textual_form_id": f"{wid}-english",
            "edition_id": f"{wid}-ccel-thml-electronic",
            "acquisition_id": f"{wid}-ccel-retained-xml",
            "edition_title": "CCEL ThML electronic witness",
            "provider": "Christian Classics Ethereal Library",
            "url": item["config_source_url"],
            "language": "en",
            "media_type": "application/xml",
            "source_scope": f"Complete acquired file {item['retained_source']}; the retained XML is the electronic witness for {wid}. This accounting does not establish complete TEI reconstruction, print-edition equivalence, or acceptance.",
            "warnings": warnings,
        })
    return {"contract": "ocd-library-sidecar-batch-v1", "entries": sorted(rows, key=lambda row: row["work_id"])}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    packet = prepare(args.repository_root.resolve())
    if args.output.exists():
        raise PipelineError(f"packet already exists: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_bytes(packet))
    print(f"prepared {len(packet['entries'])} lookup CCEL entries: {args.output}")


if __name__ == "__main__":
    main()
