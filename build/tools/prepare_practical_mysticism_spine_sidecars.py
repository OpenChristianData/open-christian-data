"""Stage Practical Mysticism sidecars with OPF-spine text and bound checkout support."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError, sha256_file, write_json
from ocd_kernel.library.acquisitions import source_member_set_bytes, validate_acquisition
from ocd_kernel.library.identities import load_work, validate_identity_update, validate_record
from ocd_kernel.library.state import load_state, validate_state
from ocd_kernel.tei.install_accepted import _io_path


WORK_ID = "practical-mysticism"
CONTRACT = "ocd-practical-mysticism-spine-sidecar-stage-v1"
SOURCE_ROOT = "raw/standard_ebooks/evelyn-underhill_practical-mysticism"
PROFILE_REL = "sources/standard-ebooks/evelyn-underhill_practical-mysticism/practical-mysticism.reconstruction-profile.json"
MANIFEST_REL = "sources/standard-ebooks/evelyn-underhill_practical-mysticism/practical-mysticism.source-manifest.json"
CONFIG_REL = "sources/standard-ebooks/evelyn-underhill_practical-mysticism/config.json"
CATALOG_REL = "metadata/source-evidence/catalog/practical-mysticism.json"
CREDIT_SOURCE_REL = "sources/standard-ebooks/evelyn-underhill_practical-mysticism/README.source.md"
PACKET_REL = "plans/2026-09-22-source-preflight/practical-mysticism-spine-sidecar-packet-20260926.json"


def _json(root: Path, rel: str) -> dict:
    return json.loads(_io_path(root / rel).read_text(encoding="utf-8"))


def _member(root: Path, rel: str) -> dict:
    path = _io_path(resolve_repo_path(root, rel))
    if not path.is_file():
        raise PipelineError(f"missing Practical Mysticism retained member: {rel}")
    return {"path": rel, "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def evidence(root: Path) -> dict:
    profile, manifest, config = (_json(root, rel) for rel in (PROFILE_REL, MANIFEST_REL, CONFIG_REL))
    if (profile.get("work_id") != WORK_ID or profile.get("source_root") != SOURCE_ROOT
            or manifest.get("work_id") != WORK_ID or config.get("resource_id") != WORK_ID):
        raise PipelineError("Practical Mysticism source identity differs")
    scoped = profile["source_scope"]
    if scoped["commit"] != profile["source_revision"]:
        raise PipelineError("Practical Mysticism source revision differs")
    checkout = _io_path(resolve_repo_path(root, SOURCE_ROOT))
    files = sorted(p for p in checkout.rglob("*") if p.is_file() and ".git" not in p.parts)
    all_members = [_member(root, f"{SOURCE_ROOT}/{p.relative_to(checkout).as_posix()}") for p in files]
    if len(all_members) != scoped["member_count"] or sum(m["bytes"] for m in all_members) != scoped["bytes"]:
        raise PipelineError("Practical Mysticism retained checkout differs from profile")
    by_path = {item["path"]: item for item in all_members}
    profiled = {f"{SOURCE_ROOT}/{item['path']}": item for item in profile["members"]}
    if (set(profiled) != set(by_path)
            or any(any(by_path[rel][key] != entry[key] for key in ("bytes", "sha256")) for rel, entry in profiled.items())):
        raise PipelineError("Practical Mysticism profile member hashes differ")
    declared = [item for item in manifest["authorities"] if item["role"] == "primary-source"]
    if (len(declared) != len(all_members) or {item["path"] for item in declared} != set(by_path)
            or any(any(by_path[item["path"]][key] != item[key] for key in ("bytes", "sha256")) for item in declared)):
        raise PipelineError("Practical Mysticism source manifest differs from checkout")
    opf_rel = f"{SOURCE_ROOT}/src/epub/content.opf"
    tree = etree.parse(str(_io_path(resolve_repo_path(root, opf_rel))),
                       etree.XMLParser(resolve_entities=False, no_network=True))
    ns = {"opf": "http://www.idpf.org/2007/opf"}
    nodes = tree.xpath("//opf:manifest/opf:item", namespaces=ns)
    inventory = {node.get("id"): node.get("href") for node in nodes}
    if len(inventory) != len(nodes):
        raise PipelineError("Practical Mysticism OPF duplicate item IDs")
    spine = [inventory.get(node.get("idref")) for node in tree.xpath("//opf:spine/opf:itemref", namespaces=ns)]
    if (len(spine) < 2 or len(set(spine)) != len(spine)
            or any(not isinstance(rel, str) or not rel.startswith("text/") or not rel.endswith(".xhtml")
                   or ".." in Path(rel).parts for rel in spine)
            or ["src/epub/" + rel for rel in spine] != profile["spine"]):
        raise PipelineError("Practical Mysticism OPF spine differs from bound profile")
    ordered = [f"{SOURCE_ROOT}/src/epub/{rel}" for rel in spine]
    if any(rel not in by_path for rel in ordered):
        raise PipelineError("Practical Mysticism spine member missing")
    source, support = [by_path[rel] for rel in ordered], [item for item in all_members if item["path"] not in set(ordered)]
    if len(source) != 18 or len(support) != 15 or opf_rel not in {item["path"] for item in support}:
        raise PipelineError("Practical Mysticism text/support boundary differs")
    work_rel, state_rel = (f"library/works/{WORK_ID}/{name}.json" for name in ("work", "state"))
    return {"contract": CONTRACT, "work_id": WORK_ID,
            "authorities": {rel: sha256_file(_io_path(root / rel)) for rel in
                            (PROFILE_REL, MANIFEST_REL, CONFIG_REL, CATALOG_REL, CREDIT_SOURCE_REL)},
            "source_revision": profile["source_revision"], "source_root": SOURCE_ROOT,
            "opf": by_path[opf_rel], "ordered_text_members": source, "support_members": support,
            "url": config["source_url"],
            "before": {"work": sha256_file(_io_path(root / work_rel)),
                       "state": sha256_file(_io_path(root / state_rel))}}


def stage(root: Path, destination: Path) -> dict:
    root, destination = root.resolve(), destination.resolve()
    if destination.exists():
        raise PipelineError(f"stage destination exists: {destination}")
    work_rel, state_rel = (f"library/works/{WORK_ID}/{name}.json" for name in ("work", "state"))
    work, state = load_work(_io_path(root / work_rel)), load_state(_io_path(root / state_rel))
    if work["textual_forms"] or state["targets"]:
        raise PipelineError("Practical Mysticism no longer identity-only")
    packet = evidence(root)
    packet_path = _io_path(root / PACKET_REL)
    if packet_path.exists():
        if _json(root, PACKET_REL) != packet:
            raise PipelineError("existing Practical Mysticism packet differs")
    else:
        write_json(packet_path, packet)
    form_id = f"{WORK_ID}-standard-ebooks-en"
    edition_id = f"{WORK_ID}-standard-ebooks-retained"
    acquisition_id = f"{WORK_ID}-standard-ebooks-acquired"
    edition_rel = f"library/works/{WORK_ID}/forms/{form_id}/editions/{edition_id}"
    acq_rel = f"{edition_rel}/acquisitions/{acquisition_id}.json"
    descriptor_rel = f"{edition_rel}/source-member-set.json"
    support_rel = f"{edition_rel}/retained-support.json"
    credit_rel = f"library/works/{WORK_ID}/SOURCE_CREDIT.md"
    for rel in (acq_rel, descriptor_rel, support_rel, credit_rel):
        if _io_path(root / rel).exists():
            raise PipelineError(f"Practical Mysticism destination exists: {rel}")
    ordered = packet["ordered_text_members"]
    scope = (f"{len(ordered)} complete retained Standard Ebooks XHTML files in exact OPF spine order. "
             f"The other {len(packet['support_members'])} checkout files are separately hash-bound support, "
             "including images, styles, OPF, navigation, license, and repository files; not reconstruction text.")
    acquisition = {"schema_version": "2.0", "acquisition_id": acquisition_id, "edition_id": edition_id,
                   "provider": "Standard Ebooks", "url": packet["url"], "route": "born-digital",
                   "source_kind": "retained-member-set", "source_path": descriptor_rel,
                   "retained_files": [dict(item, media_type="application/xhtml+xml",
                                           scope=f"OPF spine position {index} of {len(ordered)}")
                                      for index, item in enumerate(ordered, 1)],
                   "source_scope": scope,
                   "warnings": ["Source and artwork rights and attribution require separate review; acquisition does not establish accepted TEI or publication authorization.",
                                f"Complete checkout support is bound in {support_rel}."]}
    descriptor = source_member_set_bytes(acquisition)
    acquisition["source_bytes"] = len(descriptor)
    acquisition["source_sha256"] = hashlib.sha256(descriptor).hexdigest()
    validate_record("acquisition", acquisition, context=acq_rel)
    updated_work, updated_state = copy.deepcopy(work), copy.deepcopy(state)
    updated_work["textual_forms"].append({"textual_form_id": form_id, "language": "en",
                                          "editions": [{"edition_id": edition_id,
                                                        "title": "Practical Mysticism (Standard Ebooks retained electronic witness)",
                                                        "language": "en", "acquisition_ids": [acquisition_id]}]})
    for rel in (PACKET_REL, PROFILE_REL, MANIFEST_REL, support_rel, credit_rel):
        if rel not in updated_work["evidence"]:
            updated_work["evidence"].append(rel)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    for target_id, kind in ((acquisition_id, "acquisition"), (edition_id, "edition")):
        updated_state["targets"].append({"target_id": target_id, "target_type": kind, "stage": "acquired",
                                         "updated_at": now, "evidence": [PACKET_REL, PROFILE_REL, MANIFEST_REL,
                                                                          support_rel, credit_rel, acq_rel, descriptor_rel]})
    validate_identity_update(work, updated_work)
    validate_record("work", updated_work, context=WORK_ID)
    validate_record("state", updated_state, context=WORK_ID)
    support = {"contract": "ocd-retained-checkout-support-v1", "work_id": WORK_ID,
               "source_root": SOURCE_ROOT, "source_revision": packet["source_revision"],
               "opf": packet["opf"], "text_member_count": len(ordered),
               "support_members": packet["support_members"]}
    credit = ("# Source and credit — Practical Mysticism\n\n"
              f"Standard Ebooks electronic witness, commit {packet['source_revision']}: "
              f"{len(ordered)} retained XHTML text files in exact OPF spine order. "
              f"The other {len(packet['support_members'])} checkout files are retained and hash-bound "
              f"as support in {support_rel}; images, styles, navigation, license and repository files "
              "are not reconstruction text. The retained Standard Ebooks attribution and rights "
              "claims need separate review. Acquisition does not establish accepted TEI, rights "
              "clearance, or publication authorization.\n")
    output = {work_rel: updated_work, state_rel: updated_state, acq_rel: acquisition,
              descriptor_rel: json.loads(descriptor), support_rel: support, credit_rel: credit}
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
    validate_acquisition(_io_path(destination / acq_rel), root=_io_path(destination))
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
