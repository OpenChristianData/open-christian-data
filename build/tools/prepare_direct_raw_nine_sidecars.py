"""Audit and stage nine retained Gutenberg works without changing canonical sidecars."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError, load_json, sha256_file, write_json
from ocd_kernel.library.acquisitions import source_member_set_bytes
from ocd_kernel.library.identities import load_work, validate_identity_update, validate_record
from ocd_kernel.library.state import load_state
from ocd_kernel.tei.install_accepted import _io_path


PLAN = "plans/2026-09-22-source-preflight"
CONTRACT = "ocd-direct-raw-nine-source-packet-v1"
SERIAL = "american-missionary"
SINGLES = {
    "barclay-apology-true-christian-divinity": ("master-4/28", "56487-h.htm", "source_hash", "source_url", "text/html", 56487,
        "Electronic production: Emmanuel Ackerman and the Online Distributed Proofreading Team. The retained README also credits HathiTrust Digital Library, Google, and the University of Michigan Library as image providers."),
    "greenleaf-testimony-four-evangelists-1847": ("master-4/28", "34989-tei.tei", "source_hash", "source_url", "application/xml", 34989,
        "Electronic production: Dianna Adair, Jeff G., David King, and the Online Distributed Proofreading Team."),
    "lightfoot-essays-supernatural-religion-1893": ("master-4/28", "pg18191-images.html", "source_hash", "source_url", "text/html", 18191,
        "Electronic transcription: Project Gutenberg Distributed Proofreaders."),
    "missionary-survey": ("master-5/35", "pg13360.txt", "text_authority_sha256", "text_authority_url", "text/plain", 13360,
        "Electronic production: Ted Garvin, Josephine Paolucci, and the Online Distributed Proofreading Team."),
    "modern-scepticism-christian-evidence-society-1871": ("master-4/28", "42957-h.htm", "source_hash", "source_url", "text/html", 42957,
        "Electronic production: Charlene Taylor, Marilynda Fraser-Cunliffe, Charlie Howard, and the Online Distributed Proofreading Team."),
    "ports-of-entry-missionary-herald": ("master-5/35", "pg55955-images.html", "html_authority_sha256", "html_authority_url", "text/html", 55955,
        "Electronic production: ellinora, Larry B. Harrison, and the Online Distributed Proofreading Team."),
    "singmaster-story-of-lutheran-missions": ("master-5/35", "pg55819-images.html", "html_authority_sha256", "html_authority_url", "text/html", 55819,
        "Electronic production: David Edwards, Barry Abrahamsen, and the Online Distributed Proofreading Team."),
    "turton-truth-of-christianity-1919": ("master-4/28", "42460-h.htm", "source_hash", "source_url", "text/html", 42460,
        "Electronic production: Heiko Evermann, Quentin Johnson, Fox in the Stars, and the Online Distributed Proofreading Team."),
}
WORKS = (SERIAL, *SINGLES)
RIGHTS = ("Project Gutenberg identifies this underlying work as public domain in the USA. "
          "Its license and trademark conditions apply to distribution of the Gutenberg eBook or "
          "material retaining its identification; other jurisdictions require separate review. "
          "Source accounting does not grant rights clearance or publication authorization.")


def _ref(root: Path, relative: str) -> dict[str, Any]:
    path = resolve_repo_path(root, relative)
    if not _io_path(path).is_file():
        raise PipelineError(f"missing retained file: {relative}")
    return {"path": relative, "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def _inventory(root: Path, raw_roots: list[str]) -> list[dict[str, Any]]:
    result = []
    for relative_root in raw_roots:
        directory = resolve_repo_path(root, relative_root)
        if not directory.is_dir():
            raise PipelineError(f"missing retained raw directory: {relative_root}")
        files = sorted((path for path in directory.rglob("*") if path.is_file()),
                       key=lambda path: path.relative_to(directory).as_posix())
        if not files:
            raise PipelineError(f"empty retained raw directory: {relative_root}")
        for path in files:
            relative = relative_root + "/" + path.relative_to(directory).as_posix()
            item = _ref(root, relative)
            if path.suffix.lower() == ".zip":
                try:
                    with zipfile.ZipFile(_io_path(path)) as archive:
                        members = []
                        for member in archive.infolist():
                            if member.is_dir():
                                continue
                            name = Path(member.filename)
                            if name.is_absolute() or ".." in name.parts:
                                raise PipelineError(f"unsafe archive member: {relative}::{member.filename}")
                            content = archive.read(member)
                            members.append({"name": member.filename, "bytes": len(content),
                                            "crc32": member.CRC,
                                            "sha256": hashlib.sha256(content).hexdigest()})
                        item["archive_members"] = members
                except (OSError, zipfile.BadZipFile, KeyError) as exc:
                    raise PipelineError(f"invalid retained package {relative}: {exc}") from exc
            result.append(item)
    return result


def _serial_editions(root: Path) -> list[dict[str, Any]]:
    result = []
    for number, year in ((36, 1882), (37, 1883)):
        raw_root = f"raw/clean-ready-acquisition-to-tei/master-5/35/american-missionary-volume-{number}-{year}"
        directory = resolve_repo_path(root, raw_root)
        sources = []
        packages = []
        for folder in sorted(directory.glob("pg*")):
            if not folder.is_dir():
                continue
            ebook = folder.name
            source_rel = f"{raw_root}/{ebook}/{ebook}.txt"
            package_rel = f"{raw_root}/{ebook}/{ebook}-h.zip"
            source = resolve_repo_path(root, source_rel)
            header = source.read_text(encoding="utf-8-sig", errors="replace")[:700]
            match = re.search(r"Volume\s+(\d+),\s+No\.\s+(\d+),\s+([^\r\n]+)", header)
            if match is None or int(match.group(1)) != number or str(year) not in match.group(3):
                raise PipelineError(f"{source_rel} does not identify the retained volume/year")
            sources.append((int(match.group(2)), _ref(root, source_rel), f"https://www.gutenberg.org/ebooks/{ebook[2:]}"))
            packages.append(_ref(root, package_rel))
        sources.sort(key=lambda row: row[0])
        if [row[0] for row in sources] != list(range(1, 13)) or len(packages) != 12:
            raise PipelineError(f"American Missionary volume {number} does not contain issues 1-12")
        result.append({"edition_id": f"american-missionary-volume-{number}-{year}-gutenberg-electronic",
                       "title": f"The American Missionary, volume {number} ({year}), monthly issues 1-12",
                       "sources": [row[1] for row in sources], "packages": packages,
                       "source_urls": [row[2] for row in sources], "media_type": "text/plain",
                       "source_scope": f"The complete retained set of 12 monthly issues for volume {number} ({year}); this does not claim completeness of other years or the whole serial."})
    return result


def audit(root: Path) -> dict[str, Any]:
    """Recompute all retained-file and source-config evidence from the current checkout."""
    root = root.resolve()
    entries = []
    for wid in WORKS:
        work_rel = f"library/works/{wid}/work.json"
        state_rel = f"library/works/{wid}/state.json"
        work = load_work(root / work_rel)
        state = load_state(root / state_rel)
        if work["work_id"] != wid or state["work_id"] != wid or work["textual_forms"] or state["targets"]:
            raise PipelineError(f"{wid} is not identity-only")
        metadata = [item for item in work["evidence"] if item.startswith("metadata/source-evidence/lanes/")]
        if len(metadata) != (2 if wid == SERIAL else 1):
            raise PipelineError(f"{wid} metadata lane evidence set differs")
        row: dict[str, Any] = {"work_id": wid, "work": _ref(root, work_rel),
                               "state": _ref(root, state_rel),
                               "metadata_evidence": [_ref(root, path) for path in metadata]}
        if wid == SERIAL:
            raw_roots = [f"raw/clean-ready-acquisition-to-tei/master-5/35/american-missionary-volume-{volume}-{year}"
                         for volume, year in ((36, 1882), (37, 1883))]
            row["config"] = None
            row["source_readme"] = None
            row["credits"] = "Electronic production of all 24 retained issues: Joshua Hutchinson, KarenD, and the Online Distributed Proofreading Team."
            row["editions"] = _serial_editions(root)
        else:
            lane, filename, hash_key, url_key, media_type, ebook_id, credits = SINGLES[wid]
            raw_root = f"raw/clean-ready-acquisition-to-tei/{lane}/{wid}"
            raw_roots = [raw_root]
            config_rel = f"sources/structured-text/{wid}/config.json"
            config = load_json(root / config_rel)
            if (config.get("resource_id", config.get("slug")) != wid
                    or config.get("gutenberg_id", config.get("project_gutenberg_id")) != ebook_id):
                raise PipelineError(f"{wid} config identity or Gutenberg ID differs")
            source = _ref(root, f"{raw_root}/{filename}")
            if (config.get("source_file", source["path"]) != source["path"]
                    or config.get(hash_key) != (f"sha256:{source['sha256']}" if hash_key == "source_hash" else source["sha256"])):
                raise PipelineError(f"{wid} config source/hash differs")
            readme_rel = f"sources/structured-text/{wid}/README.md"
            row["config"] = _ref(root, config_rel)
            row["source_readme"] = _ref(root, readme_rel) if (root / readme_rel).is_file() else None
            row["credits"] = credits
            row["editions"] = [{"edition_id": f"{wid}-gutenberg-electronic",
                                "title": f"Project Gutenberg electronic witness {ebook_id}",
                                "sources": [source], "packages": [],
                                "source_urls": [config[url_key], config.get("source_landing_url", config.get("landing_url"))],
                                "media_type": media_type,
                                "source_scope": f"Complete retained electronic source file for Project Gutenberg eBook {ebook_id}; alternate witnesses and packages are separately inventoried."}]
            if (not all(isinstance(url, str) and url.startswith("https://www.gutenberg.org/")
                        for url in row["editions"][0]["source_urls"])):
                raise PipelineError(f"{wid} missing authoritative Gutenberg source URLs")
        row["raw_roots"] = raw_roots
        row["retained_inventory"] = _inventory(root, raw_roots)
        inventory_by_path = {item["path"]: item for item in row["retained_inventory"]}
        for edition in row["editions"]:
            if wid != SERIAL:
                edition["packages"] = [item for item in row["retained_inventory"]
                                       if item["path"].lower().endswith(".zip")]
            if any(inventory_by_path.get(item["path"], {}).get("sha256") != item["sha256"]
                   or inventory_by_path.get(item["path"], {}).get("bytes") != item["bytes"]
                   for item in edition["sources"] + edition["packages"]):
                raise PipelineError(f"{wid} source or package omitted from retained inventory")
        entries.append(row)
    return {"contract": CONTRACT, "entries": entries}


def _credit(row: dict[str, Any], packet_rel: str, packet_sha: str) -> str:
    lines = [f"# Source and credit — {row['work_id']}", "", row["credits"], "", RIGHTS, "",
             "The following retained files are the text sources. ZIP files are acquisition packages, not text sources.", ""]
    for edition in row["editions"]:
        lines.extend([f"## {edition['title']}", "", edition["source_scope"], "", "Text sources, in order:", ""])
        lines.extend(f"- {item['path']} — SHA-256 {item['sha256']}" for item in edition["sources"])
        lines.extend(["", "Package evidence:", ""])
        lines.extend(f"- {item['path']} — SHA-256 {item['sha256']}" for item in edition["packages"])
        if not edition["packages"]:
            lines.append("- No ZIP package is required to identify this retained text source.")
        lines.extend(["", "Official source records:", ""])
        lines.extend(f"- {url}" for url in edition["source_urls"])
        if len(edition["sources"]) > 1:
            lines.extend(["", "The acquisition URL names only the lead issue; the complete retained volume requires every listed issue and source URL."])
        lines.append("")
    lines.extend(["Evidence pins:", "", f"- Source packet: {packet_rel} — SHA-256 {packet_sha}"])
    for label, reference in (("Source config", row["config"]), ("Source-local README", row["source_readme"])):
        if reference is not None:
            lines.append(f"- {label}: {reference['path']} — SHA-256 {reference['sha256']}")
    lines.extend(f"- Metadata evidence: {item['path']} — SHA-256 {item['sha256']}"
                 for item in row["metadata_evidence"])
    lines.extend(["", "This acquired-source record does not establish faithful TEI acceptance, rights clearance, or publication authorization.", ""])
    return "\n".join(lines)


def stage(root: Path, packet_path: Path, destination: Path, *, timestamp: str | None = None) -> dict[str, Any]:
    root = root.resolve()
    packet = load_json(packet_path)
    if packet != audit(root):
        raise PipelineError("nine-work source packet differs from current retained evidence")
    packet_rel = packet_path.resolve().relative_to(root).as_posix()
    packet_sha = sha256_file(packet_path)
    timestamp = timestamp or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    proposed: list[tuple[str, dict[str, Any] | str, str | None]] = []
    for row in packet["entries"]:
        wid = row["work_id"]
        work_rel, state_rel = row["work"]["path"], row["state"]["path"]
        work, state = load_work(root / work_rel), load_state(root / state_rel)
        form_id = f"{wid}-gutenberg-retained-en"
        revised_work, revised_state = copy.deepcopy(work), copy.deepcopy(state)
        credit_rel = f"library/works/{wid}/SOURCE_CREDIT.md"
        if (root / credit_rel).exists():
            raise PipelineError(f"{wid} already has a source credit notice")
        form = {"textual_form_id": form_id, "language": "en", "editions": []}
        evidence = [packet_rel, credit_rel, *[ref["path"] for ref in row["metadata_evidence"]]]
        if row["config"]:
            evidence.append(row["config"]["path"])
        if row["source_readme"]:
            evidence.append(row["source_readme"]["path"])
        for edition in row["editions"]:
            edition_id = edition["edition_id"]
            acquisition_id = f"{edition_id}-acquired"
            base = f"library/works/{wid}/forms/{form_id}/editions/{edition_id}"
            acq_rel = f"{base}/acquisitions/{acquisition_id}.json"
            member_set_rel = f"{base}/source-member-set.json" if len(edition["sources"]) > 1 else None
            if (root / acq_rel).exists() or (member_set_rel and (root / member_set_rel).exists()):
                raise PipelineError(f"{wid} already has the proposed acquisition")
            form["editions"].append({"edition_id": edition_id, "title": edition["title"],
                                     "language": "en", "acquisition_ids": [acquisition_id]})
            scope = edition["source_scope"] + " ZIPs are package evidence, not text sources. "
            if member_set_rel:
                scope += "All issue URLs: " + "; ".join(edition["source_urls"]) + ". The singular acquisition URL is the lead issue only."
            else:
                scope += "The primary URL identifies the direct source file; the second URL is its Gutenberg catalog record."
            retained = [{"path": ref["path"], "bytes": ref["bytes"], "sha256": ref["sha256"],
                         "media_type": edition["media_type"], "scope": scope}
                        for ref in edition["sources"]]
            if not member_set_rel:
                retained.extend({"path": ref["path"], "bytes": ref["bytes"], "sha256": ref["sha256"],
                                 "media_type": "application/zip", "scope": "Retained acquisition package, not the text source."}
                                for ref in edition["packages"])
            acquisition: dict[str, Any] = {"schema_version": "2.0", "acquisition_id": acquisition_id,
                "edition_id": edition_id, "provider": "Project Gutenberg", "url": edition["source_urls"][0],
                "route": "born-digital", "retained_files": retained, "source_scope": scope,
                "warnings": [RIGHTS] + (["The 12 monthly issues are the bounded retained volume; the lead issue URL alone is incomplete."] if member_set_rel else [])}
            if member_set_rel:
                acquisition["source_kind"] = "retained-member-set"
                acquisition["source_path"] = member_set_rel
                content = source_member_set_bytes(acquisition)
                acquisition["source_bytes"] = len(content)
                acquisition["source_sha256"] = hashlib.sha256(content).hexdigest()
                proposed.append((member_set_rel, json.loads(content), None))
            else:
                source = edition["sources"][0]
                acquisition.update(source_path=source["path"], source_bytes=source["bytes"],
                                   source_sha256=source["sha256"])
            validate_record("acquisition", acquisition, context=f"{wid} proposed acquisition")
            proposed.append((acq_rel, acquisition, None))
            target_evidence = [packet_rel, credit_rel, acq_rel,
                               *(ref["path"] for ref in edition["sources"]),
                               *(ref["path"] for ref in edition["packages"])]
            if member_set_rel:
                target_evidence.append(member_set_rel)
            for target_id, kind in ((acquisition_id, "acquisition"), (edition_id, "edition")):
                revised_state["targets"].append({"target_id": target_id, "target_type": kind,
                                                  "stage": "acquired", "updated_at": timestamp,
                                                  "evidence": target_evidence})
            evidence.extend([acq_rel, *target_evidence])
        revised_work["textual_forms"].append(form)
        for path in evidence:
            if path not in revised_work["evidence"]:
                revised_work["evidence"].append(path)
        validate_identity_update(work, revised_work)
        validate_record("work", revised_work, context=f"{wid} proposed work")
        validate_record("state", revised_state, context=f"{wid} proposed state")
        proposed.extend([(work_rel, revised_work, row["work"]["sha256"]),
                         (state_rel, revised_state, row["state"]["sha256"]),
                         (credit_rel, _credit(row, packet_rel, packet_sha), None)])
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
    receipt = {"contract": "ocd-direct-raw-nine-stage-v1", "packet_sha256": packet_sha,
               "entries": [row["work_id"] for row in packet["entries"]],
               "files": sorted(files, key=lambda item: item["path"])}
    write_json(_io_path(destination / "receipt.json"), receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--audit", action="store_true", help="write exact packet at --packet; no stage")
    args = parser.parse_args()
    if args.audit:
        if args.packet.exists():
            raise PipelineError(f"refusing existing packet: {args.packet}")
        write_json(args.packet, audit(args.repository_root))
        print(json.dumps({"packet": str(args.packet), "sha256": sha256_file(args.packet)}, sort_keys=True))
    else:
        if args.destination is None:
            parser.error("--destination is required unless --audit")
        result = stage(args.repository_root, args.packet, args.destination)
        print(json.dumps({"stage": str(args.destination), "works": len(result["entries"]),
                          "files": len(result["files"])}, sort_keys=True))


if __name__ == "__main__":
    main()
