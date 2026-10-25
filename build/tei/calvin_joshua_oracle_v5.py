"""Independent title-scope validator for the Calvin Joshua candidate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

from jsonschema import Draft202012Validator
from lxml import etree

from build.tei import calvin_commentaries_oracle as base
from build.tei import calvin_joshua_catalogue_oracle_v4 as catalogue_oracle
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.contract import (
    _canonical,
    _runtime_binding,
    _validation_authority_bindings,
)

TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
PROFILE = "calvin-title-selection-profile"
POLICY = "title-validation-policy"
ACCOUNT_SCHEMA = "title-accountability-schema"
PARENT = "collection-source-manifest"
ORACLE_ID = "ocd-calvin-joshua-source-oracle"
ORACLE_VERSION = "5"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(data: bytes, label: str) -> dict:
    value = json.loads(data.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _profile_check(profile: dict) -> tuple[list[dict], dict[str, dict]]:
    if profile.get("contract") != "ocd-calvin-title-selection-profile-v1":
        raise ValueError("title profile contract drifted")
    crosswalk = profile.get("title_hierarchy_crosswalk")
    if not isinstance(crosswalk, dict):
        raise ValueError("title profile crosswalk missing")
    crosswalk_bytes = json.dumps(crosswalk, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if profile.get("crosswalk_sha256") != _sha(crosswalk_bytes):
        raise ValueError("title profile crosswalk hash drifted")
    rows = crosswalk.get("component_rows")
    groups = crosswalk.get("title_hierarchy_disposition", {}).get("component_groups")
    if not isinstance(rows, list) or len(rows) != 45 or not isinstance(groups, list) or len(groups) != 19:
        raise ValueError("title profile row/group cardinality drifted")
    row_by_name: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("member"), str) or row["member"] in row_by_name:
            raise ValueError("title profile row identity is invalid or duplicated")
        row_by_name[row["member"]] = row
    titles: set[str] = set()
    assigned: list[str] = []
    projected = []
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("group"), str) or group["group"] in titles:
            raise ValueError("title profile group title invalid or duplicated")
        titles.add(group["group"])
        members = group.get("members")
        if not isinstance(members, list) or not members or any(not isinstance(name, str) for name in members):
            raise ValueError("title profile group members invalid")
        assigned.extend(members)
        projected.append({"title": group["group"], "members": list(members)})
    if len(assigned) != 45 or len(set(assigned)) != 45 or set(assigned) != set(row_by_name):
        raise ValueError("title profile groups do not partition all component rows exactly once")
    if profile.get("component_member_count") != 45 or profile.get("groups") != projected:
        raise ValueError("title profile projection differs from source crosswalk")
    selected = profile.get("selected_unit")
    matches = [group for group in projected if isinstance(selected, dict) and group["title"] == selected.get("title")]
    if len(matches) != 1 or selected.get("members") != matches[0]["members"] or selected != {"title": "Commentary on Joshua", "members": ["calcom07.xml"]}:
        raise ValueError("Joshua selected member assignment drifted")
    return rows, row_by_name


def _check_wrapper(source_bytes: bytes, wrapper: etree._Element, member: str) -> int:
    source_root = etree.fromstring(source_bytes, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    expected = []
    for node in source_root.iter():
        if not isinstance(node.tag, str) or base._is_formatting(node):
            continue
        expected.append((base._source_uri(member, base._selector(node)), base._target_local(node)))
    observed = [node for node in wrapper.iter() if isinstance(node.tag, str) and node.get("corresp")]
    actual = [(node.get("corresp"), etree.QName(node).localname) for node in observed]
    if actual != expected:
        raise ValueError(f"source selector/TEI element sequence differs for {member}")
    if base._source_stream(source_root) != base._candidate_stream(wrapper):
        raise ValueError(f"ordered source text stream differs for {member}")
    return len(expected)


def _verify_prior_wrapper(wrapper: etree._Element, profile: dict, member: str) -> None:
    expected = profile.get("retained_wrapper_sha256")
    key = "catalogue" if member == "commentaries.xml" else member
    if wrapper.get("n") != member:
        raise ValueError(f"source-member identity differs from selected member {member}")
    if not isinstance(expected, dict) or _sha(etree.tostring(wrapper, encoding="UTF-8")) != expected.get(key):
        raise ValueError(f"source wrapper bytes differ from the previously validated aggregate for {member}")


def _verify_container_members(container: etree._Element, expected_members: list[str], label: str) -> list[etree._Element]:
    children = [node for node in container if isinstance(node.tag, str)]
    actual = [node.get("n") for node in children if node.get("type") == "source-member"]
    if len(children) != len(expected_members) or actual != expected_members:
        raise ValueError(f"{label} has omitted, misassigned, or invented sibling elements")
    if (container.text or "").strip() or any((node.tail or "").strip() for node in children):
        raise ValueError(f"{label} has unbound sibling text")
    return children


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    profile_bytes = source_manifest.authority_path(PROFILE).read_bytes()
    profile = _json(profile_bytes, "title profile")
    rows, row_by_name = _profile_check(profile)
    derivation = profile.get("derivation_authority")
    if not isinstance(derivation, dict):
        raise ValueError("aggregate derivation binding is missing")
    parent_path = source_manifest.authority_path(PARENT)
    if _sha(parent_path.read_bytes()) != derivation.get("source_manifest_sha256"):
        raise ValueError("parent source manifest hash differs from title profile")
    parent = SourceManifest.load(parent_path, repository_root=source_manifest.repository_root)
    parent.verify()
    parent_converter = parent.record["converter"]
    if parent.record.get("producer_import_closure_sha256") != base._closure_digest(
        source_manifest.repository_root,
        source_manifest.repository_root / parent_converter["implementation_path"],
    ):
        raise ValueError("aggregate producer import closure differs from reviewed binding")
    for name in ("commentaries.xml", "calcom07.xml"):
        target = source_manifest.authority_path(name).read_bytes()
        if target != parent.authority_path(name).read_bytes():
            raise ValueError(f"title-source authority differs from parent member {name}")
    if _sha(profile_bytes) != next(item["sha256"] for item in source_manifest.record["authorities"] if item.get("name") == PROFILE):
        raise ValueError("title profile manifest binding drifted")

    content = (candidate.path / "content.tei.xml").read_bytes()
    tei = etree.fromstring(content, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    if tei.tag != f"{{{TEI}}}TEI" or tei.get(f"{{{XML}}}id") != "calvin-joshua-candidate":
        raise ValueError("Joshua TEI root identity drifted")
    front = tei.find(f"{{{TEI}}}text/{{{TEI}}}front")
    body = tei.find(f"{{{TEI}}}text/{{{TEI}}}body")
    if front is None or body is None:
        raise ValueError("Joshua TEI front/body missing")
    front_wrappers = front.findall(f"{{{TEI}}}div[@type='source-member']")
    body_wrappers = body.findall(f"{{{TEI}}}div[@type='source-member']")
    if [etree.QName(node).localname for node in tei if isinstance(node.tag, str)] != ["teiHeader", "text"]:
        raise ValueError("Joshua TEI contains an unexpected top-level sibling")
    if [etree.QName(node).localname for node in tei.find(f"{{{TEI}}}text") if isinstance(node.tag, str)] != ["front", "body"]:
        raise ValueError("Joshua TEI text contains an unexpected front/body sibling")
    if len(front_wrappers) != 1 or front_wrappers[0].get("n") != "commentaries.xml":
        raise ValueError("shared catalogue wrapper missing or duplicated")
    if len(body_wrappers) != 1 or body_wrappers[0].get("n") != "calcom07.xml":
        raise ValueError("Joshua body is not exactly the selected complete title member")
    _verify_container_members(front, ["commentaries.xml"], "Joshua shared catalogue front")
    _verify_container_members(body, ["calcom07.xml"], "Joshua title body")
    _verify_prior_wrapper(front_wrappers[0], profile, "commentaries.xml")
    _verify_prior_wrapper(body_wrappers[0], profile, "calcom07.xml")
    feature_counts = {}
    for member, wrapper in (("commentaries.xml", front_wrappers[0]), ("calcom07.xml", body_wrappers[0])):
        raw = source_manifest.authority_path(member).read_bytes()
        if member == "calcom07.xml":
            row = row_by_name[member]
            if len(raw) != row["bytes"] or _sha(raw) != row["sha256"]:
                raise ValueError("Joshua crosswalk source bytes drifted")
        feature_counts[member] = _check_wrapper(raw, wrapper, member)
    expected_files = ["commentaries.xml", "calcom07.xml"]
    source_desc = tei.xpath("/tei:TEI/tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:idno[@type='filename']/text()", namespaces={"tei": TEI})
    if source_desc != expected_files:
        raise ValueError("Joshua sourceDesc must bind only shared catalogue plus selected primary source")
    title = tei.xpath("/tei:TEI/tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title/text()", namespaces={"tei": TEI})
    if title != ["Commentary on Joshua"]:
        raise ValueError("Joshua title statement drifted")
    if tei.xpath("/tei:TEI/tei:teiHeader/tei:fileDesc/tei:notesStmt/tei:note[@type='source-member-set-sha256']", namespaces={"tei": TEI}):
        raise ValueError("aggregate 46-member source-set claim leaked into Joshua TEI")
    ownership = tei.xpath("/tei:TEI/tei:teiHeader/tei:fileDesc/tei:notesStmt/tei:note[@type='shared-catalogue-ownership']/text()", namespaces={"tei": TEI})
    if len(ownership) != 1 or "shared collection-level front matter" not in ownership[0]:
        raise ValueError("shared catalogue ownership is not explicit")
    header = tei.find(f"{{{TEI}}}teiHeader")
    if header is None:
        raise ValueError("Joshua TEI header is missing")

    accounting_bytes = (candidate.path / "source-accountability.json").read_bytes()
    accounting = _json(accounting_bytes, "Joshua source accountability")
    catalogue_authority = next(
        (item for item in source_manifest.record["authorities"] if item.get("name") == "commentaries.xml"),
        None,
    )
    if not isinstance(catalogue_authority, Mapping):
        raise ValueError("Joshua source manifest lacks the exact retained catalogue authority")
    try:
        catalogue_title_binding = catalogue_oracle.verify_header_title(
            source_manifest.authority_path("commentaries.xml"),
            candidate.path / "content.tei.xml",
            accounting,
            source_member_path=str(catalogue_authority["path"]),
            source_sha256=str(catalogue_authority["sha256"]),
            source_bytes=int(catalogue_authority["bytes"]),
        )
    except AssertionError as exc:
        raise ValueError(f"Joshua catalogue-header title source binding failed: {exc}") from exc

    # The old shared aggregate title profile pins the uncorrected header. Its
    # only permitted difference in this Joshua successor is the source-derived
    # correction above. Restore the old profile value in a copy and require an
    # exact inverse hash match before accepting the repaired header.
    collection_profile = _json(
        parent.authority_path("reconstruction-profile").read_bytes(),
        "aggregate collection profile",
    )
    catalogue_members = [
        row for row in collection_profile.get("members", [])
        if isinstance(row, dict) and row.get("name") == "commentaries.xml"
    ]
    if len(catalogue_members) != 1 or not isinstance(catalogue_members[0].get("main_title"), str):
        raise ValueError("aggregate profile lacks one pinned catalogue title for the inverse check")
    old_profile_title = catalogue_members[0]["main_title"]
    header_inverse = etree.fromstring(etree.tostring(header, encoding="UTF-8"))
    inverse_titles = header_inverse.xpath(
        "/tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl[@type='catalogue'][tei:idno[@type='filename']='commentaries.xml']/tei:title",
        namespaces={"tei": TEI},
    )
    if len(inverse_titles) != 1:
        raise ValueError("Joshua catalogue header title is not unique for the inverse check")
    inverse_titles[0].text = old_profile_title
    if _sha(etree.tostring(header_inverse, encoding="UTF-8")) != profile.get("retained_tei_header_sha256"):
        raise ValueError("Joshua header differs beyond the exact source-derived catalogue-title repair")

    schema = _json(source_manifest.authority_path(ACCOUNT_SCHEMA).read_bytes(), "Joshua accountability schema")
    errors = sorted(Draft202012Validator(schema).iter_errors(accounting), key=str)
    if errors:
        raise ValueError(f"Joshua accountability schema failure: {errors[0].message}")
    expected_included = []
    for member, role, wrapper in (("commentaries.xml", "shared-catalogue-front-matter", front_wrappers[0]), ("calcom07.xml", "primary-commentary-source", body_wrappers[0])):
        authority = next(item for item in parent.record["authorities"] if item["name"] == member)
        expected_included.append({"member":member,"path":authority["path"],"role":role,"bytes":authority["bytes"],"sha256":authority["sha256"],"wrapper_sha256":_sha(etree.tostring(wrapper,encoding="UTF-8")),"mapped_selector_count":feature_counts[member]})
    expected_siblings = [{"member":name,"group":group["title"],"disposition":"sibling-title-excluded-from-this-TEI"} for group in profile["groups"] for name in group["members"] if name != "calcom07.xml"]
    expected_accounting = {"contract":"ocd-calvin-series-accountability-v2","profile_sha256":_sha(profile_bytes),"crosswalk_sha256":profile["crosswalk_sha256"],"historical_container_id":"calvin-commentaries","title":"Commentary on Joshua","selected_members":["calcom07.xml"],"included":expected_included,"sibling_exclusions":expected_siblings,"group_count":19,"component_count":45,"catalogue_title_binding":catalogue_title_binding}
    if accounting != expected_accounting or accounting_bytes != _canonical(expected_accounting):
        raise ValueError("Joshua source accounting scope or records drifted")

    policy_bytes = source_manifest.authority_path(POLICY).read_bytes()
    policy = _json(policy_bytes, "Joshua policy")
    if _json((candidate.path / "provenance.json").read_bytes(), "Joshua provenance") != policy["provenance"]:
        raise ValueError("Joshua provenance differs from bound policy")
    if (candidate.path / "unresolved.jsonl").read_bytes() != b"".join(_canonical(item) for item in policy["unresolved"]):
        raise ValueError("Joshua unresolved ledger differs from bound policy")
    if (candidate.path / "README.source.md").read_bytes() != source_manifest.authority_path("title-source-readme").read_bytes():
        raise ValueError("Joshua source README differs from bound authority")
    xsd = etree.XMLSchema(etree.parse(str(source_manifest.authority_path("tei-p5-xsd"))))
    if not xsd.validate(etree.ElementTree(tei)):
        raise ValueError(f"Joshua TEI fails P5: {xsd.error_log.last_error}")
    if base._closure_digest(source_manifest.repository_root, Path(__file__).resolve()) != source_manifest.record["validator"]["import_closure_sha256"]:
        raise ValueError("Joshua oracle import closure drifted")

    bindings = _validation_authority_bindings(source_manifest)
    result: dict[str, object] = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": str(source_manifest.record["validator"]["import_closure_sha256"]),
        "runtime": _runtime_binding(),
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": bindings["profile_sha256"],
        "package_schema_sha256": bindings["package_schema_sha256"],
        "source_sha256": bindings["source_sha256"],
        "xsd_sha256": bindings["xsd_sha256"],
        "policy_sha256": bindings["policy_sha256"],
        "findings": [],
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
