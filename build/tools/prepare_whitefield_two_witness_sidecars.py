"""Stage distinct CCEL and Gutenberg Whitefield electronic acquisitions."""
from __future__ import annotations

import argparse
import copy
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError, sha256_file, write_json
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work, validate_identity_update, validate_record
from ocd_kernel.library.state import load_state, validate_state
from ocd_kernel.tei.install_accepted import _io_path


WORK_ID = "george-whitefield-sermons"
CONTRACT = "ocd-whitefield-two-witness-sidecar-stage-v1"
BASE = "sources/sermons/george-whitefield-sermons"
PROFILE_REL = f"{BASE}/george-whitefield-sermons.reconstruction-profile.json"
MANIFEST_REL = f"{BASE}/george-whitefield-sermons.source-manifest.json"
CONFIG_REL = f"{BASE}/config.json"
CATALOG_REL = "metadata/source-evidence/catalog/george-whitefield-sermons.json"
PACKET_REL = "plans/2026-09-22-source-preflight/whitefield-two-witness-sidecar-packet-20260926.json"


def _json(root: Path, rel: str) -> dict:
    return json.loads(_io_path(root / rel).read_text(encoding="utf-8"))


def _member(root: Path, rel: str) -> dict:
    path = _io_path(resolve_repo_path(root, rel))
    if not path.is_file():
        raise PipelineError(f"Whitefield retained member missing: {rel}")
    return {"path": rel, "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def evidence(root: Path) -> dict:
    profile, manifest, config = (_json(root, rel) for rel in (PROFILE_REL, MANIFEST_REL, CONFIG_REL))
    if (profile.get("contract") != "ocd-george-whitefield-reconstruction-profile-v1"
            or profile.get("work_id") != WORK_ID or manifest.get("work_id") != WORK_ID
            or config.get("resource_id") != WORK_ID):
        raise PipelineError("Whitefield source identity differs")
    members = profile["members"]
    if (len(members) != 2 or [item["name"] for item in members]
            != ["retained-ccel-xml", "retained-project-gutenberg-text"]):
        raise PipelineError("Whitefield two-witness profile differs")
    actual = [_member(root, item["path"]) for item in members]
    declared = manifest["source_members"]
    for source, profiled, item in zip(actual, members, declared, strict=True):
        if (any(source[key] != profiled[key] or source[key] != item[key]
                for key in ("path", "bytes", "sha256")) or item["role"] != "primary-source"):
            raise PipelineError(f"Whitefield retained witness differs: {source['path']}")
    if (manifest["retained_source_path"] != actual[0]["path"]
            or config["source_hash"] != "sha256:" + actual[0]["sha256"]
            or config["supplementary_source"]["source_hash"] != "sha256:" + actual[1]["sha256"]):
        raise PipelineError("Whitefield config source hashes differ")
    xml = etree.parse(str(_io_path(resolve_repo_path(root, actual[0]["path"]))),
                      etree.XMLParser(resolve_entities=False, no_network=True))
    divs = xml.xpath("/ThML/ThML.body/div1")
    if (xml.getroot().tag != members[0]["expected_root"]
            or [div.get("id") for div in divs] != members[0]["expected_direct_div1_ids"]):
        raise PipelineError("Whitefield CCEL XML scope differs")
    gutenberg = _io_path(resolve_repo_path(root, actual[1]["path"]))
    lines = gutenberg.read_text(encoding="utf-8-sig").splitlines()
    if (len(lines) != members[1]["expected_physical_line_count"]
            or members[1]["selected_source_sermon_labels"] != ["LVIII", "LIX"]
            or sum(line.strip() == "SERMON LVIII." for line in lines) != 1
            or sum(line.strip() == "SERMON LIX." for line in lines) != 1):
        raise PipelineError("Whitefield Gutenberg two-sermon scope differs")
    authorities = {rel: sha256_file(_io_path(root / rel)) for rel in
                   (PROFILE_REL, MANIFEST_REL, CONFIG_REL, CATALOG_REL)}
    work_rel, state_rel = (f"library/works/{WORK_ID}/{name}.json" for name in ("work", "state"))
    return {"contract": CONTRACT, "work_id": WORK_ID, "authorities": authorities,
            "witnesses": {"ccel": {"source": actual[0], "url": config["source_url"],
                                   "div1_ids": [div.get("id") for div in divs]},
                          "gutenberg": {"source": actual[1],
                                        "url": config["supplementary_source"]["url"],
                                        "selected_labels": ["LVIII", "LIX"],
                                        "physical_line_count": len(lines)}},
            "identity_unresolved": profile["identity"],
            "before": {"work": sha256_file(_io_path(root / work_rel)),
                       "state": sha256_file(_io_path(root / state_rel))}}


def stage(root: Path, destination: Path) -> dict:
    root, destination = root.resolve(), destination.resolve()
    if destination.exists():
        raise PipelineError(f"stage destination exists: {destination}")
    work_rel, state_rel = (f"library/works/{WORK_ID}/{name}.json" for name in ("work", "state"))
    work, state = load_work(_io_path(root / work_rel)), load_state(_io_path(root / state_rel))
    if work["textual_forms"] or state["targets"]:
        raise PipelineError("Whitefield no longer identity-only")
    packet = evidence(root)
    packet_path = _io_path(root / PACKET_REL)
    if packet_path.exists():
        if _json(root, PACKET_REL) != packet:
            raise PipelineError("existing Whitefield packet differs")
    else:
        write_json(packet_path, packet)
    credit_rel = f"library/works/{WORK_ID}/SOURCE_CREDIT.md"
    if _io_path(root / credit_rel).exists():
        raise PipelineError("Whitefield source credit already exists")
    updated_work, updated_state = copy.deepcopy(work), copy.deepcopy(state)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    output: dict[str, dict | str] = {}
    for label, provider, media in (("ccel", "CCEL", "application/xml"),
                                   ("gutenberg", "Project Gutenberg", "text/plain")):
        form_id = f"{WORK_ID}-{label}-retained-en"
        edition_id = f"{WORK_ID}-{label}-retained-electronic"
        acquisition_id = f"{WORK_ID}-{label}-acquired"
        source = packet["witnesses"][label]["source"]
        edition_rel = f"library/works/{WORK_ID}/forms/{form_id}/editions/{edition_id}"
        acq_rel = f"{edition_rel}/acquisitions/{acquisition_id}.json"
        if _io_path(root / acq_rel).exists():
            raise PipelineError(f"Whitefield acquisition already exists: {acq_rel}")
        if label == "ccel":
            scope = ("Complete retained CCEL ThML XML document, including source metadata and 62 "
                     "source-native div1 carriers. No relationship to a particular print edition "
                     "or to Gutenberg numbering is asserted.")
            title = "Whitefield sermons, CCEL retained electronic witness"
        else:
            scope = ("Complete retained Project Gutenberg #77041 UTF-8 text file as acquired envelope; "
                     "only source-native Sermons LVIII and LIX are selected by the local work-specific "
                     "route. Other sermons remain acquired context. No shared CCEL ordinal or "
                     "common historical edition is inferred.")
            title = "Whitefield sermons LVIII and LIX, Gutenberg retained electronic witness"
        updated_work["textual_forms"].append({"textual_form_id": form_id, "language": "en",
                                               "editions": [{"edition_id": edition_id, "title": title,
                                                             "language": "en", "acquisition_ids": [acquisition_id]}]})
        acquisition = {"schema_version": "2.0", "acquisition_id": acquisition_id,
                       "edition_id": edition_id, "provider": provider,
                       "url": packet["witnesses"][label]["url"], "route": "born-digital",
                       "source_path": source["path"], "source_bytes": source["bytes"],
                       "source_sha256": source["sha256"], "source_scope": scope,
                       "retained_files": [dict(source, media_type=media, scope=scope)],
                       "warnings": ["Collection, cross-witness relationship, rights, acceptance, and publication remain unresolved."]}
        validate_record("acquisition", acquisition, context=acq_rel)
        output[acq_rel] = acquisition
        for target_id, kind in ((acquisition_id, "acquisition"), (edition_id, "edition")):
            updated_state["targets"].append({"target_id": target_id, "target_type": kind,
                                             "stage": "acquired", "updated_at": now,
                                             "evidence": [PACKET_REL, PROFILE_REL, MANIFEST_REL, credit_rel, acq_rel]})
    for rel in (PACKET_REL, PROFILE_REL, MANIFEST_REL, credit_rel):
        if rel not in updated_work["evidence"]:
            updated_work["evidence"].append(rel)
    validate_identity_update(work, updated_work)
    validate_record("work", updated_work, context=WORK_ID)
    validate_record("state", updated_state, context=WORK_ID)
    credit = ("# Source and credit — George Whitefield sermons\n\n"
              f"CCEL witness: {packet['witnesses']['ccel']['source']['path']}, full retained XML "
              f"(SHA-256 {packet['witnesses']['ccel']['source']['sha256']}).\n\n"
              f"Project Gutenberg witness: {packet['witnesses']['gutenberg']['source']['path']}, "
              f"full retained text file (SHA-256 {packet['witnesses']['gutenberg']['source']['sha256']}). "
              "The current work-specific reconstruction selects its source-native Sermons LVIII "
              "and LIX only; other text in the acquired file is context. The two electronic "
              "witnesses have separate editions and acquisitions. Their shared historical edition, "
              "collection boundary, numbering, rights, human acceptance, and publication remain unresolved.\n")
    output.update({work_rel: updated_work, state_rel: updated_state, credit_rel: credit})
    destination.mkdir(parents=True)
    storage = root / ".ocd-storage.json"
    if storage.is_file():
        shutil.copy2(storage, destination / ".ocd-storage.json")
    for rel in (PACKET_REL, PROFILE_REL, MANIFEST_REL):
        target = _io_path(destination / rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_io_path(root / rel), target)
    files = []
    for rel, value in output.items():
        target = _io_path(destination / rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(value, str):
            target.write_text(value, encoding="utf-8")
        else:
            write_json(target, value)
        current = _io_path(root / rel)
        files.append({"path": rel, "before_sha256": sha256_file(current) if current.is_file() else None,
                      "proposed_sha256": sha256_file(target)})
    receipt = {"contract": CONTRACT, "packet_path": PACKET_REL,
               "packet_sha256": sha256_file(packet_path), "files": sorted(files, key=lambda item: item["path"])}
    write_json(_io_path(destination / "receipt.json"), receipt)
    for rel in output:
        if "/acquisitions/" in rel:
            validate_acquisition(_io_path(destination / rel), root=_io_path(destination))
    validate_state(_io_path(destination / state_rel), root=_io_path(destination))
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    result = stage(args.repository_root, args.destination)
    print(json.dumps({"destination": str(args.destination), "files": len(result["files"])}, sort_keys=True))


if __name__ == "__main__":
    main()
