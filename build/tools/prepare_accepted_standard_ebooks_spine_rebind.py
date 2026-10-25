"""Stage a complete source/acceptance rebind for three accepted Standard Ebooks works.

Historical review artifacts remain in the copied work generation. The new
generation changes only source classification, linked proofs, and TEI headers;
the accepted TEI text body must remain byte-identical.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError, sha256_file, write_json, canonical_bytes
from ocd_kernel.library.acquisitions import source_member_set_bytes, validate_acquisition
from ocd_kernel.library.identities import validate_identity_update, validate_record
from ocd_kernel.tei.acceptance import build_acceptance_record, make_file_binding, validate_acceptance, write_acceptance
from ocd_kernel.tei.install_accepted import _io_path
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


IDS = ("imitation-of-christ", "paradise-lost", "pilgrims-progress")
CONTRACT = "ocd-accepted-standard-ebooks-spine-rebind-v1"
PACKET_REL = "plans/2026-09-22-source-preflight/accepted-standard-ebooks-three-spine-rebind-packet-20260926.json"
REVISION = {"id": "standard-ebooks-spine-source-rebind-v1", "date": "2026-09-26",
            "note": "Rebound retained text to the OPF spine; checkout support is separately accounted for. Accepted text body is unchanged."}
NS = "http://www.tei-c.org/ns/1.0"


def _json(path: Path) -> dict:
    return json.loads(_io_path(path).read_text(encoding="utf-8"))


def _tree(directory: Path) -> dict[str, str]:
    directory = _io_path(directory)
    return {path.relative_to(directory).as_posix(): sha256_file(path)
            for path in directory.rglob("*") if path.is_file()}


def _paths(root: Path, work_id: str) -> dict[str, str]:
    work_rel = f"library/works/{work_id}"
    matches = list(_io_path(root / work_rel).rglob("acceptance.json"))
    if len(matches) != 1:
        raise PipelineError(f"{work_id} requires exactly one accepted edition")
    acceptance = matches[0].relative_to(_io_path(root)).as_posix()
    edition_rel = acceptance.rsplit("/", 1)[0]
    acquisitions = list(_io_path(root / edition_rel / "acquisitions").glob("*.json"))
    if len(acquisitions) != 1:
        raise PipelineError(f"{work_id} requires exactly one retained acquisition")
    return {"work": f"{work_rel}/work.json", "state": f"{work_rel}/state.json",
            "acceptance": acceptance, "master": f"{edition_rel}/master.tei.xml",
            "acquisition": acquisitions[0].relative_to(_io_path(root)).as_posix(),
            "integration": f"{work_rel}/integration/reviewed-standard-ebooks-v1",
            "support": f"{edition_rel}/retained-support.json"}


def _member(root: Path, rel: str) -> dict:
    path = _io_path(resolve_repo_path(root, rel))
    if not path.is_file():
        raise PipelineError(f"retained member missing: {rel}")
    return {"path": rel, "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def _one(root: Path, work_id: str) -> dict:
    paths = _paths(root, work_id)
    record = _json(root / paths["acceptance"])
    acquisition = _json(root / paths["acquisition"])
    if (record["identity"]["work_id"] != work_id
            or record["identity"]["acquisition_id"] != acquisition["acquisition_id"]
            or record["promotion"]["status"] != "promoted"
            or record["decision"]["human_decision"]["status"] != "not-recorded"
            or record["decision"]["agent_assessment"]["status"] != "accepted"
            or acquisition.get("source_kind") != "retained-member-set"):
        raise PipelineError(f"{work_id} accepted source/decision route differs")
    retained = acquisition["retained_files"]
    source_root = "/".join(retained[0]["path"].split("/")[:3])
    if not source_root.startswith("raw/standard_ebooks/"):
        raise PipelineError(f"{work_id} source root differs")
    checkout = _io_path(resolve_repo_path(root, source_root))
    files = sorted(p for p in checkout.rglob("*") if p.is_file() and ".git" not in p.parts)
    all_members = [_member(root, f"{source_root}/{p.relative_to(checkout).as_posix()}") for p in files]
    by_path = {item["path"]: item for item in all_members}
    if (len(by_path) != len(retained) or {item["path"] for item in retained} != set(by_path)
            or any(any(by_path[item["path"]][key] != item[key] for key in ("bytes", "sha256"))
                   for item in retained)):
        raise PipelineError(f"{work_id} complete retained checkout differs from accepted acquisition")
    opf_rel = f"{source_root}/src/epub/content.opf"
    tree = etree.parse(str(_io_path(resolve_repo_path(root, opf_rel))),
                       etree.XMLParser(resolve_entities=False, no_network=True))
    ns = {"opf": "http://www.idpf.org/2007/opf"}
    nodes = tree.xpath("//opf:manifest/opf:item", namespaces=ns)
    inventory = {node.get("id"): node.get("href") for node in nodes}
    if len(inventory) != len(nodes):
        raise PipelineError(f"{work_id} duplicate OPF item IDs")
    spine = [inventory.get(node.get("idref")) for node in tree.xpath("//opf:spine/opf:itemref", namespaces=ns)]
    if (len(spine) < 2 or len(set(spine)) != len(spine)
            or any(not isinstance(item, str) or not item.startswith("text/")
                   or not item.endswith(".xhtml") or ".." in Path(item).parts for item in spine)):
        raise PipelineError(f"{work_id} OPF spine is not a unique XHTML source set")
    ordered = [f"{source_root}/src/epub/{item}" for item in spine]
    if any(rel not in by_path for rel in ordered):
        raise PipelineError(f"{work_id} OPF source member missing")
    source, support = [by_path[rel] for rel in ordered], [item for item in all_members if item["path"] not in set(ordered)]
    if opf_rel not in {item["path"] for item in support}:
        raise PipelineError(f"{work_id} OPF is not accounted as support")
    if record["source"]["source_sha256"] != acquisition["source_sha256"]:
        raise PipelineError(f"{work_id} current acceptance does not bind current acquisition")
    before_tree = _tree(root / f"library/works/{work_id}")
    return {"work_id": work_id, "paths": paths, "source_root": source_root, "opf": by_path[opf_rel],
            "ordered_text_members": source, "support_members": support,
            "old_source_sha256": acquisition["source_sha256"],
            "old_acceptance_sha256": sha256_file(_io_path(root / paths["acceptance"])),
            "old_master_sha256": sha256_file(_io_path(root / paths["master"])),
            "before_tree": before_tree}


def evidence(root: Path) -> dict:
    root = root.resolve()
    return {"contract": CONTRACT, "works": [_one(root, work_id) for work_id in IDS]}


def _body(raw: bytes) -> bytes:
    root = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, no_network=True))
    header = root.find(f"{{{NS}}}teiHeader")
    if header is None:
        raise PipelineError("accepted TEI header missing")
    prefix = (header.prefix + ":") if header.prefix else ""
    marker = ("</" + prefix + "teiHeader>").encode("utf-8")
    if raw.count(marker) != 1:
        raise PipelineError("accepted TEI header boundary ambiguous")
    return raw.split(marker, 1)[1]


def _rebind_one(root: Path, stage_root: Path, row: dict, now: str) -> None:
    work_id, paths = row["work_id"], row["paths"]
    before = _json(root / paths["acceptance"])
    old_acquisition = _json(root / paths["acquisition"])
    acquisition = copy.deepcopy(old_acquisition)
    source = row["ordered_text_members"]
    scope = (f"{len(source)} retained Standard Ebooks XHTML text members in exact OPF spine order "
             f"and the corresponding unchanged reviewed {work_id} TEI representation; "
             f"the other {len(row['support_members'])} checkout files are separately hash-bound "
             "support, not reconstruction text. No independent print-edition collation.")
    acquisition["retained_files"] = [dict(item, media_type="application/xhtml+xml",
                                          scope=f"OPF spine position {index} of {len(source)}")
                                     for index, item in enumerate(source, 1)]
    acquisition["source_scope"] = scope
    acquisition["warnings"] = list(acquisition.get("warnings", [])) + [
        f"Complete checkout support is separately bound in {paths['support']}."]
    descriptor = source_member_set_bytes(acquisition)
    acquisition["source_bytes"] = len(descriptor)
    acquisition["source_sha256"] = hashlib.sha256(descriptor).hexdigest()
    descriptor_rel = acquisition["source_path"]
    write_json(_io_path(stage_root / paths["acquisition"]), acquisition)
    _io_path(stage_root / descriptor_rel).write_bytes(descriptor)
    support = {"contract": "ocd-retained-checkout-support-v1", "work_id": work_id,
               "source_root": row["source_root"], "opf": row["opf"],
               "text_member_count": len(source), "support_members": row["support_members"]}
    write_json(_io_path(stage_root / paths["support"]), support)
    updated_work = copy.deepcopy(_json(stage_root / paths["work"]))
    for rel in (PACKET_REL, paths["support"]):
        if rel not in updated_work["evidence"]:
            updated_work["evidence"].append(rel)
    validate_identity_update(_json(root / paths["work"]), updated_work)
    validate_record("work", updated_work, context=work_id)
    write_json(_io_path(stage_root / paths["work"]), updated_work)
    validate_acquisition(stage_root / paths["acquisition"], root=stage_root)

    integration = Path(paths["integration"])
    args_rel = integration / "derivation-arguments.json"
    args = _json(stage_root / args_rel)
    original = _io_path(stage_root / integration / "original-package/content.tei.xml").read_bytes()
    old_candidate = _io_path(root / integration / "candidate.tei.xml").read_bytes()
    old_master = _io_path(root / paths["master"]).read_bytes()
    if old_candidate != old_master or before["promotion"]["master"]["sha256"] != hashlib.sha256(old_master).hexdigest():
        raise PipelineError(f"{work_id} accepted candidate/master bytes differ")
    source_binding = {key: acquisition[key] for key in
                      ("source_kind", "source_path", "source_bytes", "source_sha256", "source_scope")}
    args.update({"source": source_binding, "declared_scope": scope, "revision": REVISION})
    write_json(_io_path(stage_root / args_rel), args)
    args = _json(stage_root / args_rel)
    candidate_bytes = bind_reviewed_header(original, **args)
    if _body(candidate_bytes) != _body(old_candidate) or _body(candidate_bytes) != _body(old_master):
        raise PipelineError(f"{work_id} accepted TEI text body changed")
    worker = ("import json,sys; from pathlib import Path; "
              "from ocd_kernel.tei.reviewed_integration import bind_reviewed_header; "
              "p=Path(sys.argv[1]); "
              "sys.stdout.buffer.write(bind_reviewed_header((p/'original-package/content.tei.xml').read_bytes(), "
              "**json.loads((p/'derivation-arguments.json').read_bytes())))")
    reproduced = subprocess.run([sys.executable, "-c", worker, str(stage_root / integration)],
                                cwd=root, check=True, capture_output=True).stdout
    if reproduced != candidate_bytes:
        raise PipelineError(f"{work_id} candidate header not reproducible")
    candidate_rel = integration / "candidate.tei.xml"
    _io_path(stage_root / candidate_rel).write_bytes(candidate_bytes)
    _io_path(stage_root / paths["master"]).write_bytes(candidate_bytes)
    if validate_file(_io_path(stage_root / candidate_rel)):
        raise PipelineError(f"{work_id} rebound candidate fails TEI schema")
    candidate_binding = make_file_binding(stage_root, stage_root / candidate_rel)
    expected_members = [{"path": item["path"], "position": index}
                        for index, item in enumerate(source, 1)]
    included_members = [{key: item[key] for key in ("path", "bytes", "sha256")}
                        | {"position": index, "scope": f"OPF spine position {index} of {len(source)}"}
                        for index, item in enumerate(source, 1)]
    common = {"identity": before["identity"], "source": source_binding,
              "candidate": candidate_binding, "scope": scope,
              "accepted_scope": {"kind": "edition", "declared": scope},
              "expected_members": expected_members, "included_members": included_members,
              "excluded_members": [], "missing_members": [], "unknown_members": []}
    source_accounting_rel = integration / "source-accounting.json"
    write_json(_io_path(stage_root / source_accounting_rel), common | {
        "source_sha256": acquisition["source_sha256"], "source_bytes": acquisition["source_bytes"],
        "correction": "OPF-spine XHTML is reconstruction text; all other retained checkout members are support."})
    command = "py -3 -m build.tools.prepare_accepted_standard_ebooks_spine_rebind --destination <isolated-stage>"
    implementation = {"build/tools/prepare_accepted_standard_ebooks_spine_rebind.py":
                      sha256_file(root / "build/tools/prepare_accepted_standard_ebooks_spine_rebind.py")}
    observations = {
        "validation": "Rebound candidate passes the current TEI schema; source binding is checked by public acceptance validation.",
        "accounting": "Each OPF spine XHTML member and every separately retained support member is hash-bound.",
        "fidelity": "The candidate and promoted master retain the prior accepted TEI text body byte-for-byte.",
        "reproducibility": "A separate Python process reproduced the revised header from the preserved original package.",
        "schema": "The complete rebound TEI candidate passes the current vendored TEI P5 schema.",
        "closure": "Historical acceptance is rebound to the corrected source class without changing the accepted text body."}
    technical = copy.deepcopy(before["technical"])
    technical["candidate"] = candidate_binding
    for name, observation in observations.items():
        rel = integration / f"{name}.json"
        write_json(_io_path(stage_root / rel), common | {
            "status": "pass", "command": command, "exit_code": 0, "checked_at": now,
            "observation": observation, "implementation": implementation})
        technical[name] = {"path": rel.as_posix(), "bytes": _io_path(stage_root / rel).stat().st_size,
                           "sha256": sha256_file(_io_path(stage_root / rel)), "status": "pass",
                           "command": command, "exit_code": 0}
    review = copy.deepcopy(before["review"])
    review["reviewer"] = "agent:standard-ebooks-spine-accounting-rebind"
    review["reviewed_at"] = now
    review["coverage"]["declared"] = scope
    review["unreviewed_residuals"] = list(review["unreviewed_residuals"]) + [
        "This source-classification rebind relies on the prior whole-candidate visual review; no new full visual review was performed."]
    review_rel = integration / "review.json"
    write_json(_io_path(stage_root / review_rel), common | {key: review[key] for key in
        ("reviewer", "reviewed_at", "coverage", "source_quality_uncertainty", "discrepancies", "unreviewed_residuals")})
    review["report"] = make_file_binding(stage_root, stage_root / review_rel)
    decision = copy.deepcopy(before["decision"])
    decision["agent_assessment"]["supported_scope"] = scope
    decision["source_local_disposition"] = (before["decision"]["source_local_disposition"]
        + " Source membership corrected to OPF-spine XHTML; accepted text body unchanged.")
    acceptance = build_acceptance_record(
        stage_root, identity=before["identity"], candidate_path=stage_root / candidate_rel,
        source_accounting_path=stage_root / source_accounting_rel,
        scope={"kind": "edition", "declared": scope, "expected_members": expected_members,
               "included_members": included_members, "excluded_members": []},
        technical=technical, review={"report_path": stage_root / review_rel,
            **{key: review[key] for key in ("reviewer", "reviewed_at", "coverage",
                "source_quality_uncertainty", "discrepancies", "unreviewed_residuals")}},
        representation_revision=REVISION, decision=decision,
        acceptance_id=before["acceptance_id"], promotion_status="promoted")
    write_acceptance(_io_path(stage_root / paths["acceptance"]), acceptance)
    validate_acceptance(stage_root / paths["acceptance"], root=stage_root)


def stage(root: Path, destination: Path) -> dict:
    root, destination = root.resolve(), destination.resolve()
    if destination.exists():
        raise PipelineError(f"stage destination exists: {destination}")
    for work_id in IDS:
        paths = _paths(root, work_id)
        validate_acceptance(root / paths["acceptance"], root=root)
    packet = evidence(root)
    packet_path = _io_path(root / PACKET_REL)
    if packet_path.exists():
        if _json(packet_path) != packet:
            raise PipelineError("existing accepted spine packet differs")
    else:
        write_json(packet_path, packet)
    destination.mkdir(parents=True)
    storage = root / ".ocd-storage.json"
    if storage.is_file():
        shutil.copy2(storage, destination / ".ocd-storage.json")
    target_packet = _io_path(destination / PACKET_REL)
    target_packet.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(packet_path, target_packet)
    for row in packet["works"]:
        work_rel = f"library/works/{row['work_id']}"
        shutil.copytree(_io_path(root / work_rel), _io_path(destination / work_rel))
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    for row in packet["works"]:
        _rebind_one(root, destination, row, now)
    works = []
    for row in packet["works"]:
        work_id = row["work_id"]
        before, after = row["before_tree"], _tree(destination / f"library/works/{work_id}")
        changed = [{"path": f"library/works/{work_id}/{rel}", "before_sha256": before.get(rel),
                    "proposed_sha256": after.get(rel)} for rel in sorted(set(before) | set(after)) if before.get(rel) != after.get(rel)]
        if not changed:
            raise PipelineError(f"{work_id} staged generation has no change")
        works.append({"work_id": work_id, "changed_files": changed,
                      "before_tree_sha256": hashlib.sha256(canonical_bytes(before)).hexdigest(),
                      "proposed_tree_sha256": hashlib.sha256(canonical_bytes(after)).hexdigest(),
                      "proposed_tree": after})
    receipt = {"contract": CONTRACT, "packet_path": PACKET_REL,
               "packet_sha256": sha256_file(packet_path), "works": works}
    write_json(_io_path(destination / "receipt.json"), receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    result = stage(args.repository_root, args.destination)
    print(json.dumps({"destination": str(args.destination),
                      "changed_files": sum(len(row["changed_files"]) for row in result["works"])}, sort_keys=True))


if __name__ == "__main__":
    main()
