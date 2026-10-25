"""Stage four exact Gutenberg HTML acquisitions; never install them."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError, load_json, sha256_file, write_json
from ocd_kernel.library.acquisitions import source_member_set_bytes
from ocd_kernel.library.identities import load_work, validate_identity_update, validate_record
from ocd_kernel.library.state import load_state
from ocd_kernel.tei.install_accepted import _io_path


CONTRACT = "ocd-direct-raw-four-sidecar-packet-v1"
WORKS = (
    "aquinas-summa-theologica-four-parts",
    "newman-development-christian-doctrine",
    "newman-grammar-of-assent",
    "teresa-life-of-st-teresa-of-jesus",
)


def _bound(root: Path, reference: dict[str, str], label: str) -> tuple[Path, str]:
    if not isinstance(reference, dict) or set(reference) != {"path", "sha256"}:
        raise PipelineError(f"{label} needs exact path and SHA-256")
    relative = reference["path"]
    path = resolve_repo_path(root, relative)
    if not path.is_file() or sha256_file(path) != reference["sha256"]:
        raise PipelineError(f"{label} missing or changed: {relative}")
    return path, relative


def _original_member_name(item: dict[str, Any]) -> str:
    return item.get("path", item.get("name"))


def _verify_extraction(root: Path, row: dict[str, Any], work: dict[str, Any],
                       evidence: dict[str, Any], extraction_rel: str) -> tuple[list[dict[str, Any]], list[str]]:
    wid = work["work_id"]
    source_path, source_rel = _bound(root, row["config"], f"{wid} config")
    config = load_json(source_path)
    receipt_path, receipt_rel = _bound(root, row["original_receipt"], f"{wid} original receipt")
    _, readme_rel = _bound(root, row["source_readme"], f"{wid} source README")
    original = load_json(receipt_path)
    if (source_rel != evidence["config_path"] or row["config"]["sha256"] != evidence["config_sha256"]
            or readme_rel != f"sources/structured-text/{wid}/README.md"
            or row.get("source_urls") != evidence.get("source_urls")
            or row.get("source_urls") != config.get("source_urls", [config["source_url"]])
            or receipt_rel != evidence["original_receipt_path"]
            or row["original_receipt"]["sha256"] != evidence["original_receipt_sha256"]
            or config.get("resource_id") != wid or config.get("source_url") != row.get("url")
            or row.get("provider") != "Project Gutenberg" or row.get("language") != config.get("language")
            or original.get("slug", wid) != wid):
        raise PipelineError(f"{wid} historical source identity or receipt binding differs")
    members = evidence["members"]
    primary = [member for member in members if member["role"] == "primary-text"]
    support = [member for member in members if member["role"] == "support-image"]
    packages = list(dict.fromkeys(member["package_path"] for member in members))
    if (row.get("primary_sources") != [member["source_path"] for member in primary]
            or row.get("support_files") != [member["source_path"] for member in support]
            or row.get("packages") != packages or set(config["source_members"]) != {member["member_name"] for member in members}
            or len(primary) != (4 if wid == WORKS[0] else 1)
            or len(packages) != (4 if wid == WORKS[0] else 1)
            or len(support) != len(packages)):
        raise PipelineError(f"{wid} declared package, source, or support set differs")
    if wid == WORKS[0]:
        expected_ids = (17611, 17897, 18755, 19950)
        components = original.get("components")
        if (not isinstance(components, list)
                or tuple(part.get("project_gutenberg_id") for part in components) != expected_ids
                or [part.get("landing_url") for part in components] != row["source_urls"]
                or [member["member_name"] for member in primary]
                != [f"pg{value}-images.html" for value in expected_ids]
                or len(original["retained_files"]) != 24):
            raise PipelineError(f"{wid} four ordered components or historical envelope differ")
    expected_archive = original["archive_members"]
    if {(_original_member_name(item), item["bytes"], item["sha256"]) for item in expected_archive} != {
            (item["member_name"], item["bytes"], item["sha256"]) for item in members}:
        raise PipelineError(f"{wid} historical archive inventory differs")
    for package_rel in packages:
        matching = [item for item in members if item["package_path"] == package_rel]
        expected_package = next((item for item in original["retained_files"]
                                 if package_rel.endswith("/" + _original_member_name(item))), None)
        package_path = resolve_repo_path(root, package_rel)
        if (expected_package is None or not package_path.is_file()
                or package_path.stat().st_size != expected_package["bytes"]
                or sha256_file(package_path) != expected_package["sha256"]
                or any(item["package_bytes"] != expected_package["bytes"]
                       or item["package_sha256"] != expected_package["sha256"] for item in matching)):
            raise PipelineError(f"{wid} ZIP package differs: {package_rel}")
        with zipfile.ZipFile(_io_path(package_path)) as archive:
            infos = [info for info in archive.infolist() if not info.is_dir()]
            if [info.filename for info in infos] != [item["member_name"] for item in matching]:
                raise PipelineError(f"{wid} ZIP member order or names differ: {package_rel}")
            for info, item in zip(infos, matching, strict=True):
                name = info.filename
                parts = PurePosixPath(name).parts
                if (not name or name.startswith("/") or "\\" in name or ":" in name
                        or any(part in {"", ".", ".."} for part in parts)
                        or PurePosixPath(name).as_posix() != name):
                    raise PipelineError(f"{wid} unsafe ZIP member: {name}")
                content = archive.read(info)
                extracted = resolve_repo_path(root, item["source_path"])
                if (not extracted.is_file() or extracted.read_bytes() != content
                        or len(content) != item["bytes"]
                        or hashlib.sha256(content).hexdigest() != item["sha256"]
                        or f"{info.CRC:08x}" != item["member_crc32"]):
                    raise PipelineError(f"{wid} extracted member differs from ZIP: {name}")
        extracted_root = resolve_repo_path(root, str(PurePosixPath(package_rel).parent /
                                                "extracted" / PurePosixPath(package_rel).stem))
        observed = {path.relative_to(extracted_root).as_posix() for path in extracted_root.rglob("*") if path.is_file()}
        if observed != {item["member_name"] for item in matching}:
            raise PipelineError(f"{wid} extracted tree has unaccounted files: {package_rel}")
    scope = row.get("source_scope")
    if (not isinstance(scope, str) or not all(item["source_path"] in scope for item in primary)
            or not all(package in scope for package in packages)
            or "accepted TEI" not in scope or "publication clearance" not in scope
            or (wid == WORKS[0] and ("excludes the Supplement" not in scope
                                      or "lead component only" not in scope
                                      or not all(url in scope for url in row["source_urls"])))):
        raise PipelineError(f"{wid} source scope fails to distinguish text, package, and acceptance")
    if (not isinstance(row.get("warnings"), list) or not row["warnings"]
            or "public domain in the USA" not in row["warnings"][0]
            or (wid == WORKS[0] and "no Supplement" not in " ".join(row["warnings"]))):
        raise PipelineError(f"{wid} rights or completeness warning absent")
    if wid == WORKS[0]:
        retained = [{"path": item["source_path"], "bytes": item["bytes"], "sha256": item["sha256"],
                     "media_type": "text/html", "scope": f"Ordered source part {position} of four. {scope}"}
                    for position, item in enumerate(primary, 1)]
    else:
        retained = [{"path": primary[0]["source_path"], "bytes": primary[0]["bytes"],
                     "sha256": primary[0]["sha256"], "media_type": "text/html", "scope": scope}]
        for package_rel in packages:
            item = next(member for member in members if member["package_path"] == package_rel)
            retained.append({"path": package_rel, "bytes": item["package_bytes"],
                             "sha256": item["package_sha256"], "media_type": "application/zip",
                             "scope": "Retained acquisition package; not the text source."})
        for item in support:
            retained.append({"path": item["source_path"], "bytes": item["bytes"],
                             "sha256": item["sha256"],
                             "media_type": "image/jpeg" if item["member_name"].endswith(".jpg") else "image/png",
                             "scope": "Supporting cover image extracted from the acquisition package."})
    evidence_paths = [source_rel, receipt_rel, readme_rel, extraction_rel, *packages,
                      *(item["source_path"] for item in members)]
    return retained, evidence_paths



def _credit_document(row: dict[str, Any], evidence: dict[str, Any], extraction_ref: dict[str, str]) -> str:
    wid = row["work_id"]
    credits = {
        WORKS[0]: "The retained Gutenberg headers credit Sandra K. Perry. Parts I, II-II, and III also credit David McClamrock for corrections and supplementation.",
        WORKS[1]: "The retained Gutenberg header credits Curtis Weyant, Lisa Reigel, and the Online Distributed Proofreading Team.",
        WORKS[2]: "The retained acquisition receipt credits Delphine Lettau, David King, and the Online Distributed Proofreading Team at www.pgdp.net.",
        WORKS[3]: "The retained Gutenberg header credits Elizabeth T. Knuth.",
    }
    text = [
        f"# Source and credit — {row['edition_title']}",
        "",
        "The text source is the verified extracted Project Gutenberg HTML below, in this order:",
        "",
    ]
    text.extend(f"- {member['source_path']} — SHA-256 {member['sha256']}"
                for member in evidence["members"] if member["role"] == "primary-text")
    text.extend(["", "The ZIP files are retained acquisition packages; they are not the text source:", ""])
    packages = list(dict.fromkeys((member["package_path"], member["package_sha256"])
                                  for member in evidence["members"]))
    text.extend(f"- {path} — SHA-256 {digest}" for path, digest in packages)
    text.extend(["", credits[wid], "",
                 "Project Gutenberg describes the underlying work as public domain in the USA. "
                 "Its license and trademark terms (https://www.gutenberg.org/license) apply to redistribution "
                 "of the Project Gutenberg eBook or material retaining its identification; rights in other "
                 "jurisdictions require separate review. This notice does not grant publication clearance.", "",
                 "Official source records:", ""])
    text.extend(f"- {url}" for url in row["source_urls"])
    text.extend(["", "Evidence pins:", "",
                 f"- Original acquisition receipt: {row['original_receipt']['path']} — SHA-256 {row['original_receipt']['sha256']}",
                 f"- Extracted-source receipt: {extraction_ref['path']} — SHA-256 {extraction_ref['sha256']}",
                 f"- Source-local README: {row['source_readme']['path']} — SHA-256 {row['source_readme']['sha256']}",
                 ""])
    if wid == WORKS[0]:
        text.extend(["This electronic witness has four parts: I, I-II, II-II, and III. "
                     "The Supplement is absent and is outside this acquired source set. "
                     "The acquisition URL points only to the lead component; all four source records are listed above.", ""])
    return "\n".join(text)


def stage(root: Path, packet_path: Path, destination: Path, *, timestamp: str | None = None) -> dict[str, Any]:
    root = root.resolve()
    packet = load_json(packet_path)
    if packet.get("contract") != CONTRACT or set(packet) != {"contract", "extraction_receipt", "entries"}:
        raise PipelineError("invalid four-work sidecar packet contract")
    receipt_path, receipt_rel = _bound(root, packet["extraction_receipt"], "extraction receipt")
    extraction = load_json(receipt_path)
    evidence = extraction.get("works")
    entries = packet.get("entries")
    if (extraction.get("contract") != "ocd-direct-raw-four-extraction-v1"
            or not isinstance(evidence, list) or not isinstance(entries, list)
            or [item.get("work_id") for item in evidence] != list(WORKS)
            or [item.get("work_id") for item in entries] != list(WORKS)):
        raise PipelineError("four-work extraction or packet identity set differs")
    timestamp = timestamp or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    proposed: list[tuple[str, dict[str, Any] | str, str | None]] = []
    stage_entries = []
    for row, source_evidence in zip(entries, evidence, strict=True):
        wid = row["work_id"]
        work_path, work_rel = _bound(root, row["work"], f"{wid} work")
        state_path, state_rel = _bound(root, row["state"], f"{wid} state")
        if (work_rel != f"library/works/{wid}/work.json"
                or state_rel != f"library/works/{wid}/state.json"):
            raise PipelineError(f"{wid} work/state paths differ")
        work = load_work(work_path)
        state = load_state(state_path)
        if (work["work_id"] != wid or state["work_id"] != wid
                or work["textual_forms"] or state["targets"]):
            raise PipelineError(f"{wid} is not identity-only")
        retained, evidence_paths = _verify_extraction(root, row, work, source_evidence, receipt_rel)
        form_id = row["textual_form_id"]
        edition_id = row["edition_id"]
        acquisition_id = row["acquisition_id"]
        if (form_id != f"{wid}-gutenberg-retained-en" or edition_id != f"{wid}-gutenberg-electronic"
                or acquisition_id != f"{wid}-gutenberg-acquired"):
            raise PipelineError(f"{wid} form, edition, or acquisition ID differs")
        edition_dir = f"library/works/{wid}/forms/{form_id}/editions/{edition_id}"
        acquisition_rel = f"{edition_dir}/acquisitions/{acquisition_id}.json"
        member_set_rel = f"{edition_dir}/source-member-set.json" if wid == WORKS[0] else None
        credit_rel = f"library/works/{wid}/SOURCE_CREDIT.md"
        if resolve_repo_path(root, credit_rel).exists():
            raise PipelineError(f"{wid} already has a work-local source notice")
        if resolve_repo_path(root, acquisition_rel).exists() or (member_set_rel and resolve_repo_path(root, member_set_rel).exists()):
            raise PipelineError(f"{wid} already has this acquisition")
        revised_work = copy.deepcopy(work)
        for path in [receipt_rel, row["original_receipt"]["path"], credit_rel, *row["packages"], *row["primary_sources"]]:
            if path not in revised_work["evidence"]:
                revised_work["evidence"].append(path)
        revised_work["textual_forms"].append({"textual_form_id": form_id, "language": row["language"],
            "editions": [{"edition_id": edition_id, "title": row["edition_title"],
                          "language": row["language"], "acquisition_ids": [acquisition_id]}]})
        validate_identity_update(work, revised_work)
        validate_record("work", revised_work, context=f"{wid} proposed work")
        acquisition = {"schema_version": "2.0", "acquisition_id": acquisition_id,
                       "edition_id": edition_id, "provider": row["provider"], "url": row["url"],
                       "route": "born-digital", "retained_files": retained,
                       "source_scope": row["source_scope"], "warnings": row["warnings"]}
        if member_set_rel:
            acquisition["source_kind"] = "retained-member-set"
            acquisition["source_path"] = member_set_rel
            member_set_bytes = source_member_set_bytes(acquisition)
            acquisition["source_bytes"] = len(member_set_bytes)
            acquisition["source_sha256"] = hashlib.sha256(member_set_bytes).hexdigest()
            evidence_paths.append(member_set_rel)
            proposed.append((member_set_rel, json.loads(member_set_bytes), None))
        else:
            principal = retained[0]
            acquisition.update(source_path=principal["path"], source_bytes=principal["bytes"],
                               source_sha256=principal["sha256"])
        validate_record("acquisition", acquisition, context=f"{wid} proposed acquisition")
        revised_state = copy.deepcopy(state)
        target_evidence = [*evidence_paths, credit_rel, acquisition_rel]
        revised_state["targets"].extend([
            {"target_id": acquisition_id, "target_type": "acquisition", "stage": "acquired",
             "updated_at": timestamp, "evidence": target_evidence},
            {"target_id": edition_id, "target_type": "edition", "stage": "acquired",
             "updated_at": timestamp, "evidence": target_evidence},
        ])
        validate_record("state", revised_state, context=f"{wid} proposed state")
        proposed.extend([(work_rel, revised_work, sha256_file(work_path)),
                         (state_rel, revised_state, sha256_file(state_path)),
                         (acquisition_rel, acquisition, None),
                         (credit_rel, _credit_document(row, source_evidence, packet["extraction_receipt"]), None)])
        stage_entries.append({"work_id": wid, "source_paths": row["primary_sources"],
                              "package_paths": row["packages"], "member_set_path": member_set_rel,
                              "source_credit_path": credit_rel})
    if destination.exists():
        raise PipelineError(f"refusing existing stage destination: {destination}")
    _io_path(destination).mkdir(parents=True)
    staged_files = []
    for relative, document, before_hash in proposed:
        target = _io_path(destination / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(document, str):
            target.write_text(document, encoding="utf-8")
        else:
            write_json(target, document)
        staged_files.append({"path": relative, "before_sha256": before_hash,
                             "proposed_sha256": sha256_file(target)})
    stage_receipt = {"contract": "ocd-direct-raw-four-sidecar-stage-v1",
                     "packet_sha256": sha256_file(packet_path),
                     "extraction_receipt_sha256": sha256_file(receipt_path),
                     "entries": stage_entries,
                     "files": sorted(staged_files, key=lambda item: item["path"])}
    write_json(_io_path(destination / "receipt.json"), stage_receipt)
    return stage_receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    receipt = stage(args.repository_root, args.packet, args.destination)
    print(json.dumps({"destination": str(args.destination), "works": len(receipt["entries"]),
                      "files": len(receipt["files"])}, sort_keys=True))


if __name__ == "__main__":
    main()
