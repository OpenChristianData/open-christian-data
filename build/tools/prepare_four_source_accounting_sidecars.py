"""Stage four remaining source-accounting sidecars from exact retained files."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError, canonical_bytes, load_json, sha256_file, write_json
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import validate_identity_update, validate_record
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.install_accepted import _files, _io_path


WORK_IDS = ("drc", "maclaren-expositions", "robertson-word-pictures-vol1", "westminster-shorter-catechism")
PACKET_REL = "plans/2026-09-22-source-preflight/four-complex-source-sidecar-packet-20260926-v2.json"
RECEIPT_REL = "plans/2026-09-22-source-preflight/four-complex-source-sidecar-stage-20260926-v2.json"
CONTRACT = "ocd-four-complex-source-sidecars-v1"


def _ref(root: Path, rel: str) -> dict[str, str]:
    path = resolve_repo_path(root, rel)
    if not path.is_file():
        raise PipelineError(f"missing retained authority: {rel}")
    return {"path": rel, "sha256": sha256_file(_io_path(path))}


def _json(root: Path, rel: str) -> dict[str, Any]:
    return load_json(_io_path(resolve_repo_path(root, rel)))


def _authority(root: Path, manifest: dict[str, Any], rel: str, role: str) -> dict[str, Any]:
    found = [item for item in manifest.get("authorities", []) if isinstance(item, dict)
             and item.get("path") == rel and item.get("role") == role]
    if len(found) != 1:
        raise PipelineError(f"manifest does not uniquely bind {role}: {rel}")
    item = found[0]
    path = resolve_repo_path(root, rel)
    if (not path.is_file() or path.stat().st_size != item.get("bytes")
            or sha256_file(_io_path(path)) != item.get("sha256")):
        raise PipelineError(f"retained authority differs: {rel}")
    return item


def _source(item: dict[str, Any], url: str, provider: str, media_type: str, scope: str) -> dict[str, Any]:
    return {"path": item["path"], "bytes": item["bytes"], "sha256": item["sha256"],
            "url": url, "provider": provider, "media_type": media_type, "scope": scope}


def _drc(root: Path) -> dict[str, Any]:
    wid = "drc"
    manifest_rel = "sources/douay-rheims-1899/douay-rheims-1899.source-manifest.json"
    acquisitions_rel = "sources/douay-rheims-1899/acquisitions.json"
    config_rel = "sources/bible-text/drc/config.json"
    metadata_rel = "metadata/source-evidence/catalog/drc.json"
    source_rel = "raw/bible_databases/formats/json/DRC.json"
    manifest, acquisitions, config, metadata = (_json(root, rel) for rel in
                                                (manifest_rel, acquisitions_rel, config_rel, metadata_rel))
    if (manifest.get("contract") != "ocd-source-manifest-v1"
            or manifest.get("source_id") != "douay-rheims-american-1899-retained-witnesses"
            or acquisitions.get("work_id") != "douay-rheims-bible"
            or config.get("resource_id") != wid or config.get("source_file") != source_rel
            or metadata.get("subject") != {"id": wid, "kind": "catalog"}):
        raise PipelineError("DRC identity, Scrollmapper route, or 1899 comparison boundary differs")
    source = _authority(root, manifest, source_rel, "primary-source")
    _authority(root, manifest, acquisitions_rel, "source-acquisition-evidence")
    _authority(root, manifest, config_rel, "source-identity-and-rights-config")
    matches = [a for a in acquisitions.get("acquisitions", []) if a.get("acquisition_id") == "scrollmapper-drc-json-a228a19a"]
    if (len(matches) != 1 or matches[0].get("members") != [
            {key: source[key] for key in ("path", "bytes", "sha256")}]
            or matches[0].get("source_record") != config.get("source_url")
            or matches[0].get("carrier_role") != "secondary-structured-text-witness"):
        raise PipelineError("DRC Scrollmapper source record or exact JSON member differs")
    scope = ("The single complete retained Scrollmapper DRC.json Challoner witness, including empty carrier slots. "
             "Its use as a secondary witness in a separate 1899 reconstruction does not equate this catalog work "
             "with the 1899 eBible or print witnesses.")
    return {"evidence": [_ref(root, rel) for rel in (manifest_rel, acquisitions_rel, config_rel, metadata_rel)],
            "sources": [_source(source, config["source_url"], "scrollmapper/bible_databases", "application/json", scope)],
            "warnings": ["Scrollmapper/CrossWire derivation is source lineage, not an accepted 1899 edition identity or rights clearance.",
                         "Attribution, accepted text, human review, and publication authorization remain separate."],
            "rights": "No new rights clearance; source-specific redistribution review remains open."}


def _maclaren(root: Path) -> dict[str, Any]:
    wid = "maclaren-expositions"
    manifest_rel = "sources/sermons/maclaren-expositions/maclaren-expositions.source-manifest.json"
    profile_rel = "sources/sermons/maclaren-expositions/maclaren-expositions.reconstruction-profile.json"
    inventory_rel = "raw/gutenberg/sermons/PG_SERMON_INVENTORY.md"
    readme_rel = "sources/sermons/maclaren-expositions/README.source.md"
    metadata_rel = f"metadata/source-evidence/catalog/{wid}.json"
    manifest, profile, metadata = (_json(root, rel) for rel in (manifest_rel, profile_rel, metadata_rel))
    if (manifest.get("contract") != "ocd-source-manifest-v1"
            or manifest.get("source_id") != "maclaren-expositions-pg-cohort-15-retained"
            or manifest.get("work_id") != wid or profile.get("work_id") != wid
            or profile.get("scope", {}).get("included_member_count") != 15
            or metadata.get("subject") != {"id": wid, "kind": "catalog"}):
        raise PipelineError("Maclaren fifteen-volume identity differs")
    for rel, role in ((profile_rel, "complete-source-feature-profile"),
                      (inventory_rel, "source-scope-inventory"), (readme_rel, "source-attribution-evidence")):
        _authority(root, manifest, rel, role)
    primary = [item for item in manifest["authorities"] if item.get("role") == "primary-source"]
    members = profile.get("members")
    if not isinstance(members, list) or len(primary) != len(members) or len(primary) != 15:
        raise PipelineError("Maclaren source/profile member census differs")
    sources = []
    for index, (item, member) in enumerate(zip(primary, members), 1):
        if (any(item.get(key) != member.get(key) for key in ("path", "bytes", "sha256"))
                or member.get("inventory_order") != index or not re.fullmatch(r"[0-9]+", member.get("pg_id", ""))
                or item.get("path") != f"raw/gutenberg/sermons/maclaren/pg{member['pg_id']}.txt"):
            raise PipelineError(f"Maclaren inventory member differs at {index}")
        _authority(root, manifest, item["path"], "primary-source")
        header = resolve_repo_path(root, item["path"]).read_bytes()[:3000].decode("utf-8-sig", errors="replace")
        if f"www.gutenberg.org/ebooks/{member['pg_id']}" not in header:
            raise PipelineError(f"Maclaren direct Gutenberg URL absent from retained header: {item['path']}")
        sources.append(_source(item, f"https://www.gutenberg.org/ebooks/{member['pg_id']}",
                               "Project Gutenberg", "text/plain",
                               f"Complete retained PG #{member['pg_id']} electronic volume; one of 15 in the bounded collection cohort. "
                               "No individual exposition split or printed-edition identity is inferred."))
    return {"evidence": [_ref(root, rel) for rel in (manifest_rel, profile_rel, inventory_rel, readme_rel, metadata_rel)],
            "sources": sources,
            "warnings": ["Retain the Project Gutenberg license material and attribution carried in each source file; rights vary by jurisdiction.",
                         "Collection and print-edition relationships, accepted text, human review, and publication authorization remain unresolved."],
            "rights": "Project Gutenberg license accompanies all 15 complete retained electronic volumes."}


def _robertson(root: Path) -> dict[str, Any]:
    wid = "robertson-word-pictures-vol1"
    base = "sources/commentaries/robertson-word-pictures-vol1"
    manifest_rel, profile_rel, readme_rel = (f"{base}/{name}" for name in
                                            ("source-manifest.json", "source-feature-profile.json", "README.source.md"))
    metadata_rel = f"metadata/source-evidence/catalog/{wid}.json"
    config_rels = ["sources/commentaries/robertson-word-pictures-vol1-matthew/config.json",
                   "sources/commentaries/robertson-word-pictures-vol1-mark/config.json"]
    manifest, profile, metadata = (_json(root, rel) for rel in (manifest_rel, profile_rel, metadata_rel))
    if (manifest.get("work_id") != wid or manifest.get("source_id") != "robertson-word-pictures-vol1-retained-thml"
            or metadata.get("subject") != {"id": wid, "kind": "catalog"}):
        raise PipelineError("Robertson volume identity differs")
    for rel, role in ((profile_rel, "complete-source-feature-profile"),
                      (readme_rel, "source-attribution-readme")):
        _authority(root, manifest, rel, role)
    primary = [item for item in manifest["authorities"] if item.get("role") == "primary-source"]
    if len(primary) != 2 or len(profile.get("members", [])) != 2:
        raise PipelineError("Robertson Matthew/Mark member count differs")
    sources = []
    for item, member, config_rel, book, slug in zip(primary, profile["members"], config_rels, ("Matthew", "Mark"), ("matt", "mark")):
        config = _json(root, config_rel)
        if (item["path"] != f"raw/ccel/robertson-word-pictures/robertson_at_wp_{slug}.xml"
                or item["sha256"] != member.get("sha256") or item["bytes"] != member.get("bytes")
                or config.get("resource_id") != wid or config.get("source_hash") != "sha256:" + item["sha256"]
                or config.get("source_url") != f"https://www.ccel.org/ccel/robertson_at/wp_{slug}.xml"):
            raise PipelineError(f"Robertson {book} direct CCEL source/config differs")
        _authority(root, manifest, item["path"], "primary-source")
        sources.append(_source(item, config["source_url"], "Christian Classics Ethereal Library",
                               "application/xml", f"Complete retained {book} ThML component of assigned Vol. I cohort; "
                               "other volumes and print-edition completeness remain unresolved."))
    return {"evidence": [_ref(root, rel) for rel in (manifest_rel, profile_rel, readme_rel, metadata_rel, *config_rels)],
            "sources": sources,
            "warnings": ["CCEL copyright comment and empty DC.Rights fields require source-specific rights review and data-path attribution before publication.",
                         "Only assigned Matthew/Mark components are acquired; accepted text, human review, and publication authorization remain separate."],
            "rights": "Rights unresolved; CCEL header statements do not establish redistribution clearance."}


def _westminster(root: Path) -> dict[str, Any]:
    wid = "westminster-shorter-catechism"
    base = "sources/catechisms/westminster-shorter-catechism"
    manifest_rel = f"{base}/{wid}.source-manifest.json"
    profile_rel = f"{base}/{wid}.reconstruction-profile.json"
    outer_rel = f"{base}/{wid}.outer-html-profile.json"
    config_rel = f"{base}/config.json"
    metadata_rel = f"metadata/source-evidence/catalog/{wid}.json"
    manifest, profile, config, metadata = (_json(root, rel) for rel in
                                          (manifest_rel, profile_rel, config_rel, metadata_rel))
    if (manifest.get("source_id") != "westminster-shorter-catechism-three-retained-witnesses"
            or profile.get("identity", {}).get("work_id") != wid
            or profile.get("identity", {}).get("edition_status") != "unresolved; no retained authority selects or reconciles a reading"
            or config.get("id") != wid or metadata.get("subject") != {"id": wid, "kind": "catalog"}):
        raise PipelineError("Westminster three-witness or unresolved-edition identity differs")
    for rel, role in ((profile_rel, "complete-source-feature-profile"),
                      (outer_rel, "complete-source-carrier-profile"),
                      (config_rel, "local-metadata-claim-evidence")):
        _authority(root, manifest, rel, role)
    primary = [item for item in manifest["authorities"] if item.get("role") == "primary-source"]
    witnesses = profile.get("source_scope", {}).get("witnesses")
    if not isinstance(witnesses, list) or len(primary) != len(witnesses) or len(primary) != 3:
        raise PipelineError("Westminster three-source inventory differs")
    for item, witness in zip(primary, witnesses):
        if any(item.get(key) != witness.get(key) for key in ("path", "bytes", "sha256")):
            raise PipelineError("Westminster source witness/profile bytes differ")
        _authority(root, manifest, item["path"], "primary-source")
    rights_rels = [item["path"] for item in manifest["authorities"] if item.get("role") == "rights-evidence"]
    if len(rights_rels) != 3:
        raise PipelineError("Westminster rights evidence count differs")
    for rel in rights_rels:
        _authority(root, manifest, rel, "rights-evidence")
    readme = resolve_repo_path(root, "raw/TheologAI/README.md").read_text(encoding="utf-8")
    if "https://theologai.xyz" not in readme:
        raise PipelineError("TheologAI provider website is not evidenced")
    if (config.get("source", {}).get("repository") != "https://github.com/NonlinearFruit/Creeds.json"
            or config.get("secondary_sources", [{}])[0].get("url") != "https://thewestminsterstandard.org/westminster-shorter-catechism/"):
        raise PipelineError("Westminster Creeds or HTML provider URL differs")
    urls = [config["source"]["repository"], "https://theologai.xyz",
            config["secondary_sources"][0]["url"]]
    providers = ["Creeds.json", "TheologAI", "The Westminster Standard"]
    media = ["application/json", "application/json", "text/html"]
    scopes = ["Complete retained Creeds.json provider Q&A rendering; print edition unresolved.",
              "Complete retained TheologAI historical-document rendering; exact upstream file URL unrecorded, rights unresolved.",
              "Complete retained Westminster Standard HTML page; Q&A and proof apparatus plus outer carrier, rights unresolved."]
    sources = [_source(item, url, provider, kind, scope) for item, url, provider, kind, scope in
               zip(primary, urls, providers, media, scopes)]
    for item, rights in zip(sources, (
        "Creeds.json README supplies Unlicense evidence, and this catechism is not among its named exceptions; historical-text rights still require review.",
        "TheologAI ISC license covers software, not this historical-document rendering; redistribution rights are unresolved.",
        "Cached Westminster Standard page has a 2016 copyright footer and no retained text or proof-apparatus license; rights are unresolved.",
    )):
        item["rights"] = rights
    return {"evidence": [_ref(root, rel) for rel in (manifest_rel, profile_rel, outer_rel, config_rel, metadata_rel,
                                                     *rights_rels)],
            "sources": sources,
            "warnings": ["Creeds.json Unlicense evidence does not settle the other provider renderings' rights.",
                         "TheologAI software ISC license does not establish historical-document redistribution rights; only its provider website, not an exact file URL, is retained.",
                         "Westminster Standard cached page has a 2016 copyright footer and no retained text/proof-apparatus license; human rights review, accepted text, and publication authorization remain open."],
            "rights": "Three distinct provider rights positions; no combined rights clearance."}


def evidence(root: Path) -> dict[str, Any]:
    root = root.resolve()
    routes = {"drc": _drc(root), "maclaren-expositions": _maclaren(root),
              "robertson-word-pictures-vol1": _robertson(root),
              "westminster-shorter-catechism": _westminster(root)}
    for wid, route in routes.items():
        work_rel, state_rel = (f"library/works/{wid}/{name}.json" for name in ("work", "state"))
        work, state = _json(root, work_rel), _json(root, state_rel)
        if (work.get("work_id") != wid or state.get("work_id") != wid
                or work.get("textual_forms") != [] or state.get("targets") != []
                or f"metadata/source-evidence/catalog/{wid}.json" not in work.get("evidence", [])):
            raise PipelineError(f"{wid} is no longer an identity-only sidecar")
        route["before"] = {"work": _ref(root, work_rel), "state": _ref(root, state_rel)}
    return {"contract": CONTRACT, "works": routes}


def _credit(wid: str, route: dict[str, Any]) -> str:
    sources = "\n".join(f"- {s['provider']}: `{s['path']}`; {s['url']}"
                        + (f"; rights: {s['rights']}" if "rights" in s else "")
                        for s in route["sources"])
    return (f"# Source accounting: {wid}\n\n{sources}\n\n"
            f"Rights: {route['rights']}\n\n"
            + "\n".join(f"- {w}" for w in route["warnings"]) + "\n")


def _design(wid: str, route: dict[str, Any]) -> tuple[list[dict[str, Any]], list[list[int]]]:
    count = len(route["sources"])
    if wid == "westminster-shorter-catechism":
        forms = []
        for index, label in enumerate(("creeds-json", "theologai-json", "westminster-standard-html")):
            forms.append({"form_id": f"{wid}-{label}-en", "edition_id": f"{wid}-{label}-retained",
                          "title": f"Westminster Shorter Catechism, retained {label} provider rendering",
                          "acquisition_indices": [index]})
        return forms, [[index] for index in range(3)]
    form_id = {"drc": "drc-scrollmapper-retained-en",
               "maclaren-expositions": "maclaren-expositions-pg-retained-en",
               "robertson-word-pictures-vol1": "robertson-word-pictures-vol1-ccel-retained-en"}[wid]
    edition_id = {"drc": "drc-scrollmapper-digital-witness",
                  "maclaren-expositions": "maclaren-expositions-pg-fifteen-volume-cohort",
                  "robertson-word-pictures-vol1": "robertson-word-pictures-vol1-matthew-mark-ccel"}[wid]
    title = {"drc": "Douay-Rheims Challoner Scrollmapper digital witness",
             "maclaren-expositions": "Maclaren Expositions, fifteen retained Project Gutenberg electronic volumes",
             "robertson-word-pictures-vol1": "Robertson Word Pictures Vol. I, retained CCEL Matthew and Mark components"}[wid]
    return [{"form_id": form_id, "edition_id": edition_id, "title": title,
             "acquisition_indices": list(range(count))}], [list(range(count))]


def proposed(root: Path, packet: dict[str, Any], now: str) -> dict[str, dict[str, bytes]]:
    if packet != evidence(root):
        raise PipelineError("four-work retained source or current sidecar evidence differs from reviewed packet")
    result: dict[str, dict[str, bytes]] = {}
    for wid in WORK_IDS:
        route = packet["works"][wid]
        work = copy.deepcopy(_json(root, f"library/works/{wid}/work.json"))
        state = copy.deepcopy(_json(root, f"library/works/{wid}/state.json"))
        prefix = f"library/works/{wid}/"
        credit_rel = prefix + "SOURCE_CREDIT.md"
        evidence_paths = [ref["path"] for ref in route["evidence"]] + [s["path"] for s in route["sources"]]
        work["evidence"].extend(path for path in evidence_paths if path not in work["evidence"])
        outputs: dict[str, bytes] = {credit_rel: _credit(wid, route).encode("utf-8")}
        forms, _ = _design(wid, route)
        for form_spec in forms:
            form_id, edition_id = form_spec["form_id"], form_spec["edition_id"]
            acquisition_ids = []
            for index in form_spec["acquisition_indices"]:
                source = route["sources"][index]
                stem = Path(source["path"]).stem.lower().replace("_", "-")
                aid = f"{wid}-{index + 1:02d}-{stem}-acquired"
                acquisition_ids.append(aid)
                rel = f"{prefix}forms/{form_id}/editions/{edition_id}/acquisitions/{aid}.json"
                retained = {key: source[key] for key in ("path", "bytes", "sha256", "media_type", "scope")}
                acquisition = {"schema_version": "2.0", "acquisition_id": aid, "edition_id": edition_id,
                               "provider": source["provider"], "url": source["url"], "retained_files": [retained],
                               "source_path": source["path"], "source_bytes": source["bytes"],
                               "source_sha256": source["sha256"], "source_scope": source["scope"],
                               "warnings": route["warnings"]}
                if "rights" in source:
                    acquisition["rights"] = source["rights"]
                validate_record("acquisition", acquisition, context=rel)
                outputs[rel] = canonical_bytes(acquisition)
                state["targets"].append({"target_id": aid, "target_type": "acquisition", "stage": "acquired",
                                         "updated_at": now, "evidence": [*evidence_paths, credit_rel, rel]})
            edition = {"edition_id": edition_id, "title": form_spec["title"], "language": "en",
                       "acquisition_ids": acquisition_ids}
            work["textual_forms"].append({"textual_form_id": form_id, "language": "en", "editions": [edition]})
            state["targets"].append({"target_id": edition_id, "target_type": "edition", "stage": "acquired",
                                     "updated_at": now, "evidence": [*evidence_paths, credit_rel,
                                                                     *[rel for rel in outputs if "/acquisitions/" in rel
                                                                       and f"/editions/{edition_id}/" in rel]]})
        validate_identity_update(_json(root, prefix + "work.json"), work)
        validate_record("work", work, context=wid)
        validate_record("state", state, context=wid)
        outputs[prefix + "work.json"] = canonical_bytes(work)
        outputs[prefix + "state.json"] = canonical_bytes(state)
        result[wid] = outputs
    return result


def stage(root: Path, destination: Path, now: str) -> dict[str, Any]:
    root, destination = root.resolve(), destination.resolve()
    if destination.exists() or root == destination or root in destination.parents:
        raise PipelineError("stage destination must be new and outside repository")
    packet = load_json(root / PACKET_REL)
    outputs = proposed(root, packet, now)
    receipt = {"contract": "ocd-four-complex-source-stage-v1", "packet_sha256": sha256_file(root / PACKET_REL),
               "entries": []}
    destination.mkdir(parents=True)
    storage = root / ".ocd-storage.json"
    if storage.is_file():
        shutil.copy2(storage, destination / ".ocd-storage.json")
    for route in packet["works"].values():
        for ref in route["evidence"]:
            rel = ref["path"]
            if not rel.startswith(("raw/", "reports/", "exports/")):
                target = _io_path(destination / rel)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(_io_path(root / rel), target)
    for wid in WORK_IDS:
        prefix = f"library/works/{wid}/"
        shutil.copytree(_io_path(root / prefix), _io_path(destination / prefix))
        entry = {"work_id": wid, "files": []}
        for rel, raw in outputs[wid].items():
            target = _io_path(destination / rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            current = root / rel
            entry["files"].append({"path": rel,
                                   "before_sha256": sha256_file(_io_path(current)) if current.is_file() else None,
                                   "proposed_sha256": hashlib.sha256(raw).hexdigest()})
        receipt["entries"].append(entry)
    write_json(_io_path(destination / "receipt.json"), receipt)
    return receipt


def preflight(root: Path, destination: Path) -> dict[str, Any]:
    root, destination = root.resolve(), destination.resolve()
    packet = load_json(root / PACKET_REL)
    receipt = load_json(_io_path(destination / "receipt.json"))
    if (receipt.get("contract") != "ocd-four-complex-source-stage-v1"
            or receipt.get("packet_sha256") != sha256_file(root / PACKET_REL)
            or [x.get("work_id") for x in receipt.get("entries", [])] != list(WORK_IDS)):
        raise PipelineError("four-work stage receipt differs from packet/work set")
    first_state = _json(destination, f"library/works/{WORK_IDS[0]}/state.json")
    now = first_state["targets"][-1]["updated_at"]
    outputs = proposed(root, packet, now)
    files = 0
    for entry in receipt["entries"]:
        wid = entry["work_id"]
        listed = entry.get("files")
        if (not isinstance(listed, list) or len(listed) != len(outputs[wid])
                or {x.get("path") for x in listed} != set(outputs[wid])):
            raise PipelineError(f"{wid} staged file set differs")
        for item in listed:
            rel = item["path"]
            current = root / rel
            before = sha256_file(_io_path(current)) if current.is_file() else None
            digest = hashlib.sha256(outputs[wid][rel]).hexdigest()
            if (item.get("before_sha256") != before or item.get("proposed_sha256") != digest
                    or sha256_file(_io_path(destination / rel)) != digest):
                raise PipelineError(f"{wid} staged/current file differs: {rel}")
            if "/acquisitions/" in rel:
                validate_acquisition(_io_path(destination / rel), root=_io_path(destination))
            files += 1
        prefix = f"library/works/{wid}/"
        before_tree = _files(root / prefix)
        after_tree = _files(destination / prefix)
        listed_rel = {Path(rel).relative_to(Path(prefix)).as_posix() for rel in outputs[wid]}
        if (set(after_tree) != set(before_tree) | listed_rel
                or any(after_tree[rel] != digest for rel, digest in before_tree.items() if rel not in listed_rel)):
            raise PipelineError(f"{wid} staged generation has unrelated changes")
        validate_state(_io_path(destination / prefix / Path("state.json")), root=_io_path(destination))
    return {"preflighted": len(WORK_IDS), "files": files}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--write-packet", action="store_true")
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    root = args.repository_root.resolve()
    if args.write_packet:
        path = root / PACKET_REL
        if path.exists():
            raise PipelineError(f"packet already exists: {path}")
        write_json(path, evidence(root))
        print(json.dumps({"packet": str(path)}, sort_keys=True))
    elif args.preflight:
        print(json.dumps(preflight(root, args.stage), sort_keys=True))
    else:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        receipt = stage(root, args.stage, now)
        print(json.dumps({"works": len(receipt["entries"]),
                          "files": sum(len(x["files"]) for x in receipt["entries"])}, sort_keys=True))


if __name__ == "__main__":
    main()
