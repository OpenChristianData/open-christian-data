"""Prepare exact div1 evidence and sidecar declarations for seven Chrysostom works."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError, canonical_bytes, sha256_file


BASE = "sources/structured-text/chrysostom-npnf110-111-112-114"
MANIFEST = BASE + "/npnf-chrysostom.source-manifest.json"
PROFILE = BASE + "/npnf-chrysostom.reconstruction-profile.json"
CHILDREN = (
    ("chrysostom-homilies-on-matthew", "npnf110", "iii"),
    ("chrysostom-homilies-on-acts", "npnf111", "vi"),
    ("chrysostom-homilies-on-romans", "npnf111", "vii"),
    ("chrysostom-homilies-on-1-corinthians", "npnf112", "iv"),
    ("chrysostom-homilies-on-2-corinthians", "npnf112", "v"),
    ("chrysostom-homilies-on-john", "npnf114", "iv"),
    ("chrysostom-homilies-on-hebrews", "npnf114", "v"),
)


def _ref(root: Path, rel: str) -> dict[str, str]:
    path = resolve_repo_path(root, rel)
    if not path.is_file():
        raise PipelineError(f"missing Chrysostom evidence: {rel}")
    return {"path": rel, "sha256": sha256_file(path)}


def prepare(root: Path, evidence_rel: str) -> tuple[dict, dict]:
    manifest = json.loads(resolve_repo_path(root, MANIFEST).read_text(encoding="utf-8"))
    profile = json.loads(resolve_repo_path(root, PROFILE).read_text(encoding="utf-8"))
    if (manifest.get("source_id") != "ccel-npnf-chrysostom-110-111-112-114-retained-xml"
            or profile.get("assigned_work_count") != 7):
        raise PipelineError("Chrysostom seven-work authority differs")
    primary = {Path(item["path"]).stem: item for item in manifest["authorities"]
               if item.get("role") == "primary-source"}
    if set(primary) != {"npnf110", "npnf111", "npnf112", "npnf114"}:
        raise PipelineError("Chrysostom four-volume source census differs")
    volume_data = {}
    for stem, item in primary.items():
        path = resolve_repo_path(root, item["path"])
        if path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]:
            raise PipelineError(f"{stem} retained XML differs from manifest")
        xml = etree.parse(str(path), etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False))
        header = xml.getroot().find("./ThML.head/electronicEdInfo/DC")
        if header is None:
            raise PipelineError(f"{stem} retained XML header missing")
        titles = [" ".join("".join(node.itertext()).split()) for node in header.findall("DC.Title")]
        rights = [" ".join("".join(node.itertext()).split()) for node in header.findall("DC.Rights")]
        if not titles or rights != ["Public Domain"]:
            raise PipelineError(f"{stem} retained XML title or rights changed")
        volume_data[stem] = (xml, titles[0], item)
    children = []
    rows = []
    for wid, stem, div1_id in CHILDREN:
        xml, volume_title, source = volume_data[stem]
        found = xml.xpath("/ThML/ThML.body//div1[@id=$identity]", identity=div1_id)
        if len(found) != 1 or not found[0].get("title"):
            raise PipelineError(f"{wid} assigned div1 child missing")
        child = {"work_id": wid, "source": {"path": source["path"], "bytes": source["bytes"],
                                             "sha256": source["sha256"]},
                 "div1_id": div1_id, "child_title": found[0].get("title"),
                 "volume_title": volume_title, "source_rights_label": "Public Domain"}
        children.append(child)
        work_rel = f"library/works/{wid}/work.json"
        state_rel = f"library/works/{wid}/state.json"
        work = json.loads(resolve_repo_path(root, work_rel).read_text(encoding="utf-8"))
        state = json.loads(resolve_repo_path(root, state_rel).read_text(encoding="utf-8"))
        config_rel = f"sources/structured-text/{wid}/config.json"
        config = json.loads(resolve_repo_path(root, config_rel).read_text(encoding="utf-8"))
        metadata_rel = f"metadata/source-evidence/catalog/{wid}.json"
        if (work["textual_forms"] or state["targets"] or work["title"] != config["title"]
                or config.get("source_hash") != "sha256:" + source["sha256"]):
            raise PipelineError(f"{wid} is no longer identity-only or config/source differs")
        locator = source["path"] + "#" + div1_id
        rows.append({
            "work_id": wid, "work": _ref(root, work_rel), "state": _ref(root, state_rel),
            "source_manifest": _ref(root, MANIFEST), "config": _ref(root, config_rel),
            "metadata_evidence": _ref(root, metadata_rel),
            "chrysostom_child_evidence": {"path": evidence_rel, "sha256": ""},
            "primary_source": source,
            "textual_form_id": f"{wid}-ccel-{stem}-retained-en",
            "edition_id": f"{wid}-ccel-{stem}-electronic",
            "acquisition_id": f"{wid}-ccel-{stem}-acquired",
            "edition_title": f"CCEL electronic witness of {volume_title}",
            "provider": "Christian Classics Ethereal Library",
            "url": config["source_url"], "language": "en", "media_type": "application/xml",
            "source_scope": f"Complete acquired XML volume {source['path']}; work-specific div1 locator {locator} is recorded in edition.containing_source and does not establish accepted child text.",
            "containing_source": {"title": volume_title, "locator": locator,
                                  "evidence": [evidence_rel, metadata_rel, locator]},
            "warnings": [
                "The retained XML states Public Domain; CCEL permits parsing ThML but retains file and formatting rights. Publication rights require separate review.",
                "The inherited config edition statement and volume-level contributor credits do not settle this child's printed edition or contributor allocation.",
                "The legacy parser excluded footnotes; complete source-to-TEI accounting and acceptance remain separate work.",
            ],
        })
    evidence = {"contract": "ocd-chrysostom-seven-child-scope-v1",
                "source_manifest": _ref(root, MANIFEST), "profile": _ref(root, PROFILE),
                "children": sorted(children, key=lambda child: child["work_id"])}
    digest = hashlib.sha256(canonical_bytes(evidence)).hexdigest()
    for row in rows:
        row["chrysostom_child_evidence"]["sha256"] = digest
    packet = {"contract": "ocd-library-sidecar-batch-v1",
              "entries": sorted(rows, key=lambda row: row["work_id"])}
    return evidence, packet


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--packet", type=Path, required=True)
    args = parser.parse_args()
    root = args.repository_root.resolve()
    evidence_rel = args.evidence.resolve().relative_to(root).as_posix()
    evidence, packet = prepare(root, evidence_rel)
    if args.evidence.exists() or args.packet.exists():
        raise PipelineError("Chrysostom evidence or packet already exists")
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.packet.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_bytes(canonical_bytes(evidence))
    args.packet.write_bytes(canonical_bytes(packet))
    print(f"prepared {len(packet['entries'])} Chrysostom child-bound rows")


if __name__ == "__main__":
    main()
