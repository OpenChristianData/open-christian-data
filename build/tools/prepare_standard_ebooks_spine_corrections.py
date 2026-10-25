"""Stage source-accounting corrections for four acquired Standard Ebooks works.

Only OPF spine XHTML is reconstruction text. Every other retained checkout file
is hash-bound support. This route does not change a TEI or acceptance decision.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
from pathlib import Path

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError, sha256_file, write_json
from ocd_kernel.library.acquisitions import source_member_set_bytes, validate_acquisition
from ocd_kernel.library.identities import load_work, validate_identity_update, validate_record
from ocd_kernel.tei.install_accepted import _io_path


IDS = ("george-macdonald-unspoken-sermons", "heretics", "orthodoxy", "the-everlasting-man")
CONTRACT = "ocd-standard-ebooks-spine-correction-v1"
ORIGINAL_PACKET = "plans/2026-09-22-source-preflight/exclusive-multi-manifest-six-sidecar-batch-20260926.json"
PACKET_REL = "plans/2026-09-22-source-preflight/standard-ebooks-four-spine-correction-packet-20260926.json"


def _member(root: Path, rel: str) -> dict:
    path = _io_path(resolve_repo_path(root, rel))
    if not path.is_file():
        raise PipelineError(f"missing retained checkout member: {rel}")
    return {"path": rel, "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def _record(root: Path, rel: str) -> dict:
    return json.loads(_io_path(root / rel).read_text(encoding="utf-8"))


def _one(root: Path, original: dict) -> dict:
    work_id = original["work_id"]
    if work_id not in IDS or original["provider"] != "Standard Ebooks":
        raise PipelineError(f"unexpected Standard Ebooks work: {work_id}")
    work_rel = f"library/works/{work_id}/work.json"
    state_rel = f"library/works/{work_id}/state.json"
    work = load_work(_io_path(root / work_rel))
    if len(work["textual_forms"]) != 1 or work["textual_forms"][0]["textual_form_id"] != original["textual_form_id"]:
        raise PipelineError(f"{work_id} textual form differs")
    edition = work["textual_forms"][0]["editions"][0]
    if edition["edition_id"] != original["edition_id"] or edition["acquisition_ids"] != [original["acquisition_id"]]:
        raise PipelineError(f"{work_id} edition/acquisition identity differs")
    if list(_io_path(root / f"library/works/{work_id}").rglob("acceptance.json")):
        raise PipelineError(f"{work_id} has accepted TEI; dedicated acceptance rebind required")
    edition_rel = f"library/works/{work_id}/forms/{original['textual_form_id']}/editions/{original['edition_id']}"
    acq_rel = f"{edition_rel}/acquisitions/{original['acquisition_id']}.json"
    descriptor_rel = f"{edition_rel}/source-member-set.json"
    support_rel = f"{edition_rel}/retained-support.json"
    credit_rel = f"library/works/{work_id}/SOURCE_CREDIT.md"
    if _io_path(root / support_rel).exists() or _io_path(root / credit_rel).exists():
        raise PipelineError(f"{work_id} correction already present")
    acquisition = _record(root, acq_rel)
    if acquisition.get("source_path") != descriptor_rel or acquisition.get("source_kind") != "retained-member-set":
        raise PipelineError(f"{work_id} acquisition route differs")
    declared = original["primary_sources"]
    if [(m["path"], m["bytes"], m["sha256"]) for m in declared] != [
        (m["path"], m["bytes"], m["sha256"]) for m in acquisition["retained_files"]
    ]:
        raise PipelineError(f"{work_id} original manifest/installed source members differ")
    for key in ("source_manifest", "config", "metadata_evidence"):
        ref = original[key]
        if sha256_file(_io_path(root / ref["path"])) != ref["sha256"]:
            raise PipelineError(f"{work_id} authority changed: {ref['path']}")
    source_root = declared[0]["path"].split("/src/epub/")[0]
    checkout = _io_path(resolve_repo_path(root, source_root))
    files = sorted(p for p in checkout.rglob("*") if p.is_file() and ".git" not in p.parts)
    all_members = [_member(root, f"{source_root}/{p.relative_to(checkout).as_posix()}") for p in files]
    opf_rel = f"{source_root}/src/epub/content.opf"
    tree = etree.parse(str(_io_path(resolve_repo_path(root, opf_rel))),
                       etree.XMLParser(resolve_entities=False, no_network=True))
    ns = {"opf": "http://www.idpf.org/2007/opf"}
    manifest_nodes = tree.xpath("//opf:manifest/opf:item", namespaces=ns)
    manifest = {node.get("id"): node.get("href") for node in manifest_nodes}
    if len(manifest) != len(manifest_nodes):
        raise PipelineError(f"{work_id} OPF duplicate item IDs")
    spine = [manifest.get(node.get("idref")) for node in tree.xpath("//opf:spine/opf:itemref", namespaces=ns)]
    if (len(spine) < 2 or len(set(spine)) != len(spine)
            or any(not isinstance(item, str) or not item.startswith("text/")
                   or not item.endswith(".xhtml") or ".." in Path(item).parts for item in spine)):
        raise PipelineError(f"{work_id} OPF spine is not an unambiguous XHTML source set")
    ordered = [f"{source_root}/src/epub/{item}" for item in spine]
    by_path = {item["path"]: item for item in all_members}
    if any(rel not in by_path for rel in ordered):
        raise PipelineError(f"{work_id} OPF spine member missing")
    source = [by_path[rel] for rel in ordered]
    declared_paths = {item["path"] for item in declared}
    if declared_paths != set(ordered) | {f"{source_root}/src/epub/images/{name}.svg" for name in ("cover", "logo", "titlepage")}:
        raise PipelineError(f"{work_id} manifest primary source boundary differs")
    if any(by_path[item["path"]] != {key: item[key] for key in ("path", "bytes", "sha256")} for item in declared):
        raise PipelineError(f"{work_id} retained primary bytes differ")
    support = [item for item in all_members if item["path"] not in set(ordered)]
    if not support or opf_rel not in {item["path"] for item in support}:
        raise PipelineError(f"{work_id} checkout support boundary differs")
    return {"work_id": work_id, "source_root": source_root,
            "authority": {key: original[key] for key in ("source_manifest", "config", "metadata_evidence")},
            "opf": by_path[opf_rel], "ordered_text_members": source, "support_members": support,
            "paths": {"work": work_rel, "state": state_rel, "acquisition": acq_rel,
                      "descriptor": descriptor_rel, "support": support_rel, "credit": credit_rel},
            "before": {rel: sha256_file(_io_path(root / rel)) for rel in (work_rel, state_rel, acq_rel, descriptor_rel)}}


def evidence(root: Path, selected_ids: tuple[str, ...] = IDS) -> dict:
    original = _record(root, ORIGINAL_PACKET)
    if original.get("contract") != "ocd-library-sidecar-batch-v1":
        raise PipelineError("original source packet contract differs")
    rows = {item["work_id"]: item for item in original["entries"] if item["work_id"] in IDS}
    if set(rows) != set(IDS) or any(work_id not in IDS for work_id in selected_ids):
        raise PipelineError("original source packet lacks a correction work")
    return {"contract": CONTRACT, "original_packet": {"path": ORIGINAL_PACKET,
            "sha256": sha256_file(_io_path(root / ORIGINAL_PACKET))},
            "works": [_one(root, rows[work_id]) for work_id in selected_ids]}


def _proposed(root: Path, row: dict) -> dict[str, dict | str]:
    work_id, paths = row["work_id"], row["paths"]
    acquisition = copy.deepcopy(_record(root, paths["acquisition"]))
    ordered = row["ordered_text_members"]
    acquisition["retained_files"] = [dict(item, media_type="application/xhtml+xml",
                                          scope=f"OPF spine position {index} of {len(ordered)}")
                                     for index, item in enumerate(ordered, 1)]
    acquisition["source_scope"] = (f"{len(ordered)} complete retained XHTML text members in exact OPF spine order. "
                                    f"The other {len(row['support_members'])} checkout files are separately hash-bound "
                                    "support, including the OPF, images, styles, navigation, and repository files; "
                                    "they are not reconstruction text.")
    descriptor = source_member_set_bytes(acquisition)
    acquisition["source_bytes"] = len(descriptor)
    acquisition["source_sha256"] = hashlib.sha256(descriptor).hexdigest()
    acquisition["warnings"] = list(acquisition.get("warnings", [])) + [
        f"Complete checkout support is bound in {paths['support']}; source text is only the OPF spine XHTML."]
    validate_record("acquisition", acquisition, context=paths["acquisition"])
    work = copy.deepcopy(load_work(_io_path(root / paths["work"])))
    for rel in (PACKET_REL, paths["support"], paths["credit"]):
        if rel not in work["evidence"]:
            work["evidence"].append(rel)
    validate_identity_update(load_work(_io_path(root / paths["work"])), work)
    validate_record("work", work, context=work_id)
    support = {"contract": "ocd-retained-checkout-support-v1", "work_id": work_id,
               "source_root": row["source_root"], "opf": row["opf"],
               "text_member_count": len(ordered), "support_members": row["support_members"]}
    credit = (f"# Source and credit — {work_id}\n\n"
              f"Standard Ebooks electronic witness: {len(ordered)} retained XHTML text files in "
              f"the exact reading order of {row['opf']['path']} (SHA-256 {row['opf']['sha256']}). "
              f"The other {len(row['support_members'])} checkout files are retained and hash-bound "
              f"in {paths['support']} as supporting material, not text source. The retained "
              "Standard Ebooks license and attribution remain subject to review. This acquisition "
              "does not itself establish accepted TEI, rights clearance, or publication authorization.\n")
    return {paths["work"]: work, paths["acquisition"]: acquisition,
            paths["descriptor"]: json.loads(descriptor), paths["support"]: support,
            paths["credit"]: credit}


def stage(root: Path, destination: Path) -> dict:
    root, destination = root.resolve(), destination.resolve()
    if destination.exists():
        raise PipelineError(f"stage destination exists: {destination}")
    packet = evidence(root)
    packet_path = _io_path(root / PACKET_REL)
    if packet_path.exists():
        if _record(root, PACKET_REL) != packet:
            raise PipelineError("existing correction packet differs")
    else:
        write_json(packet_path, packet)
    destination.mkdir(parents=True)
    storage = root / ".ocd-storage.json"
    if storage.is_file():
        shutil.copy2(storage, destination / ".ocd-storage.json")
    files = []
    for row in packet["works"]:
        for rel, value in _proposed(root, row).items():
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
    for row in packet["works"]:
        validate_acquisition(_io_path(destination / row["paths"]["acquisition"]), root=_io_path(destination))
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    receipt = stage(args.repository_root, args.destination)
    print(json.dumps({"files": len(receipt["files"]), "destination": str(args.destination)}, sort_keys=True))


if __name__ == "__main__":
    main()
