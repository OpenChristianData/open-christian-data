"""Select a source-attested title group from the verified Calvin collection TEI.

This is a post-reconstruction selector: it copies source-member subtrees from
the independently validated collection candidate and does not reconvert CCEL
XML. It emits a nonaccepted title-group TEI for review, not a canonical work ID.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from lxml import etree

from build.tei import calvin_commentaries_oracle as oracle
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.contract import _canonical

TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
NS = {"tei": TEI}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _group(crosswalk: dict[str, Any], title: str) -> dict[str, Any]:
    groups = crosswalk.get("title_hierarchy_disposition", {}).get("component_groups")
    if not isinstance(groups, list):
        raise ValueError("crosswalk component groups are missing")
    matches = [item for item in groups if isinstance(item, dict) and item.get("group") == title]
    if len(matches) != 1:
        raise ValueError("title-group selector is missing or ambiguous")
    group = matches[0]
    names = group.get("members")
    if not isinstance(names, list) or not names or any(not isinstance(name, str) for name in names):
        raise ValueError("title-group member selection is invalid")
    return group


def validate_title_selection_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """Validate a title profile's crosswalk binding and exact partition."""
    if profile.get("contract") != "ocd-calvin-title-selection-profile-v1":
        raise ValueError("title-selection profile contract mismatch")
    crosswalk = profile.get("title_hierarchy_crosswalk")
    if not isinstance(crosswalk, dict):
        raise ValueError("title-selection profile crosswalk is missing")
    canonical_crosswalk = json.dumps(
        crosswalk, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    if profile.get("crosswalk_sha256") != _sha(canonical_crosswalk):
        raise ValueError("title-selection crosswalk digest drifted")

    rows = crosswalk.get("component_rows")
    if not isinstance(rows, list) or len(rows) != 45:
        raise ValueError("title-selection component row cardinality drifted")
    row_names: list[str] = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("member"), str) or not row["member"]:
            raise ValueError("title-selection component row identity is invalid")
        row_names.append(row["member"])
    if len(set(row_names)) != 45:
        raise ValueError("title-selection component rows contain duplicate members")

    groups = crosswalk.get("title_hierarchy_disposition", {}).get("component_groups")
    if not isinstance(groups, list) or len(groups) != 19:
        raise ValueError("title-selection group cardinality drifted")
    titles: list[str] = []
    projected_groups: list[dict[str, Any]] = []
    assigned: list[str] = []
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("group"), str) or not group["group"]:
            raise ValueError("title-selection group identity is invalid")
        members = group.get("members")
        if not isinstance(members, list) or not members or any(not isinstance(item, str) or not item for item in members):
            raise ValueError("title-selection group members are invalid")
        titles.append(group["group"])
        assigned.extend(members)
        projected_groups.append({"title": group["group"], "members": list(members)})
    if len(set(titles)) != 19:
        raise ValueError("title-selection group titles contain duplicates")
    if len(set(assigned)) != len(assigned):
        raise ValueError("title-selection groups overlap or duplicate members")
    if len(assigned) != 45 or set(assigned) != set(row_names):
        raise ValueError("title-selection groups do not partition the component rows")
    if profile.get("component_member_count") != 45 or profile.get("groups") != projected_groups:
        raise ValueError("title-selection profile group binding drifted")

    selected = profile.get("selected_unit")
    if not isinstance(selected, dict) or not isinstance(selected.get("title"), str):
        raise ValueError("title-selection selected unit is invalid")
    selected_matches = [item for item in projected_groups if item["title"] == selected["title"]]
    if len(selected_matches) != 1 or selected.get("members") != selected_matches[0]["members"]:
        raise ValueError("title-selection selected membership differs from the partition")
    return {"crosswalk": crosswalk, "component_rows": rows, "groups": projected_groups}


def _validate_parent(
    package: CandidatePackage,
    validation_path: Path,
    manifest: SourceManifest,
) -> dict[str, Any]:
    package_manifest = package.manifest
    if package_manifest.get("source_manifest", {}).get("sha256") != manifest.sha256:
        raise ValueError("parent candidate is not bound to the supplied source manifest")
    validation = _json(validation_path, "parent validation sidecar")
    if (
        validation.get("status") != "pass"
        or validation.get("candidate_sha256") != package.sha256
        or validation.get("source_manifest_sha256") != manifest.sha256
        or validation.get("findings") != []
        or validation.get("attestation", {}).get("status") != "pass"
    ):
        raise ValueError("parent candidate does not have a matching passing validation")
    report_record = {
        "contract": "ocd-validation-report-v1",
        "status": validation.get("status"),
        "candidate_sha256": validation.get("candidate_sha256"),
        "source_manifest_sha256": validation.get("source_manifest_sha256"),
        "attestation": validation.get("attestation"),
        "findings": validation.get("findings"),
    }
    if validation.get("report_sha256") != _sha(_canonical(report_record)):
        raise ValueError("parent validation report digest drifted")
    return validation


def _source_wrapper_checks(
    manifest: SourceManifest,
    member: str,
    wrapper: etree._Element,
    crosswalk_rows: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    row = crosswalk_rows.get(member)
    if row is None:
        raise ValueError(f"crosswalk has no source row for {member}")
    authority = next(
        (item for item in manifest.record["authorities"] if item.get("name") == member),
        None,
    )
    if authority is None:
        raise ValueError(f"source manifest has no authority for {member}")
    source_bytes = manifest.authority_path(member).read_bytes()
    if len(source_bytes) != row.get("bytes") or _sha(source_bytes) != row.get("sha256"):
        raise ValueError(f"crosswalk source binding drifted for {member}")
    source = etree.fromstring(source_bytes, etree.XMLParser(resolve_entities=False, no_network=True))

    expected: list[tuple[str, str]] = []
    for node in source.iter():
        if not isinstance(node.tag, str) or oracle._is_formatting(node):
            continue
        selector = oracle._selector(node)
        expected.append((oracle._source_uri(member, selector), oracle._target_local(node)))

    observed = [node for node in wrapper.iter() if isinstance(node.tag, str) and node.get("corresp")]
    actual = [(node.get("corresp"), etree.QName(node).localname) for node in observed]
    if actual != expected:
        raise ValueError(f"source selector or target-element mapping drifted for {member}")
    if oracle._candidate_stream(wrapper) != oracle._source_stream(source):
        raise ValueError(f"source text stream drifted for {member}")
    return {
        "member": member,
        "source_bytes": len(source_bytes),
        "source_sha256": _sha(source_bytes),
        "source_feature_count": len(expected),
        "selector_sequence_match": True,
        "target_element_sequence_match": True,
        "text_stream_match": True,
    }


def _parse_tei(content: bytes) -> etree._Element:
    root = etree.fromstring(content, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    if root.tag != f"{{{TEI}}}TEI" or root.get(f"{{{XML}}}id") != "calvin-commentaries-candidate":
        raise ValueError("verified parent TEI root identity drifted")
    return root


def select_title_group(
    *,
    package_path: Path,
    validation_path: Path,
    manifest_path: Path,
    repository_root: Path,
    crosswalk_path: Path,
    group_title: str,
    output_path: Path,
) -> dict[str, Any]:
    package = CandidatePackage.load(package_path)
    manifest = SourceManifest.load(manifest_path, repository_root=repository_root)
    validation = _validate_parent(package, validation_path, manifest)
    report = _json(crosswalk_path, "title hierarchy report")
    crosswalk = report.get("title_hierarchy_crosswalk")
    if not isinstance(crosswalk, dict):
        raise ValueError("title hierarchy crosswalk is missing")
    group = _group(crosswalk, group_title)
    names = list(group["members"])

    rows = crosswalk.get("component_rows")
    if not isinstance(rows, list):
        raise ValueError("component crosswalk rows are missing")
    crosswalk_rows = {row["member"]: row for row in rows if isinstance(row, dict) and isinstance(row.get("member"), str)}
    if len(crosswalk_rows) != 45:
        raise ValueError("component crosswalk cardinality drifted")

    parent_root = _parse_tei(package.member_bytes("content.tei.xml"))
    front = parent_root.find(f"{{{TEI}}}text/{{{TEI}}}front")
    body = parent_root.find(f"{{{TEI}}}text/{{{TEI}}}body")
    if front is None or body is None:
        raise ValueError("verified parent TEI is missing front/body")
    catalogue_wrappers = front.findall(f"{{{TEI}}}div[@type='source-member']")
    body_wrappers = body.findall(f"{{{TEI}}}div[@type='source-member']")
    if len(catalogue_wrappers) != 1 or catalogue_wrappers[0].get("n") != "commentaries.xml":
        raise ValueError("verified parent catalogue ownership drifted")
    available = {node.get("n"): node for node in body_wrappers}
    if len(available) != 45 or set(available) != set(crosswalk_rows):
        raise ValueError("verified parent component set differs from the crosswalk")
    if [node.get("n") for node in body_wrappers if node.get("n") in names] != names:
        raise ValueError("selected members are not in source order")

    title_nodes = parent_root.xpath("/tei:TEI/tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title", namespaces=NS)
    notes_stmt = parent_root.xpath("/tei:TEI/tei:teiHeader/tei:fileDesc/tei:notesStmt", namespaces=NS)
    if len(title_nodes) != 1 or len(notes_stmt) != 1:
        raise ValueError("verified parent title/notes structure drifted")
    title_nodes[0].text = group_title
    for note in list(notes_stmt[0]):
        if note.get("type") in {"series-selection", "shared-catalogue-ownership"}:
            notes_stmt[0].remove(note)
    selection_note = etree.SubElement(notes_stmt[0], f"{{{TEI}}}note", type="series-selection")
    selection_note.text = f"Source-attested complete title group: {group_title}. Selected members: {', '.join(names)}. The legacy collection identity is retained as history, not asserted as a new work identifier."
    catalogue_note = etree.SubElement(notes_stmt[0], f"{{{TEI}}}note", type="shared-catalogue-ownership")
    catalogue_note.text = "The complete CCEL catalogue is retained as collection-level shared front matter in this title-group TEI. Its original CCEL hrefs are preserved, including links to sibling groups not included in this TEI."

    for child in list(body):
        body.remove(child)
    selected_checks = []
    for name in names:
        wrapper = available[name]
        body.append(wrapper)
        selected_checks.append(_source_wrapper_checks(manifest, name, wrapper, crosswalk_rows))

    schema_path = manifest.authority_path("tei-p5-xsd")
    schema = etree.XMLSchema(etree.parse(str(schema_path)))
    output_bytes = etree.tostring(parent_root, encoding="UTF-8", xml_declaration=True, pretty_print=False)
    parsed_output = etree.fromstring(output_bytes, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    if not schema.validate(parsed_output):
        error = schema.error_log.last_error
        raise ValueError(f"selected title-group TEI fails P5 schema: {error}")
    output_path = output_path.resolve(strict=False)
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(output_bytes)
    return {
        "status": "pass",
        "group_title": group_title,
        "members": names,
        "output_path": str(output_path),
        "output_bytes": len(output_bytes),
        "output_sha256": _sha(output_bytes),
        "parent_candidate_manifest_sha256": package.sha256,
        "parent_validation_report_sha256": _sha(validation_path.read_bytes()),
        "parent_validation_status": validation["status"],
        "source_manifest_sha256": manifest.sha256,
        "crosswalk_sha256": _sha(json.dumps(crosswalk, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")),
        "tei_schema_sha256": _sha(schema_path.read_bytes()),
        "catalogue_wrapper_count": len(catalogue_wrappers),
        "selected_body_wrapper_count": len(names),
        "source_checks": selected_checks,
        "acceptance_status": "not-accepted",
        "canonical_identity_created": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-package", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--crosswalk", type=Path, required=True)
    parser.add_argument("--group-title", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    return parser


def main() -> None:
    args = _parser().parse_args()
    print(json.dumps(select_title_group(
        package_path=args.candidate_package,
        validation_path=args.validation,
        manifest_path=args.manifest,
        repository_root=args.repository_root,
        crosswalk_path=args.crosswalk,
        group_title=args.group_title,
        output_path=args.output,
    ), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
