"""Audit and stage four retained TCP XML witnesses as library acquisitions."""

from __future__ import annotations

import argparse
import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError, load_json, sha256_file, write_json
from ocd_kernel.library.identities import load_work, validate_identity_update, validate_record
from ocd_kernel.library.state import load_state
from ocd_kernel.tei.install_accepted import _io_path


CONTRACT = "ocd-direct-tcp-four-source-packet-v1"
PLAN = "plans/2026-09-22-source-preflight"
SOURCES = {
    "hammon-address-to-the-negroes-of-new-york": ("master-2/15", "N15943", "evans"),
    "locke-reasonableness-christianity": ("master-4/28", "A48888", "eebo"),
    "marrant-prince-hall-african-lodge-sermon": ("master-2/15", "N17016", "evans"),
    "stillingfleet-origines-sacrae": ("master-4/28", "A61580", "eebo"),
}
RIGHTS = (
    "The retained TCP header labels its keyboarded and encoded Phase I text CC0 1.0 "
    "Universal and requests credit to the original source. The commercial page images "
    "are not included. Source accounting does not establish rights review or publication clearance."
)


def _ref(root: Path, relative: str) -> dict[str, Any]:
    path = resolve_repo_path(root, relative)
    if not _io_path(path).is_file():
        raise PipelineError(f"missing source evidence: {relative}")
    return {"path": relative, "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def _source_identity(root: Path, source: dict[str, Any], source_id: str) -> dict[str, str]:
    path = resolve_repo_path(root, source["path"])
    try:
        tree = etree.parse(str(_io_path(path)), etree.XMLParser(resolve_entities=False, no_network=True))
    except (OSError, etree.XMLSyntaxError) as exc:
        raise PipelineError(f"invalid retained TCP XML {source['path']}: {exc}") from exc
    ns = {"tei": "http://www.tei-c.org/ns/1.0"}
    if tree.getroot().tag != "{http://www.tei-c.org/ns/1.0}TEI":
        raise PipelineError(f"unexpected TCP XML root: {source['path']}")
    header = tree.xpath("/tei:TEI/tei:teiHeader/tei:fileDesc", namespaces=ns)
    title = tree.xpath("/tei:TEI/tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title", namespaces=ns)
    author = tree.xpath("/tei:TEI/tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:author", namespaces=ns)
    ids = tree.xpath("/tei:TEI/tei:teiHeader/tei:fileDesc/tei:publicationStmt/tei:idno", namespaces=ns)
    text = tree.xpath("/tei:TEI/tei:text", namespaces=ns)
    credit = tree.xpath("/tei:TEI/tei:teiHeader/tei:encodingDesc/tei:editorialDecl//tei:p", namespaces=ns)
    if (len(header) != 1 or len(title) != 1 or len(author) != 1 or len(text) != 1
            or len([node for node in ids if node.get("type") == "DLPS" and "".join(node.itertext()).strip() == source_id]) != 1
            or not any("due credit and attribution" in " ".join(node.itertext()) for node in credit)):
        raise PipelineError(f"TCP XML identity or credit request differs: {source['path']}")
    source_title = " ".join(" ".join(title[0].itertext()).split())
    source_author = " ".join(" ".join(author[0].itertext()).split())
    if not source_title or not source_author:
        raise PipelineError(f"TCP XML title missing: {source['path']}")
    return {"source_title": source_title, "source_author": source_author, "tcp_id": source_id}


def audit(root: Path) -> dict[str, Any]:
    """Compute a frozen packet from current identities, source bytes, and rights evidence."""
    root = root.resolve()
    entries = []
    for wid, (lane, source_id, family) in SOURCES.items():
        work_ref = _ref(root, f"library/works/{wid}/work.json")
        state_ref = _ref(root, f"library/works/{wid}/state.json")
        work = load_work(root / work_ref["path"])
        state = load_state(root / state_ref["path"])
        source = _ref(root, f"raw/clean-ready-acquisition-to-tei/{lane}/{wid}/{source_id}.xml")
        if (work["work_id"] != wid or state["work_id"] != wid
                or work["textual_forms"] or state["targets"] or source["path"] not in work["evidence"]):
            raise PipelineError(f"{wid} identity or retained source evidence differs")
        identity = _source_identity(root, source, source_id)
        source_readme = _ref(root, f"sources/structured-text/{wid}/README.md")
        raw_root = f"raw/clean-ready-acquisition-to-tei/{lane}/{wid}"
        raw_rights = _ref(root, raw_root + ("/LICENSE.CC0-1.0.txt" if family == "evans" else "/Texts-LICENSE"))
        refs = [source_readme, raw_rights]
        if family == "evans":
            manifest_ref = _ref(root, f"sources/structured-text/{wid}/{wid}.source-manifest.json")
            policy_ref = _ref(root, f"sources/structured-text/{wid}/{wid}.validation-policy.json")
            manifest, policy = load_json(root / manifest_ref["path"]), load_json(root / policy_ref["path"])
            primary = [item for item in manifest.get("authorities", []) if item.get("role") == "primary-source"]
            provenance = policy["provenance"]["source"]
            if (len(primary) != 1 or any(primary[0].get(key) != source[key] for key in ("path", "bytes", "sha256"))
                    or provenance.get("download_url", "").split("/")[-1] != f"{source_id}.xml"
                    or provenance.get("sha256") != source["sha256"]
                    or provenance.get("bytes") != source["bytes"]):
                raise PipelineError(f"{wid} Evans manifest or policy does not bind exact source")
            url = provenance["download_url"]
            refs.extend([manifest_ref, policy_ref])
        else:
            config_ref = _ref(root, f"sources/structured-text/{wid}/config.json")
            config = load_json(root / config_ref["path"])
            if (config.get("resource_id") != wid or config.get("source_file") != source["path"]
                    or config.get("source_hash") != "sha256:" + source["sha256"]
                    or config.get("tcp_id") != source_id + ".0001.001"):
                raise PipelineError(f"{wid} EEBO config does not bind exact source")
            url = config["source_url"]
            refs.append(config_ref)
        if not url.startswith(f"https://raw.githubusercontent.com/textcreationpartnership/{source_id}/"):
            raise PipelineError(f"{wid} source URL does not bind TCP repository")
        metadata = [item for item in work["evidence"] if item.startswith("metadata/source-evidence/lanes/")]
        if len(metadata) != 1:
            raise PipelineError(f"{wid} source metadata evidence set differs")
        metadata_ref = _ref(root, metadata[0])
        if ("CC0" not in _io_path(root / source_readme["path"]).read_text(encoding="utf-8")
                or "credit" not in _io_path(root / source_readme["path"]).read_text(encoding="utf-8").lower()):
            raise PipelineError(f"{wid} TCP rights or credit README differs")
        entries.append({"work_id": wid, "work": work_ref, "state": state_ref,
                        "source": source, "source_identity": identity, "source_url": url,
                        "source_family": family, "source_evidence": refs,
                        "metadata_evidence": metadata_ref})
    return {"contract": CONTRACT, "entries": entries}


def _notice(row: dict[str, Any], packet_rel: str, packet_sha: str) -> str:
    source = row["source"]
    return "\n".join([
        f"# Source and credit — {row['source_identity']['source_title']}", "",
        f"The retained text source is the TCP TEI P5 XML at `{source['path']}` ",
        f"(SHA-256 `{source['sha256']}`). The source identifier is {row['source_identity']['tcp_id']}.", "",
        f"The source header names {row['source_identity']['source_author']} as author.",
        "Credit the Text Creation Partnership and the original source when using this electronic witness.",
        f"Pinned source: {row['source_url']}", "",
        "TCP makes the keyboarded and encoded Phase I text available under CC0 1.0 Universal.",
        "The retained TCP header also requests due credit and attribution to its original source.",
        "The commercial page images were not acquired or redistributed, and this text license makes no claim about them.", "",
        f"Source packet: `{packet_rel}` (SHA-256 `{packet_sha}`).",
        f"Source-local rights and provenance: `{row['source_evidence'][0]['path']}`.",
        "This acquired-source record does not establish faithful TEI acceptance, rights clearance, or publication authorization.", "",
    ])


def stage(root: Path, packet_path: Path, destination: Path, *, timestamp: str | None = None) -> dict[str, Any]:
    root = root.resolve()
    packet = load_json(packet_path)
    if packet != audit(root):
        raise PipelineError("four-work TCP packet differs from current retained evidence")
    packet_rel = packet_path.resolve().relative_to(root).as_posix()
    packet_sha = sha256_file(packet_path)
    timestamp = timestamp or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    proposed: list[tuple[str, dict[str, Any] | str, str | None]] = []
    for row in packet["entries"]:
        wid, source = row["work_id"], row["source"]
        work = load_work(root / row["work"]["path"])
        state = load_state(root / row["state"]["path"])
        form_id = f"{wid}-tcp-retained-en"
        edition_id = f"{wid}-tcp-electronic"
        acquisition_id = f"{wid}-tcp-acquired"
        base = f"library/works/{wid}/forms/{form_id}/editions/{edition_id}"
        acq_rel = f"{base}/acquisitions/{acquisition_id}.json"
        notice_rel = f"library/works/{wid}/SOURCE_CREDIT.md"
        if (root / acq_rel).exists() or (root / notice_rel).exists():
            raise PipelineError(f"{wid} already has a TCP acquisition or source notice")
        work_new, state_new = copy.deepcopy(work), copy.deepcopy(state)
        work_new["textual_forms"].append({"textual_form_id": form_id, "language": "en",
            "editions": [{"edition_id": edition_id, "title": row["source_identity"]["source_title"],
                          "language": "en", "acquisition_ids": [acquisition_id]}]})
        evidence = [packet_rel, source["path"], notice_rel, acq_rel,
                    row["metadata_evidence"]["path"],
                    *(ref["path"] for ref in row["source_evidence"])]
        for relative in evidence:
            if relative not in work_new["evidence"]:
                work_new["evidence"].append(relative)
        validate_identity_update(work, work_new)
        validate_record("work", work_new, context=f"{wid} proposed work")
        scope = (f"Complete retained TCP TEI P5 electronic witness {row['source_identity']['tcp_id']} "
                 f"for {row['source_identity']['source_title']}. This is source accounting, not "
                 "accepted TEI or publication clearance; image scans are not part of the acquisition.")
        acquisition = {"schema_version": "2.0", "acquisition_id": acquisition_id,
            "edition_id": edition_id, "provider": "Text Creation Partnership", "url": row["source_url"],
            "route": "born-digital", "retained_files": [{"path": source["path"],
            "bytes": source["bytes"], "sha256": source["sha256"], "media_type": "application/xml",
            "scope": scope}], "source_path": source["path"], "source_bytes": source["bytes"],
            "source_sha256": source["sha256"], "source_scope": scope,
            "warnings": [RIGHTS, "The canonical work label is shorter than the full retained TCP title; edition title follows the XML header."]}
        validate_record("acquisition", acquisition, context=f"{wid} proposed acquisition")
        for target_id, target_type in ((acquisition_id, "acquisition"), (edition_id, "edition")):
            state_new["targets"].append({"target_id": target_id, "target_type": target_type,
                "stage": "acquired", "updated_at": timestamp, "evidence": evidence})
        validate_record("state", state_new, context=f"{wid} proposed state")
        proposed.extend([(row["work"]["path"], work_new, row["work"]["sha256"]),
                         (row["state"]["path"], state_new, row["state"]["sha256"]),
                         (acq_rel, acquisition, None), (notice_rel, _notice(row, packet_rel, packet_sha), None)])
    if destination.exists():
        raise PipelineError(f"refusing existing stage destination: {destination}")
    _io_path(destination).mkdir(parents=True)
    files = []
    for relative, value, before in proposed:
        target = _io_path(destination / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(value, str):
            target.write_text(value, encoding="utf-8")
        else:
            write_json(target, value)
        files.append({"path": relative, "before_sha256": before,
                      "proposed_sha256": sha256_file(target)})
    receipt = {"contract": "ocd-direct-tcp-four-stage-v1", "packet_sha256": packet_sha,
               "entries": list(SOURCES), "files": sorted(files, key=lambda item: item["path"])}
    write_json(_io_path(destination / "receipt.json"), receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--audit", action="store_true")
    args = parser.parse_args()
    if args.audit:
        if args.packet.exists():
            raise PipelineError(f"refusing existing packet: {args.packet}")
        write_json(args.packet, audit(args.repository_root))
        print(json.dumps({"packet": str(args.packet), "sha256": sha256_file(args.packet)}, sort_keys=True))
    else:
        if args.destination is None:
            parser.error("--destination is required unless --audit")
        receipt = stage(args.repository_root, args.packet, args.destination)
        print(json.dumps({"stage": str(args.destination), "works": len(receipt["entries"]),
                          "files": len(receipt["files"])}, sort_keys=True))


if __name__ == "__main__":
    main()


