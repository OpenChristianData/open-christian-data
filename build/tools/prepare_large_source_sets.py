"""Stage acquired-source sidecars for eight manifest-bound large source sets.

This is source accounting only. A catalog work ID does not establish complete
textual coverage, independent work boundaries, TEI acceptance, or publication.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError, canonical_bytes, sha256_file, write_json
from ocd_kernel.library.acquisitions import source_member_set_bytes
from ocd_kernel.library.identities import load_work, validate_identity_update, validate_record
from ocd_kernel.library.state import load_state
from ocd_kernel.tei.install_accepted import _io_path


CONTRACT = "ocd-large-source-set-sidecar-stage-v1"
PACKET_REL = "plans/2026-09-22-source-preflight/large-source-sets-packet-20260926.json"
SOURCES = {
    "adam-clarke": ("sources/commentaries/adam-clarke/adam-clarke.source-manifest.json", "HelloAO Bible API", "https://bible.helloao.org/api/c/adam-clarke", "raw/helloao_local/api/c/adam-clarke/"),
    "catholic-encyclopedia-vol01": ("sources/reference/catholic-encyclopedia/current-web-20260911/catholic-encyclopedia.source-manifest.json", "New Advent", "https://www.newadvent.org/cathen/", "raw/newadvent/"),
    "church-fathers-quotations": ("sources/structured-text/church-fathers-quotations/church-fathers-quotations.source-manifest.json", "Commentaries-Database retained tree", "https://github.com/HistoricalChristianFaith/Commentaries-Database/releases", "raw/Commentaries-Database/"),
    "jamieson-fausset-brown": ("sources/commentaries/jamieson-fausset-brown/jamieson-fausset-brown.source-manifest.json", "HelloAO Bible API", "https://bible.helloao.org/api/c/jamieson-fausset-brown", "raw/helloao_local/api/c/jamieson-fausset-brown/"),
    "john-gill": ("sources/commentaries/john-gill/john-gill.source-manifest.json", "HelloAO Bible API", "https://bible.helloao.org/api/c/john-gill", "raw/helloao_local/api/c/john-gill/"),
    "keil-delitzsch": ("sources/commentaries/keil-delitzsch/keil-delitzsch.source-manifest.json", "HelloAO Bible API", "https://bible.helloao.org/api/c/keil-delitzsch", "raw/helloao_local/api/c/keil-delitzsch/"),
    "matthew-henry-complete": ("sources/commentaries/matthew-henry/matthew-henry.source-manifest.json", "HelloAO Bible API", "https://bible.helloao.org/api/c/matthew-henry", "raw/helloao_local/api/c/matthew-henry/"),
    "spurgeon-mtp": ("sources/spurgeon-mtp/spurgeon-mtp.source-manifest.json", "Kingdom Collective and supplemental retained witnesses", "https://thekingdomcollective.com/spurgeon/", "raw/spurgeon_sermons/"),
}
CONFIGS = {
    "adam-clarke": "sources/commentaries/adam-clarke/config.json",
    "church-fathers-quotations": "sources/structured-text/church-fathers-quotations/config.json",
    "jamieson-fausset-brown": "sources/commentaries/jamieson-fausset-brown/config.json",
    "john-gill": "sources/commentaries/john-gill/config.json",
    "keil-delitzsch": "sources/commentaries/keil-delitzsch/config.json",
    "matthew-henry-complete": "sources/commentaries/matthew-henry/config.json",
    "spurgeon-mtp": "sources/sermons/spurgeon-mtp/config.json",
}
SPECIAL_WARNINGS = {
    "adam-clarke": ["HelloAO retains 57 books; the config notes possible absent Old Testament books. The acquired set is not a verified complete Bible commentary."],
    "catholic-encyclopedia-vol01": ["The existing catalog ID says vol01, but the retained New Advent current-web crawl spans a broader encyclopedia cohort and does not establish a Volume I boundary.", "The manifest marks the crawl partial with 17 failed acquisitions. This acquired set is not a complete encyclopedia or volume claim.", "New Advent pages carry publisher copyright and transcription-credit notices; acquisition does not establish redistribution rights or satisfy a human-visible attribution deliverable."],
    "church-fathers-quotations": ["The TOML tree is a collection of quotations from multiple historical authors. This catalog identity does not settle independent-work, authorship, translator, or print-edition boundaries.", "The retained LICENSE warns that a small number of quotations may be from copyrighted translations; release review must resolve them."],
    "matthew-henry-complete": ["The HelloAO witness lacks Song of Solomon, Matthew chapters 19–28, and Jonah chapters 2–4. 'Complete' is the existing catalog label, not a source-coverage finding."],
    "spurgeon-mtp": ["The retained set has 3,550 HTML witnesses; 13 numbered sermon slots remain missing or source-identity blocked according to its source notice.", "Supplemental witnesses 708 and 3032 carry Modernized Edition terms forbidding electronic reproduction and derivatives without express written permission; acquisition is not publication clearance."],
}
MEDIA = {".json": "application/json", ".html": "text/html", ".toml": "application/toml", ".gif": "image/gif", ".jpg": "image/jpeg"}


def binding(root: Path, work_id: str, *, verify_files: bool = True) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Read the pinned manifest and verify its explicit non-package primary files."""
    if work_id not in SOURCES:
        raise PipelineError(f"unknown large source set: {work_id}")
    manifest_rel, _, _, prefix = SOURCES[work_id]
    manifest_path = root / manifest_rel
    manifest = json.loads(_io_path(manifest_path).read_text(encoding="utf-8"))
    if manifest.get("work_id") not in (None, work_id):
        raise PipelineError(f"{work_id} manifest work ID differs")
    if work_id == "catholic-encyclopedia-vol01":
        scope = manifest.get("expression_scope", {})
        if scope.get("whole_work_complete") is not False or scope.get("status") != "partial" or len(manifest.get("failed_acquisitions", [])) != 17:
            raise PipelineError("Catholic current-web partial-scope evidence changed")
    if work_id == "church-fathers-quotations" and manifest.get("expression_scope", {}).get("included_primary_members") != "every retained .toml member":
        raise PipelineError("Church Fathers retained TOML boundary changed")
    if work_id == "spurgeon-mtp" and len(manifest.get("source_members", [])) != 3550:
        raise PipelineError("Spurgeon retained sermon count changed")
    config_rel = CONFIGS.get(work_id)
    if config_rel:
        config = json.loads(_io_path(root / config_rel).read_text(encoding="utf-8"))
        if config.get("resource_id") != work_id:
            raise PipelineError(f"{work_id} config resource ID differs")
        if work_id == "matthew-henry-complete" and len(config.get("known_coverage_gaps", [])) != 3:
            raise PipelineError("Matthew Henry coverage gaps changed")
    authorities = manifest.get("authorities")
    if not isinstance(authorities, list):
        raise PipelineError(f"{work_id} lacks explicit authorities")
    primary = [item for item in authorities if item.get("role") == "primary-source"]
    if not primary:
        raise PipelineError(f"{work_id} has no primary-source files")
    seen: set[str] = set()
    members = []
    support = []
    for item in primary:
        rel = item["path"]
        suffix = Path(rel).suffix.lower()
        if not rel.startswith(prefix) or rel in seen or suffix not in MEDIA or suffix == ".zip":
            raise PipelineError(f"{work_id} invalid/duplicate non-source member: {rel}")
        seen.add(rel)
        path = resolve_repo_path(root, rel)
        if verify_files and (not path.is_file() or path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]):
            raise PipelineError(f"{work_id} retained member differs from manifest: {rel}")
        name = Path(rel).name
        if work_id == "catholic-encyclopedia-vol01":
            is_content = suffix == ".html"
            reason = "image asset, retained as source-presentation support"
        elif work_id == "church-fathers-quotations":
            is_content = name != "metadata.toml"
            reason = "source metadata context, retained as reconstruction support"
        elif work_id == "spurgeon-mtp":
            is_content = True
            reason = ""
        else:
            is_content = name[:-5].isdigit() if suffix == ".json" else False
            reason = "HelloAO book/profile metadata, retained as reconstruction support"
        if is_content:
            members.append({"path": rel, "bytes": item["bytes"], "sha256": item["sha256"],
                            "media_type": MEDIA[suffix], "scope": f"Retained reconstruction-content member of the manifest-bound {work_id} cohort."})
        else:
            support.append({"path": rel, "bytes": item["bytes"], "sha256": item["sha256"],
                            "media_type": MEDIA[suffix], "reason": reason})
    if work_id == "catholic-encyclopedia-vol01" and (len(members), len(support)) != (11680, 378):
        raise PipelineError("Catholic HTML/image classification differs")
    if work_id == "church-fathers-quotations" and (len(members), len(support)) != (58340, 335):
        raise PipelineError("Church Fathers quote/metadata classification differs")
    if work_id in {"adam-clarke", "jamieson-fausset-brown", "john-gill", "keil-delitzsch", "matthew-henry-complete"} and len(support) != 2:
        raise PipelineError(f"{work_id} HelloAO support member count differs")
    if work_id == "spurgeon-mtp" and [item["path"] for item in manifest["source_members"]] != [item["path"] for item in primary]:
        raise PipelineError("Spurgeon source-member order differs from authorities")
    info = {"work_id": work_id, "manifest_path": manifest_rel, "manifest_sha256": sha256_file(manifest_path),
            "source_id": manifest["source_id"], "manifest_primary_count": len(primary),
            "source_member_count": len(members), "source_member_bytes": sum(item["bytes"] for item in members),
            "support_member_count": len(support), "support_members": support,
            "member_order_sha256": hashlib.sha256("\n".join(item["path"] for item in members).encode("utf-8")).hexdigest(),
            "nonprimary_authority_count": len(authorities) - len(primary),
            "scope_warnings": SPECIAL_WARNINGS.get(work_id, [])}
    if config_rel:
        info["config_path"] = config_rel
        info["config_sha256"] = sha256_file(root / config_rel)
    return info, members


def stage(root: Path, destination: Path, *, skip_live_hash_for: frozenset[str] = frozenset()) -> dict[str, Any]:
    root, destination = root.resolve(), destination.resolve()
    if not skip_live_hash_for <= set(SOURCES):
        raise PipelineError("unknown live-hash skip work ID")
    if destination.exists() or (root / PACKET_REL).exists():
        raise PipelineError("large-source stage destination or packet already exists")
    try:
        destination.relative_to(root)
    except ValueError:
        pass
    else:
        raise PipelineError("stage destination must be outside repository")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    packet: dict[str, Any] = {"contract": CONTRACT, "scope": "Eight acquired retained source cohorts; no TEI acceptance, rights clearance, independent-work identity decision, or publication", "works": []}
    staged: list[tuple[str, bytes, str | None]] = []
    for wid in SOURCES:
        live_checked = wid not in skip_live_hash_for
        info, members = binding(root, wid, verify_files=live_checked)
        info["live_file_hash_check"] = "checked-this-run" if live_checked else "deferred-to-install-preflight"
        print(f"{info['live_file_hash_check']} {wid}: {len(members)} source files", flush=True)
        old_work = load_work(root / f"library/works/{wid}/work.json")
        old_state = load_state(root / f"library/works/{wid}/state.json")
        if old_work["textual_forms"] or old_state["targets"]:
            raise PipelineError(f"{wid} is not identity-only")
        work, state = copy.deepcopy(old_work), copy.deepcopy(old_state)
        form_id, edition_id, acquisition_id = f"{wid}-retained-en", f"{wid}-retained-electronic", f"{wid}-acquired-member-set"
        edition_rel = f"library/works/{wid}/forms/{form_id}/editions/{edition_id}"
        acq_rel = f"{edition_rel}/acquisitions/{acquisition_id}.json"
        descriptor_rel = f"{edition_rel}/source-member-set.json"
        provider, url = SOURCES[wid][1:3]
        scope = (f"Exact {len(members)}-file manifest-bound retained {provider} cohort, with separately hash-pinned support members from the same manifest. "
                 "Source acquisition only; textual coverage, edition identity, faithful TEI, human acceptance, rights, and publication require separate review.")
        warnings = ["Source files are the explicit reconstruction-content retained members; manifest metadata and image support are separately hash-pinned, and any archive or ZIP is only a package.", *SPECIAL_WARNINGS.get(wid, [])]
        acquisition = {"schema_version": "2.0", "acquisition_id": acquisition_id, "edition_id": edition_id,
                       "provider": provider, "route": "born-digital", "retained_files": members,
                       "source_path": descriptor_rel, "source_kind": "retained-member-set", "source_scope": scope,
                       "warnings": warnings}
        if url:
            acquisition["url"] = url
        descriptor = source_member_set_bytes(acquisition)
        acquisition["source_bytes"] = len(descriptor)
        acquisition["source_sha256"] = hashlib.sha256(descriptor).hexdigest()
        validate_record("acquisition", acquisition, context=acq_rel)
        work["textual_forms"].append({"textual_form_id": form_id, "language": "en",
                                      "editions": [{"edition_id": edition_id, "title": f"{work['title']} — retained electronic source cohort", "language": "en", "acquisition_ids": [acquisition_id]}]})
        for evidence in (info["manifest_path"], info.get("config_path"), PACKET_REL):
            if evidence and evidence not in work["evidence"]:
                work["evidence"].append(evidence)
        evidence = [PACKET_REL, info["manifest_path"], descriptor_rel, acq_rel]
        for target_id, target_type in ((acquisition_id, "acquisition"), (edition_id, "edition")):
            state["targets"].append({"target_id": target_id, "target_type": target_type, "stage": "acquired", "updated_at": now, "evidence": evidence})
        validate_identity_update(old_work, work)
        validate_record("work", work, context=wid)
        validate_record("state", state, context=wid)
        for rel, document in ((f"library/works/{wid}/work.json", work), (f"library/works/{wid}/state.json", state), (acq_rel, acquisition)):
            before = sha256_file(root / rel) if (root / rel).exists() else None
            if before is not None and rel == acq_rel:
                raise PipelineError(f"{wid} acquisition already exists")
            staged.append((rel, canonical_bytes(document), before))
        staged.append((descriptor_rel, descriptor, None))
        info.update({"source_descriptor_path": descriptor_rel, "source_descriptor_sha256": acquisition["source_sha256"],
                     "source_descriptor_bytes": len(descriptor), "acquisition_path": acq_rel, "warnings": warnings})
        packet["works"].append(info)
    packet_path = root / PACKET_REL
    write_json(packet_path, packet)
    files = []
    for rel, blob, before in staged:
        path = _io_path(destination / rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
        files.append({"path": rel, "before_sha256": before, "proposed_sha256": hashlib.sha256(blob).hexdigest()})
    receipt = {"contract": CONTRACT, "packet_path": PACKET_REL, "packet_sha256": sha256_file(packet_path),
               "files": sorted(files, key=lambda item: item["path"])}
    write_json(_io_path(destination / "receipt.json"), receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--skip-live-hash-for", action="append", default=[], choices=sorted(SOURCES))
    args = parser.parse_args()
    receipt = stage(args.repository_root, args.destination, skip_live_hash_for=frozenset(args.skip_live_hash_for))
    print(json.dumps({"destination": str(args.destination), "files": len(receipt["files"]), "packet_sha256": receipt["packet_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
