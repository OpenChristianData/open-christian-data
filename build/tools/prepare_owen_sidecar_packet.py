"""Prepare the 29 identity-only Owen XML sidecar declarations."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError, canonical_bytes, sha256_file


def _ref(root: Path, rel: str) -> dict[str, str]:
    path = resolve_repo_path(root, rel)
    if not path.is_file():
        raise PipelineError(f"missing Owen evidence: {rel}")
    return {"path": rel, "sha256": sha256_file(path)}


def prepare(root: Path) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for number in (50, 51, 52):
        cohort = f"lib0{number}"
        base = f"sources/structured-text/{cohort}-john-owen"
        manifest_rel = f"{base}/john-owen-{cohort}.source-manifest.json"
        manifest = json.loads(resolve_repo_path(root, manifest_rel).read_text(encoding="utf-8"))
        profile_item = next(item for item in manifest["authorities"]
                            if item["role"] == "complete-source-feature-profile")
        profile = json.loads(resolve_repo_path(root, profile_item["path"]).read_text(encoding="utf-8"))
        primary = {item["name"]: item for item in manifest["authorities"]
                   if item["role"] == "primary-source"}
        if len(profile["works"]) != 10 or len(primary) != 10:
            raise PipelineError(f"{cohort} Owen source census differs")
        for item in profile["works"]:
            wid = item["work_id"]
            work_rel = f"library/works/{wid}/work.json"
            state_rel = f"library/works/{wid}/state.json"
            work = json.loads(resolve_repo_path(root, work_rel).read_text(encoding="utf-8"))
            state = json.loads(resolve_repo_path(root, state_rel).read_text(encoding="utf-8"))
            if wid == "john-owen-conscience":
                if len(work["textual_forms"]) != 1 or not state["targets"]:
                    raise PipelineError("the accepted Conscience work changed")
                continue
            if work["textual_forms"] or state["targets"]:
                raise PipelineError(f"{wid} is no longer identity-only")
            source = primary[item["authority_name"]]
            source_path = resolve_repo_path(root, source["path"])
            if source_path.stat().st_size != source["bytes"] or sha256_file(source_path) != source["sha256"]:
                raise PipelineError(f"{wid} source bytes differ from manifest")
            xml = etree.parse(str(source_path), etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False))
            edition = xml.getroot().find("./ThML.head/electronicEdInfo")
            if edition is None:
                raise PipelineError(f"{wid} XML edition header missing")
            source_titles = [" ".join("".join(node.itertext()).split())
                             for node in edition.findall("./DC/DC.Title")]
            identifier = edition.find('./DC/DC.Identifier[@scheme="URL"]')
            if identifier is None or not identifier.text or not identifier.text.startswith("/ccel/owen/"):
                raise PipelineError(f"{wid} CCEL source URL missing")
            warnings = [
                "The retained CCEL XML carries CCEL file and formatting rights and a credit request; publication rights and attribution require separate review.",
            ]
            status_node = edition.find("status")
            source_status = " ".join("".join(status_node.itertext()).split()) if status_node is not None else ""
            if "not been proof-read" in source_status:
                warnings.append("The retained electronic text is marked as not proofread; source-to-TEI fidelity and review remain open.")
            elif not source_status:
                warnings.append("The retained XML does not state a proofreading status; source-to-TEI fidelity and review remain open.")
            editorial = " ".join("".join(edition.find("editorialComments").itertext()).split()) if edition.find("editorialComments") is not None else ""
            if "AGES" in editorial:
                warnings.append("The XML credits an AGES Digital Library electronic base text and asserts AGES Software copyright; its rights are unresolved.")
            if work["title"] not in source_titles:
                warnings.append("The retained XML title differs from the catalog title; edition title equivalence needs review.")
            config_rel = f"{base}/work-bindings/{wid}/config.json"
            rows.append({
                "work_id": wid,
                "work": _ref(root, work_rel),
                "state": _ref(root, state_rel),
                "source_manifest": _ref(root, manifest_rel),
                "cohort_source_set": {"path": profile_item["path"], "sha256": profile_item["sha256"]},
                "config": _ref(root, config_rel),
                "primary_source": source,
                "textual_form_id": f"{wid}-english",
                "edition_id": f"{wid}-ccel-thml-electronic",
                "acquisition_id": f"{wid}-ccel-retained-xml",
                "edition_title": "CCEL ThML electronic witness",
                "provider": "Christian Classics Ethereal Library",
                "url": "https://www.ccel.org" + identifier.text.strip(),
                "language": "en",
                "media_type": "application/xml",
                "source_scope": f"Complete acquired file {source['path']}; the pinned {cohort.upper()} profile assigns this distinct XML witness to {wid}. This acquisition does not establish a complete TEI reconstruction or acceptance.",
                "warnings": warnings,
            })
    if len(rows) != 29 or len({row["work_id"] for row in rows}) != 29:
        raise PipelineError("Owen identity-only work census is not 29")
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
    print(f"prepared {len(packet['entries'])} Owen source-bound entries: {args.output}")


if __name__ == "__main__":
    main()
