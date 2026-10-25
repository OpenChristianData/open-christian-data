"""Independent retained-byte JSON oracle for the ten LIB-063 packages."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts


ORACLE_ID = "ocd-creeds-json-lib063-retained-byte-oracle"
ORACLE_VERSION = "1"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
TEI = {"tei": TEI_NS}
WORK_TO_STEM = {
    "abstract-of-principles": "abstract_of_principles",
    "apostles-creed": "apostles_creed",
    "athanasian-creed": "athanasian_creed",
    "belgic-confession-of-faith": "belgic_confession_of_faith",
    "canons-of-dort": "canons_of_dort",
    "chalcedonian-definition": "chalcedonian_definition",
    "consensus-tigurinus": "consensus_tigurinus",
    "council-of-orange": "council_of_orange",
    "first-confession-of-basel": "first_confession_of_basel",
    "first-helvetic-confession": "first_helvetic_confession",
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _strict_json(content: bytes, label: str) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate key {key!r}")
            result[key] = value
        return result

    try:
        loaded = json.loads(
            content.decode("utf-8"), object_pairs_hook=reject_duplicates
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(loaded, dict):
        raise ValueError(f"{label} must be a JSON object")
    return loaded


def _one_by_role(source: SourceManifest, role: str) -> Mapping[str, object]:
    authorities = source.record.get("authorities")
    if not isinstance(authorities, tuple):
        raise ValueError("LIB-063 source authorities are invalid")
    found = [
        authority
        for authority in authorities
        if isinstance(authority, Mapping) and authority.get("role") == role
    ]
    if len(found) != 1:
        raise ValueError(f"LIB-063 requires exactly one {role} authority")
    return found[0]


def _authority_bytes(source: SourceManifest, role: str) -> bytes:
    authority = _one_by_role(source, role)
    return source.authority_path(str(authority["name"])).read_bytes()


def _profile_and_census(
    source: SourceManifest,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    profile = _strict_json(
        _authority_bytes(source, "complete-source-feature-profile"),
        "LIB-063 reconstruction profile",
    )
    if (
        profile.get("contract") != "ocd-creeds-json-lib063-profile-v1"
        or profile.get("assigned_work_count") != 10
        or profile.get("family_member_count") != 43
        or profile.get("included_member_count") != 10
        or profile.get("excluded_member_count") != 33
    ):
        raise ValueError("LIB-063 reconstruction profile scope drifted")
    census = profile.get("family_census")
    if not isinstance(census, list) or len(census) != 43:
        raise ValueError("LIB-063 family census is incomplete")
    root = source.repository_root
    observed_paths: list[str] = []
    included = 0
    for row in census:
        if not isinstance(row, dict) or set(row) != {
            "path",
            "bytes",
            "sha256",
            "normalized_utf8_sha256",
            "disposition",
            "reason",
        }:
            raise ValueError("LIB-063 family census row shape drifted")
        logical = row["path"]
        if not isinstance(logical, str) or not logical.startswith(
            "raw/Creeds.json/creeds/"
        ):
            raise ValueError("LIB-063 family census path drifted")
        path = (root / logical).resolve(strict=True)
        if path.parent != (root / "raw/Creeds.json/creeds").resolve(strict=True):
            raise ValueError("LIB-063 family census path escapes retained family")
        content = path.read_bytes()
        normalized = content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        if (
            row["bytes"] != len(content)
            or row["sha256"] != _sha(content)
            or row["normalized_utf8_sha256"] != _sha(normalized)
        ):
            raise ValueError(f"LIB-063 family census bytes drifted: {logical}")
        disposition = row["disposition"]
        if disposition == "included-lib063":
            if row["reason"] != "assigned to LIB-063":
                raise ValueError("LIB-063 family inclusion reason drifted")
            included += 1
        elif disposition != "excluded-other-library-ticket":
            raise ValueError("LIB-063 family census disposition drifted")
        elif row["reason"] != (
            "outside the LIB-063 frozen work set; retained for another library ticket"
        ):
            raise ValueError("LIB-063 family exclusion reason drifted")
        observed_paths.append(logical)
    physical_paths = [
        path.as_posix()
        for path in sorted((root / "raw/Creeds.json/creeds").glob("*.json"))
    ]
    expected_paths = [str((root / logical).as_posix()) for logical in observed_paths]
    if observed_paths != sorted(observed_paths) or physical_paths != expected_paths:
        raise ValueError(
            "LIB-063 family census does not cover the exact retained family"
        )
    if included != 10:
        raise ValueError("LIB-063 family inclusion count drifted")
    return profile, census


def _scalar(value: object) -> tuple[str, str]:
    if value is None:
        return "json-null", ""
    if isinstance(value, bool):
        return "json-boolean", "true" if value else "false"
    if isinstance(value, (int, float)):
        return "json-number", json.dumps(value, ensure_ascii=False, allow_nan=False)
    if isinstance(value, str):
        return "json-string", value
    raise ValueError(f"unsupported retained JSON scalar {type(value).__name__}")


def _assert_element(
    node: etree._Element,
    local: str,
    attrs: dict[str, str],
    *,
    text: str | None = None,
) -> None:
    if node.tag != f"{{{TEI_NS}}}{local}" or dict(node.attrib) != attrs:
        raise ValueError(f"LIB-063 TEI {local} element or attributes drifted")
    if (node.text or "") != (text or ""):
        raise ValueError(f"LIB-063 TEI {local} direct text drifted")
    if node.tail not in (None, ""):
        raise ValueError(f"LIB-063 TEI {local} tail text drifted")


def _verify_json_node(
    node: etree._Element,
    value: object,
    *,
    work_id: str,
    path: str,
    state: dict[str, object],
) -> None:
    ordinal = int(state["next_ordinal"])
    state["next_ordinal"] = ordinal + 1
    node_id = f"lib063-{work_id}-node-{ordinal:05d}"
    if isinstance(value, dict):
        kind = "json-object"
    elif isinstance(value, list):
        kind = "json-array"
    else:
        kind, _ = _scalar(value)
    _assert_element(node, "div", {XML_ID: node_id, "type": kind})
    row: dict[str, object] = {
        "ordinal": ordinal,
        "json_path": path,
        "kind": kind.removeprefix("json-"),
        "tei_xml_id": node_id,
    }
    children = list(node)
    if isinstance(value, dict):
        state["objects"] = int(state["objects"]) + 1
        row["member_count"] = len(value)
        if len(children) != len(value):
            raise ValueError("LIB-063 TEI JSON object member count drifted")
        for member_ordinal, ((key, child_value), wrapper) in enumerate(
            zip(value.items(), children, strict=True), start=1
        ):
            wrapper_ordinal = int(state["next_ordinal"])
            state["next_ordinal"] = wrapper_ordinal + 1
            wrapper_id = f"lib063-{work_id}-node-{wrapper_ordinal:05d}"
            _assert_element(
                wrapper,
                "div",
                {XML_ID: wrapper_id, "type": "json-member", "n": str(member_ordinal)},
            )
            wrapper_children = list(wrapper)
            if len(wrapper_children) != 2:
                raise ValueError("LIB-063 TEI JSON member shape drifted")
            _assert_element(
                wrapper_children[0],
                "head",
                {"type": "json-key"},
                text=key,
            )
            state["members"] = int(state["members"]) + 1
            state["crosswalk"].append(
                {
                    "ordinal": wrapper_ordinal,
                    "json_path": f"{path}/{key}",
                    "kind": "member",
                    "key": key,
                    "member_ordinal": member_ordinal,
                    "tei_xml_id": wrapper_id,
                }
            )
            _verify_json_node(
                wrapper_children[1],
                child_value,
                work_id=work_id,
                path=f"{path}/{key}",
                state=state,
            )
    elif isinstance(value, list):
        state["arrays"] = int(state["arrays"]) + 1
        row["item_count"] = len(value)
        if len(children) != len(value):
            raise ValueError("LIB-063 TEI JSON array item count drifted")
        for index, (child_value, wrapper) in enumerate(
            zip(value, children, strict=True)
        ):
            wrapper_ordinal = int(state["next_ordinal"])
            state["next_ordinal"] = wrapper_ordinal + 1
            wrapper_id = f"lib063-{work_id}-node-{wrapper_ordinal:05d}"
            _assert_element(
                wrapper,
                "div",
                {XML_ID: wrapper_id, "type": "json-item", "n": str(index)},
            )
            wrapper_children = list(wrapper)
            if len(wrapper_children) != 1:
                raise ValueError("LIB-063 TEI JSON item shape drifted")
            state["items"] = int(state["items"]) + 1
            state["crosswalk"].append(
                {
                    "ordinal": wrapper_ordinal,
                    "json_path": f"{path}/{index}",
                    "kind": "item",
                    "item_index": index,
                    "tei_xml_id": wrapper_id,
                }
            )
            _verify_json_node(
                wrapper_children[0],
                child_value,
                work_id=work_id,
                path=f"{path}/{index}",
                state=state,
            )
    else:
        if len(children) != 1:
            raise ValueError("LIB-063 TEI JSON scalar shape drifted")
        scalar_kind, scalar_text = _scalar(value)
        _assert_element(
            children[0],
            "ab",
            {"type": "json-scalar"},
            text=scalar_text,
        )
        counter = scalar_kind.removeprefix("json-") + "s"
        state[counter] = int(state[counter]) + 1
        row["value_sha256"] = _sha(scalar_text.encode("utf-8"))
        row["value_characters"] = len(scalar_text)
    state["crosswalk"].append(row)


def _readme(work_id: str, title: str, source_path: str, source_sha: str) -> bytes:
    return (
        f"# {title}: retained Creeds.json witness\n\n"
        f"Work ID: `{work_id}`  \n"
        f"Retained source: `{source_path}`  \n"
        f"Literal-byte SHA-256: `{source_sha}`\n\n"
        "The bound repository README states that this member is covered by the "
        "Unlicense because it is not one of the eight named exceptions. That "
        "repository-level statement is retained as rights evidence; edition, "
        "translation, authorship, and worldwide publication conclusions still "
        "require human review. No attribution request is stated for this member.\n\n"
        "This candidate preserves the literal retained JSON bytes in base64 and "
        "also projects every JSON object, member key, array item, scalar value, "
        "and their order into TEI. It is technically verified evidence only: "
        "human review is required, accepted IR is not accepted, and publication "
        "is not ready.\n"
    ).encode("utf-8")


def _unresolved(work_id: str, source_path: str, source_sha: str) -> bytes:
    rows = (
        {
            "id": f"{work_id}-identity-edition-and-translation",
            "scope": work_id,
            "kind": "identity",
            "question": "Which historical edition and English translation does the retained JSON witness represent?",
            "evidence": {"path": source_path, "sha256": source_sha},
            "disposition": "human-review-required",
        },
        {
            "id": f"{work_id}-metadata-claims",
            "scope": work_id,
            "kind": "editorial",
            "question": "Which retained metadata claims are independently supported by a primary witness?",
            "evidence": {"path": source_path, "sha256": source_sha},
            "disposition": "human-review-required",
        },
        {
            "id": f"{work_id}-rights-and-publication",
            "scope": work_id,
            "kind": "rights",
            "question": "Does the repository-level Unlicense evidence suffice for the retained edition and translation in every intended jurisdiction?",
            "evidence": {
                "path": "raw/Creeds.json/README.md",
                "member_path": source_path,
                "member_sha256": source_sha,
            },
            "disposition": "human-review-required-publication-not-ready",
        },
    )
    return b"".join(_canonical(row) for row in rows)


def _verify_header(
    root: etree._Element,
    *,
    work_id: str,
    metadata: dict[str, object],
    source_sha: str,
) -> None:
    if root.tag != f"{{{TEI_NS}}}TEI" or dict(root.attrib) != {
        XML_ID: f"lib063-{work_id}",
        XML_LANG: "en",
    }:
        raise ValueError("LIB-063 TEI root drifted")
    title = metadata["Title"]
    authors = metadata.get("Authors")
    expected_author = (
        "; ".join(str(item) for item in authors)
        if isinstance(authors, list) and authors
        else "Authorship not stated in retained source"
    )
    expected_title = f"{title} — retained Creeds.json witness"
    titles = root.xpath(
        "./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title", namespaces=TEI
    )
    authors_nodes = root.xpath(
        "./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:author", namespaces=TEI
    )
    if len(titles) != 1 or titles[0].text != expected_title:
        raise ValueError("LIB-063 TEI header title drifted")
    if len(authors_nodes) != 1 or authors_nodes[0].text != expected_author:
        raise ValueError("LIB-063 TEI header author drifted")
    expected_contributors = []
    attribution = metadata.get("SourceAttribution")
    if isinstance(attribution, str) and attribution:
        expected_contributors.append(attribution)
    observed_contributors = root.xpath(
        "./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:respStmt/tei:name/text()",
        namespaces=TEI,
    )
    if observed_contributors != expected_contributors:
        raise ValueError("LIB-063 TEI attribution drifted")
    source_url = metadata.get("SourceUrl")
    if not isinstance(source_url, str) or not source_url:
        source_url = "https://github.com/NonlinearFruit/Creeds.json"
    pointers = root.xpath(
        "./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:ptr", namespaces=TEI
    )
    hashes = root.xpath(
        "./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:idno[@type='sha256']",
        namespaces=TEI,
    )
    if len(pointers) != 1 or pointers[0].get("target") != source_url:
        raise ValueError("LIB-063 TEI source URL drifted")
    if len(hashes) != 1 or hashes[0].text != source_sha:
        raise ValueError("LIB-063 TEI source hash drifted")
    rights = root.xpath(
        "./tei:teiHeader/tei:fileDesc/tei:publicationStmt/tei:availability",
        namespaces=TEI,
    )
    if (
        len(rights) != 1
        or rights[0].get("status") != "restricted"
        or "human confirmation" not in "".join(rights[0].itertext())
    ):
        raise ValueError("LIB-063 TEI rights boundary drifted")


def _closure_records(root: Path, policy: dict[str, object]) -> list[dict[str, str]]:
    paths = policy.get("import_closure")
    if not isinstance(paths, list) or not paths:
        raise ValueError("LIB-063 oracle import closure policy is invalid")
    records: list[dict[str, str]] = []
    for logical in paths:
        if (
            not isinstance(logical, str)
            or Path(logical).is_absolute()
            or ".." in Path(logical).parts
        ):
            raise ValueError("LIB-063 oracle import closure path is invalid")
        path = (root / logical).resolve(strict=True)
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError(
                "LIB-063 oracle import closure escapes repository"
            ) from exc
        records.append({"path": logical, "sha256": _sha(path.read_bytes())})
    if [row["path"] for row in records] != sorted(row["path"] for row in records):
        raise ValueError("LIB-063 oracle import closure is not sorted")
    return records


def _closure_digest(root: Path, policy: dict[str, object]) -> str:
    return _sha(_canonical(_closure_records(root, policy)))


def _oracle(
    source_manifest: SourceManifest,
    candidate: CandidatePackage,
) -> dict[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    root_path = source_manifest.repository_root
    work_id = source_manifest.record.get("work_id")
    if not isinstance(work_id, str) or work_id not in WORK_TO_STEM:
        raise ValueError("LIB-063 manifest work identity drifted")
    primary = _one_by_role(source_manifest, "primary-source")
    source_path = str(primary["path"])
    if source_path != f"raw/Creeds.json/creeds/{WORK_TO_STEM[work_id]}.json":
        raise ValueError("LIB-063 manifest primary source path drifted")
    source_bytes = source_manifest.authority_path(str(primary["name"])).read_bytes()
    source_sha = _sha(source_bytes)
    document = _strict_json(source_bytes, "retained Creeds.json member")
    if list(document) != ["Metadata", "Data"]:
        raise ValueError("retained Creeds.json top-level key order drifted")
    metadata = document.get("Metadata")
    if not isinstance(metadata, dict) or not isinstance(metadata.get("Title"), str):
        raise ValueError("retained Creeds.json metadata drifted")
    profile, census = _profile_and_census(source_manifest)
    assigned = profile.get("assigned_members")
    expected_assignment = (
        next(
            (
                row
                for row in assigned
                if isinstance(row, dict) and row.get("work_id") == work_id
            ),
            None,
        )
        if isinstance(assigned, list)
        else None
    )
    normalized_sha = _sha(source_bytes.replace(b"\r\n", b"\n").replace(b"\r", b"\n"))
    if (
        not isinstance(expected_assignment, dict)
        or expected_assignment.get("path") != source_path
        or expected_assignment.get("literal_sha256") != source_sha
        or expected_assignment.get("legacy_normalized_sha256") != normalized_sha
    ):
        raise ValueError("LIB-063 profile work assignment drifted")
    lineage = source_manifest.record.get("catalog_claim_lineage")
    expected_claims = (
        {
            "source_path": f"doctrinal-documents/{work_id}.json",
            "legacy_source_sha256": normalized_sha,
        },
    )
    if (
        not isinstance(lineage, Mapping)
        or lineage.get("contract") != "ocd-catalog-claim-lineage-v1"
        or lineage.get("work_id") != work_id
        or lineage.get("retained_source_sha256") != source_sha
        or lineage.get("claim_count") != 1
        or lineage.get("claims") != expected_claims
    ):
        raise ValueError("LIB-063 catalog claim lineage drifted")

    xml_bytes = candidate.member_bytes("content.tei.xml")
    if not xml_bytes.startswith(b"<?xml version='1.0' encoding='UTF-8'?>\n<TEI "):
        raise ValueError("LIB-063 TEI lexical prolog drifted")
    if not xml_bytes.endswith(b"</TEI>"):
        raise ValueError("LIB-063 TEI lexical root boundary drifted")
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        remove_comments=False,
        remove_pis=False,
        huge_tree=True,
    )
    try:
        tree = etree.fromstring(xml_bytes, parser=parser).getroottree()
    except etree.XMLSyntaxError as exc:
        raise ValueError("LIB-063 TEI is not well formed") from exc
    root = tree.getroot()
    if any(
        isinstance(node, (etree._Comment, etree._ProcessingInstruction))
        for node in root.iter()
    ):
        raise ValueError("LIB-063 TEI contains comments or processing instructions")
    _verify_header(root, work_id=work_id, metadata=metadata, source_sha=source_sha)
    bodies = root.xpath("./tei:text/tei:body", namespaces=TEI)
    if len(bodies) != 1 or len(bodies[0]) != 1:
        raise ValueError("LIB-063 TEI body shape drifted")
    document_div = bodies[0][0]
    _assert_element(
        document_div,
        "div",
        {
            XML_ID: f"lib063-{work_id}-document",
            "type": "retained-json-document",
            "n": work_id,
            "corresp": source_path,
        },
    )
    doc_children = list(document_div)
    if len(doc_children) != 3:
        raise ValueError("LIB-063 TEI document projection shape drifted")
    _assert_element(doc_children[0], "head", {}, text=str(metadata["Title"]))
    _assert_element(
        doc_children[1],
        "div",
        {XML_ID: f"lib063-{work_id}-literal-bytes", "type": "retained-byte-stream"},
    )
    byte_children = list(doc_children[1])
    if len(byte_children) != 1:
        raise ValueError("LIB-063 TEI retained-byte block drifted")
    _assert_element(
        byte_children[0],
        "ab",
        {"type": "base64-application-json"},
        text=base64.b64encode(source_bytes).decode("ascii"),
    )
    try:
        decoded = base64.b64decode(byte_children[0].text or "", validate=True)
    except ValueError as exc:
        raise ValueError("LIB-063 TEI retained-byte block is invalid base64") from exc
    if decoded != source_bytes:
        raise ValueError("LIB-063 TEI retained-byte block does not reproduce source")
    _assert_element(
        doc_children[2],
        "div",
        {XML_ID: f"lib063-{work_id}-semantic-json", "type": "json-semantic-tree"},
    )
    semantic_children = list(doc_children[2])
    if len(semantic_children) != 1:
        raise ValueError("LIB-063 TEI semantic root count drifted")
    state: dict[str, object] = {
        "next_ordinal": 1,
        "objects": 0,
        "arrays": 0,
        "members": 0,
        "items": 0,
        "strings": 0,
        "numbers": 0,
        "booleans": 0,
        "nulls": 0,
        "crosswalk": [],
    }
    _verify_json_node(
        semantic_children[0],
        document,
        work_id=work_id,
        path="$",
        state=state,
    )
    crosswalk = sorted(state["crosswalk"], key=lambda row: int(row["ordinal"]))
    accountability = _strict_json(
        candidate.member_bytes("source-accountability.json"),
        "LIB-063 source accountability",
    )
    expected_accountability = {
        "contract": "ocd-creeds-json-lib063-source-accountability-v1",
        "work_id": work_id,
        "source_path": source_path,
        "source_bytes": len(source_bytes),
        "source_sha256": source_sha,
        "universal_newline_normalized_utf8_sha256": normalized_sha,
        "legacy_claim_semantics": "universal-newline-normalized UTF-8 retained JSON",
        "family_member_count": 43,
        "family_included_count": 10,
        "family_excluded_count": 33,
        "family_census": census,
        "json_counts": {
            key: int(state[key])
            for key in (
                "objects",
                "arrays",
                "members",
                "items",
                "strings",
                "numbers",
                "booleans",
                "nulls",
            )
        },
        "crosswalk": crosswalk,
        "omitted_json_node_count": 0,
        "invented_json_node_count": 0,
    }
    if accountability != expected_accountability:
        raise ValueError("LIB-063 source accountability drifted")
    provenance = _strict_json(
        candidate.member_bytes("provenance.json"), "LIB-063 provenance"
    )
    expected_provenance = {
        "contract": "ocd-creeds-json-lib063-provenance-v1",
        "work_id": work_id,
        "retained_source": {
            "path": source_path,
            "bytes": len(source_bytes),
            "sha256": source_sha,
        },
        "retained_metadata": metadata,
        "rights": {
            "evidence_path": "raw/Creeds.json/README.md",
            "repository_statement": "Unlicense except eight named members; this assigned member is not named",
            "human_review": "required",
        },
        "status": {
            "candidate": "nonaccepted",
            "human_review": "required",
            "accepted_ir": "not_accepted",
            "publication": "not_ready",
        },
        "authority_boundary": (
            "Retained JSON bytes are authority. Legacy parser output and data JSON "
            "are diagnostics only and were not read by the converter."
        ),
    }
    if provenance != expected_provenance:
        raise ValueError("LIB-063 provenance drifted")
    if candidate.member_bytes("README.source.md") != _readme(
        work_id, str(metadata["Title"]), source_path, source_sha
    ):
        raise ValueError("LIB-063 source README drifted")
    if candidate.member_bytes("unresolved.jsonl") != _unresolved(
        work_id, source_path, source_sha
    ):
        raise ValueError("LIB-063 unresolved evidence drifted")
    xsd_path = source_manifest.authority_path(
        str(_one_by_role(source_manifest, "tei-validation-schema")["name"])
    )
    schema = etree.XMLSchema(etree.parse(str(xsd_path)))
    if not schema.validate(tree):
        raise ValueError(
            f"LIB-063 TEI P5 validation failed: {schema.error_log.last_error}"
        )
    policy_bytes = _authority_bytes(source_manifest, "independent-validation-policy")
    policy = _strict_json(policy_bytes, "LIB-063 validation policy")
    if (
        policy.get("contract") != "ocd-creeds-json-lib063-validation-policy-v1"
        or policy.get("candidate_status") != "nonaccepted"
    ):
        raise ValueError("LIB-063 validation policy drifted")
    closure_sha = _closure_digest(root_path, policy)
    validator = source_manifest.record.get("validator")
    if (
        not isinstance(validator, Mapping)
        or validator.get("import_closure_sha256") != closure_sha
    ):
        raise ValueError("LIB-063 oracle import closure drifted")
    facts = MechanicalFacts(
        validator_implementation_sha256=_sha(Path(__file__).read_bytes()),
        validator_import_closure_sha256=closure_sha,
        source_sha256=source_sha,
        profile_sha256=str(
            _one_by_role(source_manifest, "complete-source-feature-profile")["sha256"]
        ),
        package_schema_sha256=str(
            _one_by_role(source_manifest, "candidate-package-schema")["sha256"]
        ),
        xsd_sha256=str(
            _one_by_role(source_manifest, "tei-validation-schema")["sha256"]
        ),
        policy_sha256=_sha(policy_bytes),
        findings=(),
    )
    return verify_mechanical_facts(source_manifest, candidate, facts).as_record()


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION


__all__ = ("ORACLE_ID", "ORACLE_VERSION", "_closure_digest", "_oracle")
