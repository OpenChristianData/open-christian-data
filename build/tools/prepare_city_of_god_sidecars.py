"""Stage City of God's two retained electronic witnesses as separate sidecars.

This source-accounting stage does not promote either technical TEI candidate.
"""
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


WORK_ID = "augustine-city-of-god"
CONTRACT = "ocd-city-of-god-two-edition-sidecar-stage-v1"
PACKET_REL = "plans/2026-09-22-source-preflight/city-of-god-two-edition-sidecar-packet-20260926.json"
SOURCE_ROOT = "raw/standard_ebooks/augustine-of-hippo_the-city-of-god_marcus-dods_george-wilson_j-j-smith"
PROFILE_REL = "sources/city-of-god/city-of-god.reconstruction-profile.json"
PRINT_REL = "sources/city-of-god/print-acquisitions.json"
DODS_MANIFEST = "sources/city-of-god/city-of-god-dods-1871.source-manifest.json"
NPNF_MANIFEST = "sources/city-of-god/city-of-god-npnf-1887.source-manifest.json"
DODS_CONFIG = "sources/standard-ebooks/augustine-of-hippo_the-city-of-god_marcus-dods_george-wilson_j-j-smith/config.json"
NPNF_CONFIG = "sources/structured-text/augustine-city-of-god/config.json"


def _repo_json(root: Path, rel: str) -> dict:
    return json.loads(_io_path(resolve_repo_path(root, rel)).read_text(encoding="utf-8"))


def _member(root: Path, rel: str) -> dict:
    path = _io_path(resolve_repo_path(root, rel))
    if not path.is_file():
        raise PipelineError(f"missing retained member: {rel}")
    return {"path": rel, "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def _evidence(root: Path) -> dict:
    profile = _repo_json(root, PROFILE_REL)
    if profile.get("contract") != "ocd-city-of-god-reconstruction-profile-v1":
        raise PipelineError("City of God profile contract differs")
    standard = profile["standard_scope"]
    if standard["root"] != SOURCE_ROOT or standard["member_count"] != 46:
        raise PipelineError("Standard Ebooks scope differs from bound profile")
    source_dir = _io_path(resolve_repo_path(root, SOURCE_ROOT))
    files = sorted(p for p in source_dir.rglob("*") if p.is_file() and ".git" not in p.parts)
    if len(files) != 46:
        raise PipelineError(f"Standard Ebooks tree differs: {len(files)} files")
    all_members = [_member(root, f"{SOURCE_ROOT}/{p.relative_to(source_dir).as_posix()}") for p in files]
    if sum(item["bytes"] for item in all_members) != standard["bytes"]:
        raise PipelineError("Standard Ebooks tree bytes differ from bound profile")
    opf_rel = f"{SOURCE_ROOT}/src/epub/content.opf"
    opf_path = _io_path(resolve_repo_path(root, opf_rel))
    tree = etree.parse(str(opf_path), etree.XMLParser(resolve_entities=False, no_network=True))
    ns = {"opf": "http://www.idpf.org/2007/opf"}
    manifest = {node.get("id"): node.get("href") for node in tree.xpath("//opf:manifest/opf:item", namespaces=ns)}
    spine_ids = [node.get("idref") for node in tree.xpath("//opf:spine/opf:itemref", namespaces=ns)]
    spine = [manifest.get(identifier) for identifier in spine_ids]
    if (len(spine) != 31 or len(set(spine)) != 31
            or any(not isinstance(item, str) or not item.startswith("text/") or not item.endswith(".xhtml") for item in spine)
            or {Path(item).stem for item in spine if Path(item).stem.startswith("book-")} != {f"book-{n}" for n in range(1, 23)}):
        raise PipelineError("Standard Ebooks OPF spine or 22-book scope differs")
    text_rel = [f"{SOURCE_ROOT}/src/epub/{item}" for item in spine]
    source_members = [_member(root, rel) for rel in text_rel]
    if len(set(text_rel)) != len(text_rel):
        raise PipelineError("duplicate Standard Ebooks source member")
    support = [item for item in all_members if item["path"] not in set(text_rel)]
    if len(support) != 15 or f"{SOURCE_ROOT}/src/epub/toc.xhtml" not in {item["path"] for item in support}:
        raise PipelineError("Standard Ebooks support member set differs")
    ccel = _member(root, profile["ccel_scope"]["path"])
    if any(ccel[key] != profile["ccel_scope"][key] for key in ("path", "bytes", "sha256")):
        raise PipelineError("CCEL source differs from profile")
    xml = etree.parse(str(_io_path(resolve_repo_path(root, ccel["path"]))),
                      etree.XMLParser(resolve_entities=False, no_network=True))
    matches = xml.xpath("/ThML/ThML.body/div1[@id=$id]", id=profile["ccel_scope"]["city_div1_id"])
    doctrine = xml.xpath("/ThML/ThML.body/div1[@id='v']")
    if len(matches) != 1 or len(doctrine) != 1 or "City of God" not in (matches[0].get("title") or ""):
        raise PipelineError("City of God CCEL div1 work boundary differs")
    titles = xml.xpath("/ThML/ThML.head//DC.Title[not(@sub)]/text()")
    if len(titles) != 1:
        raise PipelineError("CCEL volume title is ambiguous")
    print_record = _repo_json(root, PRINT_REL)
    controls = [_member(root, member["path"]) for acquisition in print_record["acquisitions"]
                for member in acquisition["members"]]
    if (len(controls) != profile["print_scope"]["member_count"]
            or sum(item["bytes"] for item in controls) != profile["print_scope"]["bytes"]):
        raise PipelineError("print control member count or bytes differ")
    declared = [member for acquisition in print_record["acquisitions"] for member in acquisition["members"]]
    if any(any(actual[key] != expected[key] for key in ("path", "bytes", "sha256"))
           for actual, expected in zip(controls, declared)):
        raise PipelineError("print control bytes differ")
    refs = {}
    for label, rel in (("dods", DODS_MANIFEST), ("npnf", NPNF_MANIFEST)):
        current = _repo_json(root, rel)
        if current.get("edition") != ("dods-1871" if label == "dods" else "npnf-1887"):
            raise PipelineError(f"{label} route manifest edition differs")
        authorities = current.get("authorities", [])
        for required in (opf_rel, ccel["path"], PRINT_REL, PROFILE_REL, DODS_CONFIG, NPNF_CONFIG):
            matches = [item for item in authorities if item.get("path") == required]
            if len(matches) != 1:
                raise PipelineError(f"{label} route manifest lacks {required}")
            actual = _member(root, required)
            if any(actual[key] != matches[0].get(key) for key in ("path", "bytes", "sha256")):
                raise PipelineError(f"{label} route authority changed: {required}")
        refs[label] = {"path": rel, "sha256": sha256_file(root / rel)}
    if sha256_file(root / PRINT_REL) != profile["print_scope"]["manifest_sha256"]:
        raise PipelineError("City of God print evidence changed")
    configs = {"dods": _repo_json(root, DODS_CONFIG), "npnf": _repo_json(root, NPNF_CONFIG)}
    if (configs["dods"].get("source_revision") != standard["commit"]
            or configs["npnf"].get("source_hash") != f"sha256:{ccel['sha256']}"):
        raise PipelineError("City of God source config differs")
    return {"contract": CONTRACT, "work_id": WORK_ID, "source_profile": {"path": PROFILE_REL, "sha256": sha256_file(root / PROFILE_REL)},
            "route_manifests": refs, "print_controls": {"path": PRINT_REL, "sha256": sha256_file(root / PRINT_REL),
                                                       "members": controls},
            "standard_ebooks": {"root": SOURCE_ROOT, "commit": standard["commit"], "opf": _member(root, opf_rel),
                                "ordered_text_members": source_members, "support_members": support,
                                "url": configs["dods"]["source_url"]},
            "ccel": {"source": ccel, "work_locator": ccel["path"] + "#iv",
                     "containing_title": titles[0], "url": configs["npnf"]["source_url"]}}


def _credit(packet: dict) -> str:
    return (
        "# Source and credit — The City of God\n\n"
        "Two distinct retained electronic witnesses are accounted for:\n\n"
        f"- Standard Ebooks, commit {packet['standard_ebooks']['commit']}: "
        "31 XHTML text members in exact OPF spine order, including 22 books. "
        "The OPF, navigation, styles, images, and repository files are separately bound support.\n"
        f"- CCEL NPNF1-02: {packet['ccel']['source']['path']} "
        f"(SHA-256 {packet['ccel']['source']['sha256']}); City of God is body div1 id=iv.\n\n"
        "The retained 1871 and 1887 print scans and their OCR derivatives are "
        "comparison controls, not reconstruction text. Standard Ebooks editorial "
        "CC0 and CCEL public-domain/permission statements are recorded source claims; "
        "rights, attribution, acceptance, and publication require separate review.\n"
    )


def stage(root: Path, destination: Path) -> dict:
    root, destination = root.resolve(), destination.resolve()
    if destination.exists():
        raise PipelineError(f"stage destination already exists: {destination}")
    work_rel = f"library/works/{WORK_ID}/work.json"
    state_rel = f"library/works/{WORK_ID}/state.json"
    work, state = load_work(root / work_rel), load_state(root / state_rel)
    if work["textual_forms"] or state["targets"]:
        raise PipelineError("City of God is no longer identity-only")
    before = {"work": sha256_file(root / work_rel), "state": sha256_file(root / state_rel)}
    packet = _evidence(root)
    packet["before"] = before
    packet_path = root / PACKET_REL
    if packet_path.exists():
        if _repo_json(root, PACKET_REL) != packet:
            raise PipelineError(f"existing packet differs: {packet_path}")
    else:
        write_json(packet_path, packet)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    updated_work, updated_state = copy.deepcopy(work), copy.deepcopy(state)
    credit_rel = f"library/works/{WORK_ID}/SOURCE_CREDIT.md"
    if (root / credit_rel).exists():
        raise PipelineError("City of God source credit already exists")
    output: list[tuple[str, dict | str]] = []
    for label in ("dods", "npnf"):
        form_id = f"{WORK_ID}-{label}-retained-en"
        edition_id = f"{WORK_ID}-{label}-retained-electronic"
        acquisition_id = f"{WORK_ID}-{label}-acquired"
        edition_dir = f"library/works/{WORK_ID}/forms/{form_id}/editions/{edition_id}"
        acquisition_rel = f"{edition_dir}/acquisitions/{acquisition_id}.json"
        if (root / acquisition_rel).exists():
            raise PipelineError(f"City of God acquisition already exists: {acquisition_rel}")
        if label == "dods":
            ordered = packet["standard_ebooks"]["ordered_text_members"]
            scope = ("31 complete retained Standard Ebooks XHTML text members in OPF spine order, "
                     "including 22 books; navigation, OPF, styles, images, and repository files "
                     "are separately hash-bound support, not source text.")
            retained = [dict(item, media_type="application/xhtml+xml",
                             scope=f"OPF spine position {index} of {len(ordered)}")
                        for index, item in enumerate(ordered, 1)]
            title = "Standard Ebooks Dods-lineage electronic witness of The City of God"
            provider, url = "Standard Ebooks", packet["standard_ebooks"]["url"]
            warning = "The 1871 print scans are comparison controls; this XHTML acquisition does not establish byte identity with that print edition."
        else:
            source = packet["ccel"]["source"]
            scope = (f"Complete acquired CCEL XML volume {source['path']}; The City of God is "
                     f"the distinct body div1 id=iv at {packet['ccel']['work_locator']}. "
                     "Other body divisions remain acquired context, not City of God text.")
            retained = [dict(source, media_type="application/xml", scope=scope)]
            title = "CCEL NPNF1-02 electronic witness of The City of God"
            provider, url = "CCEL", packet["ccel"]["url"]
            warning = "The CCEL 1890 printSourceInfo and undated reprint carrier claims conflict; no exact 1890 print edition is asserted."
        edition = {"edition_id": edition_id, "title": title, "language": "en",
                   "acquisition_ids": [acquisition_id]}
        if label == "npnf":
            edition["containing_source"] = {"title": packet["ccel"]["containing_title"],
                                            "locator": packet["ccel"]["work_locator"],
                                            "evidence": [PACKET_REL, packet["ccel"]["work_locator"]]}
        updated_work["textual_forms"].append({"textual_form_id": form_id, "language": "en", "editions": [edition]})
        acquisition = {"schema_version": "2.0", "acquisition_id": acquisition_id,
                       "edition_id": edition_id, "provider": provider, "url": url,
                       "route": "born-digital", "retained_files": retained,
                       "source_scope": scope,
                       "warnings": [warning, "Source attribution and rights need separate review; acquired source does not establish accepted TEI or publication authorization."]}
        if label == "dods":
            acquisition["source_kind"] = "retained-member-set"
            descriptor_rel = f"{edition_dir}/source-member-set.json"
            acquisition["source_path"] = descriptor_rel
            member_set = source_member_set_bytes(acquisition)
            acquisition["source_bytes"] = len(member_set)
            acquisition["source_sha256"] = hashlib.sha256(member_set).hexdigest()
            output.append((descriptor_rel, json.loads(member_set)))
        else:
            acquisition.update({"source_path": source["path"], "source_bytes": source["bytes"],
                                "source_sha256": source["sha256"]})
        validate_record("acquisition", acquisition, context=acquisition_rel)
        output.append((acquisition_rel, acquisition))
        evidence = [PACKET_REL, packet["route_manifests"][label]["path"], PROFILE_REL,
                    PRINT_REL, credit_rel, acquisition_rel]
        if label == "dods":
            evidence.append(acquisition["source_path"])
        for target_id, kind in ((acquisition_id, "acquisition"), (edition_id, "edition")):
            updated_state["targets"].append({"target_id": target_id, "target_type": kind,
                                             "stage": "acquired", "updated_at": now, "evidence": evidence})
    for rel in (PACKET_REL, PROFILE_REL, PRINT_REL, DODS_MANIFEST, NPNF_MANIFEST, credit_rel,
                packet["ccel"]["work_locator"]):
        if rel not in updated_work["evidence"]:
            updated_work["evidence"].append(rel)
    validate_identity_update(work, updated_work)
    validate_record("work", updated_work, context=WORK_ID)
    validate_record("state", updated_state, context=WORK_ID)
    output.extend([(work_rel, updated_work), (state_rel, updated_state), (credit_rel, _credit(packet))])
    destination.mkdir(parents=True)
    storage_config = root / ".ocd-storage.json"
    if storage_config.is_file():
        shutil.copy2(storage_config, destination / ".ocd-storage.json")
    for rel in (PACKET_REL, PROFILE_REL, PRINT_REL, DODS_MANIFEST, NPNF_MANIFEST):
        target = _io_path(destination / rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / rel, target)
    files = []
    for rel, value in output:
        target = _io_path(destination / rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(value, str):
            target.write_text(value, encoding="utf-8")
        else:
            write_json(target, value)
        live = root / rel
        files.append({"path": rel, "before_sha256": sha256_file(live) if live.is_file() else None,
                      "proposed_sha256": sha256_file(target)})
    receipt = {"contract": CONTRACT, "packet_path": PACKET_REL,
               "packet_sha256": sha256_file(packet_path),
               "files": sorted(files, key=lambda item: item["path"])}
    write_json(_io_path(destination / "receipt.json"), receipt)
    for rel, _ in output:
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

