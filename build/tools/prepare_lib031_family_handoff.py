"""Prepare a source-bound, noninstalling LIB-031 work-by-work acceptance audit.

The ten-work candidate is evidence for conversion, not ten accepted masters.
This command reads canonical sidecars and retained sources, then writes only a
reviewable preparation report at the caller's requested path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.tei.install_accepted import _io_path
from build.tei.lib031_bounds_standalone_oracle import verify as verify_essentials
from build.tei.lib031_bounds_necessity_standalone_oracle import verify as verify_necessity


SOURCE_SET = Path("sources/structured-text/bounds-essentials-of-prayer/lib031-retained-source-set.json")
PROFILE = Path("sources/structured-text/bounds-essentials-of-prayer/lib031.reconstruction-profile.json")
SOURCE_MANIFEST = Path("sources/structured-text/bounds-essentials-of-prayer/lib031.source-manifest.json")
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
BOUNDS_REVIEW_IDS = {
    "bounds-essentials-of-prayer": "37c-079",
    "bounds-necessity-of-prayer": "37c-080",
    "bounds-power-through-prayer": "37c-081",
    "bounds-prayer-and-praying-men": "37c-082",
    "bounds-purpose-in-prayer": "37c-083",
    "bounds-reality-of-prayer": "37c-084",
    "bounds-weapon-of-prayer": "37c-085",
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise ValueError(f"expected JSON object: {path}")
    return result


def _bound(content: bytes, declared: dict[str, Any], label: str) -> None:
    if declared.get("sha256") != _sha(content) or declared.get("bytes") != len(content):
        raise ValueError(f"exact byte binding failed: {label}")


def _source_selector(node: etree._Element, body: etree._Element) -> str:
    parts: list[str] = []
    current = node
    while current is not body:
        parent = current.getparent()
        if parent is None:
            raise ValueError("source node escaped ThML.body")
        tag = current.tag if isinstance(current.tag, str) else "#comment"
        ordinal = sum(
            (peer.tag if isinstance(peer.tag, str) else "#comment") == tag
            for peer in parent[: parent.index(current) + 1]
        )
        parts.append(f"{tag}[{ordinal}]")
        current = parent
    return "ThML.body/" + "/".join(reversed(parts))


def _pilot(root: Path, work_id: str, source: bytes) -> dict[str, Any] | None:
    if work_id == "bounds-essentials-of-prayer":
        receipt_rel = Path("plans/2026-09-22-source-preflight/ccel-direct-family-handoff-20260926.json")
        receipt = _json(root / receipt_rel)["standalone_pilot"]
        candidate_root = Path(receipt["package_path"])
        expected = {
            "package/manifest.json": receipt["package_manifest_sha256"],
            "package/content.tei.xml": receipt["tei_sha256"],
            "package/source-accountability.json": receipt["accounting_sha256"],
            "validation.json": receipt["validation_sha256"],
        }
        verifier = verify_essentials
        prior_checks = {"mutations": receipt["mutations"], "reproduction": receipt["reproduction"]}
    elif work_id == "bounds-necessity-of-prayer":
        receipt_rel = Path("plans/2026-09-22-source-preflight/ccel-lib031-bounds-necessity-standalone-20260926.json")
        receipt = _json(root / receipt_rel)
        candidate_root = Path(receipt["candidate_root"])
        expected = receipt["package_sha256"]
        verifier = verify_necessity
        prior_checks = {"focused_pytest": receipt["checks"]["focused_pytest"], "reproduction": receipt["checks"]["fresh_process_reproduction"]}
    else:
        return None
    for relative, digest in expected.items():
        if _sha((candidate_root / relative).read_bytes()) != digest:
            raise ValueError(f"standalone pilot byte binding failed: {work_id}, {relative}")
    manifest = _json(candidate_root / "package" / "manifest.json")
    validation = _json(candidate_root / "validation.json")
    tei_bytes = (candidate_root / "package" / "content.tei.xml").read_bytes()
    accounting = _json(candidate_root / "package" / "source-accountability.json")
    if manifest.get("status") != "nonaccepted" or manifest.get("work_id") != work_id or validation.get("status") != "pass" or validation.get("work_id") != work_id:
        raise ValueError(f"standalone pilot status changed: {work_id}")
    oracle_result = verifier(source, tei_bytes, accounting)
    if oracle_result["source_body_nodes"] != validation["checks"]["source_body_nodes"]:
        raise ValueError(f"standalone pilot oracle count changed: {work_id}")
    return {
        "status": "verified-nonaccepted-technical-candidate",
        "receipt_path": receipt_rel.as_posix(),
        "receipt_sha256": _sha((root / receipt_rel).read_bytes()),
        "candidate_root": str(candidate_root),
        "tei_sha256": _sha(tei_bytes),
        "oracle_current_result": oracle_result,
        "prior_mutation_and_reproduction_evidence": prior_checks,
        "limitation": "Pilot package is not the standard accepted-master route and has no work-local visual review.",
    }


def _prior_parent_visual(root: Path, work_id: str, source_sha: str, parent_sha: str) -> dict[str, Any] | None:
    ticket = BOUNDS_REVIEW_IDS.get(work_id)
    if ticket is None:
        return None
    review_dir = Path("plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-08-ticket37/reviews")
    stem = ticket + "-cvw-start-20260920"
    capture_rel = review_dir / (stem + ".capture.json")
    frame_rel = review_dir / (stem + ".frame.png")
    report_rel = review_dir / (ticket + ".md")
    capture = _json(root / capture_rel)
    frame = (root / frame_rel).read_bytes()
    route = capture.get("browser_state", {}).get("route", "")
    if (capture.get("session", {}).get("candidate_sha256") != [parent_sha]
            or source_sha not in route or parent_sha not in route
            or capture.get("files", {}).get("frame.png") != _sha(frame)
            or capture.get("page_errors") != []):
        raise ValueError(f"prior parent visual binding changed: {work_id}")
    return {
        "scope": "parent-candidate opening frame only; not the work-local pilot or full visual comparison",
        "capture_path": capture_rel.as_posix(),
        "capture_sha256": _sha((root / capture_rel).read_bytes()),
        "frame_path": frame_rel.as_posix(),
        "frame_sha256": _sha(frame),
        "prior_review_path": report_rel.as_posix(),
        "prior_review_sha256": _sha((root / report_rel).read_bytes()),
        "inspected_loci_in_capture": capture.get("inspected_loci", []),
    }


def _current_work_local(root: Path, review_root: Path, work_id: str, source_sha: str) -> dict[str, Any]:
    manifest_rel = Path("sources/structured-text") / work_id / "lib031-work.source-manifest.json"
    source_manifest = SourceManifest.load(root / manifest_rel, repository_root=root)
    candidate_root = review_root / f"lib031-work-{work_id}-20260926-v6"
    candidate = CandidatePackage.load(candidate_root / "package")
    validation_bytes = (candidate_root / "validation.json").read_bytes()
    validation = json.loads(validation_bytes)
    if (candidate.manifest.get("status") != "nonaccepted"
            or candidate.manifest.get("source_manifest", {}).get("sha256") != source_manifest.sha256
            or validation.get("status") != "pass"
            or validation.get("candidate_sha256") != candidate.sha256
            or validation.get("source_manifest_sha256") != source_manifest.sha256
            or validation.get("findings") != []):
        raise ValueError(f"standard work-local candidate binding changed: {work_id}")
    accounting = json.loads(candidate.member_bytes("source-accountability.json"))
    if accounting.get("work_id") != work_id or accounting.get("source_sha256") != source_sha:
        raise ValueError(f"standard work-local source accounting changed: {work_id}")
    return {
        "status": "validated-nonaccepted",
        "source_manifest_path": manifest_rel.as_posix(),
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_root": str(candidate_root),
        "package_manifest_sha256": candidate.sha256,
        "tei_sha256": _sha(candidate.member_bytes("content.tei.xml")),
        "validation_sha256": _sha(validation_bytes),
        "body_nodes": len(accounting["body_crosswalk"]),
        "source_headings": accounting["source_headings"],
        "localized_source_links": accounting["localized_source_links"],
    }


def prepare(root: Path, family_package: Path) -> dict[str, Any]:
    root = root.resolve(strict=True)
    family_package = family_package.resolve(strict=True)
    source_set = _json(root / SOURCE_SET)
    profile = _json(root / PROFILE)
    source_manifest_bytes = (root / SOURCE_MANIFEST).read_bytes()
    members = source_set.get("members")
    if source_set.get("census", {}).get("included") != 10 or not isinstance(members, list) or len(members) != 10:
        raise ValueError("LIB-031 member census changed")
    work_order = profile.get("work_order")
    if work_order != [member.get("work_id") for member in members] or len(set(work_order)) != 10:
        raise ValueError("LIB-031 work order or membership changed")

    parent_manifest_bytes = (family_package / "manifest.json").read_bytes()
    parent_manifest = _json(family_package / "manifest.json")
    validation_bytes = (family_package.parent / "validation.json").read_bytes()
    validation = _json(family_package.parent / "validation.json")
    if (parent_manifest.get("status") != "nonaccepted" or validation.get("status") != "pass"
            or parent_manifest.get("source_manifest", {}).get("sha256") != _sha(source_manifest_bytes)
            or validation.get("source_manifest_sha256") != _sha(source_manifest_bytes)
            or validation.get("candidate_sha256") != _sha(parent_manifest_bytes)):
        raise ValueError("parent candidate validation or source manifest binding changed")
    declared = {item["name"]: item for item in parent_manifest["members"]}
    tei_bytes = (family_package / "content.tei.xml").read_bytes()
    accounting_bytes = (family_package / "source-accountability.json").read_bytes()
    _bound(tei_bytes, declared["content.tei.xml"], "parent TEI")
    _bound(accounting_bytes, declared["source-accountability.json"], "parent accounting")
    accounting = json.loads(accounting_bytes)
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, huge_tree=True)
    tei = etree.fromstring(tei_bytes, parser)
    ns = {"tei": TEI_NS}
    divisions = tei.xpath("./tei:text/tei:body/tei:div", namespaces=ns)
    if [division.get(XML_ID) for division in divisions] != work_order:
        raise ValueError("parent TEI work divisions changed")
    if not isinstance(accounting.get("crosswalk"), list):
        raise ValueError("parent crosswalk missing")

    output: list[dict[str, Any]] = []
    for member, division in zip(members, divisions, strict=True):
        work_id = member["work_id"]
        if member.get("disposition") != "include":
            raise ValueError(f"unexpected member disposition: {work_id}")
        work_dir = root / "library" / "works" / work_id
        work = _json(_io_path(work_dir / "work.json"))
        state = _json(_io_path(work_dir / "state.json"))
        forms = work.get("textual_forms", [])
        if work.get("work_id") != work_id or state.get("work_id") != work_id or len(forms) != 1 or len(forms[0].get("editions", [])) != 1:
            raise ValueError(f"canonical work/form/edition identity changed: {work_id}")
        form = forms[0]
        edition = form["editions"][0]
        acquisition_ids = edition.get("acquisition_ids")
        if not isinstance(acquisition_ids, list) or len(acquisition_ids) != 1:
            raise ValueError(f"acquisition identity ambiguous: {work_id}")
        acquisition_rel = Path("library/works") / work_id / "forms" / form["textual_form_id"] / "editions" / edition["edition_id"] / "acquisitions" / (acquisition_ids[0] + ".json")
        acquisition_path = _io_path(root / acquisition_rel)
        acquisition_bytes = acquisition_path.read_bytes()
        acquisition = json.loads(acquisition_bytes)
        source_rel = "raw/" + member["logical_path"]
        source = resolve_repo_path(root, source_rel).read_bytes()
        _bound(source, member, f"retained source for {work_id}")
        if (acquisition.get("acquisition_id") != acquisition_ids[0]
                or acquisition.get("edition_id") != edition["edition_id"]
                or acquisition.get("source_path") != source_rel
                or acquisition.get("source_sha256") != _sha(source)
                or acquisition.get("source_bytes") != len(source)
                or not any(item.get("path") == source_rel and item.get("sha256") == _sha(source) and item.get("bytes") == len(source)
                           for item in acquisition.get("retained_files", []))):
            raise ValueError(f"canonical acquisition does not bind exact source: {work_id}")
        edition_dir = acquisition_path.parent.parent
        if _io_path(edition_dir / "acceptance.json").exists() or _io_path(edition_dir / "master.tei.xml").exists():
            raise ValueError(f"existing acceptance or master requires a different route: {work_id}")
        tree = etree.fromstring(source, parser)
        head, body = tree.find("ThML.head"), tree.find("ThML.body")
        if tree.tag != "ThML" or head is None or body is None:
            raise ValueError(f"retained ThML envelope changed: {work_id}")
        header_rights_claims = [" ".join("".join(node.itertext()).split()) for node in head.iter()
                                if isinstance(node.tag, str) and node.tag.lower() == "dc.rights"]
        nodes = list(body.iter())[1:]
        rows = [row for row in accounting["crosswalk"] if row.get("work_id") == work_id]
        if len(rows) != len(nodes):
            raise ValueError(f"parent body crosswalk incomplete: {work_id}")
        for node, row in zip(nodes, rows, strict=True):
            tag = node.tag if isinstance(node.tag, str) else "#comment"
            if (row.get("source_selector") != _source_selector(node, body)
                    or row.get("source_tag") != tag
                    or row.get("attributes") != dict(node.attrib)
                    or row.get("direct_text") != (node.text or "")
                    or row.get("tail_text") != (node.tail or "")):
                raise ValueError(f"parent crosswalk source mismatch: {work_id}")
        source_heads = Counter(node.tag for node in nodes if isinstance(node.tag, str) and node.tag in {"h1", "h2", "h3", "h4", "h5", "h6"})
        mapped_heads = sum(row["tei_tag"] == "head" for row in rows if row["source_tag"] in source_heads)
        child_ids = {node.get(XML_ID) for node in division.iter() if isinstance(node.tag, str) and node.get(XML_ID)}
        refs = division.xpath(".//tei:ref[@target]", namespaces=ns)
        broken_fragments = [ref.get("target") for ref in refs if ref.get("target", "").startswith("#") and ref.get("target")[1:] not in child_ids]
        source_query_links = sum(node.tag == "a" and node.get("href", "").startswith("?") for node in nodes)
        state_targets = {item.get("target_id"): item.get("stage") for item in state.get("targets", [])}
        if state_targets.get(edition["edition_id"]) not in {"acquired", "candidate", "reviewed"}:
            raise ValueError(f"unexpected edition state for preparation: {work_id}")
        pilot = _pilot(root, work_id, source)
        work_local = _current_work_local(root, family_package.parent.parent, work_id, _sha(source))
        prior_visual = _prior_parent_visual(root, work_id, _sha(source), _sha(parent_manifest_bytes))
        if work_local["body_nodes"] != len(nodes) or work_local["source_headings"] != sum(source_heads.values()) or work_local["localized_source_links"] != sum(node.tag == "a" for node in nodes):
            raise ValueError(f"work-local semantic source coverage changed: {work_id}")
        gaps = [
            "work-local candidate has no guarded agent acceptance decision or installed master",
            "retained header attribution and disclosure need a scoped disposition",
            "exact work-local visual and edition-identity review are not recorded",
        ]
        if any(node.tag in {"table", "note", "pb", "verse"} for node in nodes):
            gaps.append("source tables, notes, pages, or verse need scoped review of readable relationships")
        output.append({
            "work_id": work_id,
            "form_id": form["textual_form_id"],
            "edition_id": edition["edition_id"],
            "acquisition_id": acquisition_ids[0],
            "source": {"path": source_rel, "sha256": _sha(source), "bytes": len(source), "body_nodes": len(nodes), "header_nodes": len(list(head.iter()))},
            "canonical_acquisition": {"path": acquisition_rel.as_posix(), "sha256": _sha(acquisition_bytes)},
            "retained_header_rights_claims": header_rights_claims,
            "acquisition_rights_warnings": acquisition.get("warnings", []),
            "parent_body_crosswalk_rows": len(rows),
            "source_heading_count": sum(source_heads.values()),
            "parent_mapped_heading_count": mapped_heads,
            "unclosed_parent_fragment_links": len(broken_fragments),
            "source_query_links": source_query_links,
            "edition_state": state_targets[edition["edition_id"]],
            "existing_standalone_pilot": pilot,
            "standard_work_local_candidate": work_local,
            "prior_parent_visual": prior_visual,
            "agent_acceptance_preparation": "blocked",
            "gaps": gaps,
        })
    if sum(item["source"]["body_nodes"] for item in output) != len(accounting["crosswalk"]):
        raise ValueError("parent crosswalk contains unassigned rows")
    return {
        "contract": "ocd-lib031-family-acceptance-preparation-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "ten source-attested LIB-031 works; no acceptance or installation",
        "source_set": {"path": SOURCE_SET.as_posix(), "sha256": _sha((root / SOURCE_SET).read_bytes())},
        "profile": {"path": PROFILE.as_posix(), "sha256": _sha((root / PROFILE).read_bytes())},
        "family_source_manifest": {"path": SOURCE_MANIFEST.as_posix(), "sha256": _sha(source_manifest_bytes)},
        "parent_candidate": {"package_manifest": str(family_package / "manifest.json"), "sha256": _sha(parent_manifest_bytes), "validation_sha256": _sha(validation_bytes), "tei_sha256": _sha(tei_bytes), "accounting_sha256": _sha(accounting_bytes)},
        "counts": {"works": len(output), "source_bound": len(output), "standard_work_local_candidates": len(output), "parent_crosswalk_rows": sum(item["parent_body_crosswalk_rows"] for item in output), "ready_for_agent_acceptance": 0, "blocked": len(output)},
        "works": output,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--family-package", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.root, args.family_package)
    if args.output.exists():
        raise FileExistsError(f"refusing to replace preparation stage: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["counts"], sort_keys=True))


if __name__ == "__main__":
    main()
