"""Producer-independent oracle for six exact LIB-015 theology witnesses."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import platform
import sys
from typing import Mapping

from jsonschema import Draft202012Validator
from lxml import etree


ORACLE_ID = "ocd-lib015-gutenberg-theology-independent-oracle"
ORACLE_VERSION = "1"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
NS = {"tei": TEI_NS}
SPECS = {
    "dabney-systematic-theology": ("syllabusnotesof00dabn_djvu.txt", 2_440_828, "2db4ddb5b9684e64797a2a963c55fef5b859affbd140291a758c464e24d4658a", 36_714, "Syllabus and Notes of the Course of Systematic and Polemic Theology", "Robert Lewis Dabney", None),
    "miley-systematic-theology-vol-1": ("systematictheolo01mile_djvu.txt", 1_684_078, "ae20e73d6895a4f88d207e2f9991107252bc59875166c6eb7435e862abbd22f3", 28_411, "Systematic Theology", "John Miley", "1"),
    "miley-systematic-theology-vol-2": ("systematictheolo02mile_djvu.txt", 1_658_840, "c6d86e0e335345d358b97c961ec660f3a8c7c06c4e53ca218802e159945416f0", 30_722, "Systematic Theology", "John Miley", "2"),
    "shedd-dogmatic-theology-vol-1": ("dogmatictheology01sheduoft_djvu.txt", 1_309_299, "bb27e8a8bd3b3eb603bd822982786dc83817cca574b79c97ef10d00c129ce58a", 22_524, "Dogmatic Theology", "William G. T. Shedd", "1"),
    "shedd-dogmatic-theology-vol-2": ("dogmatictheology02sheduoft_djvu.txt", 1_989_151, "18a47d3f1dc36cbada22bb9ad017414af33762af65e2d253c773654c2764c534", 35_767, "Dogmatic Theology", "William G. T. Shedd", "2"),
    "shedd-dogmatic-theology-vol-3": ("dogmatictheology03shed_0_djvu.txt", 1_103_532, "3fa48483098ff8372c30d4e96b1dca986bd745ae1f4f309f124b750290f7b62a", 22_818, "Dogmatic Theology", "William G. T. Shedd", "3"),
}
EXPECTED_SOURCE_IDS = {
    "dabney-systematic-theology": "lib015-dabney-systematic-theology-retained",
    "miley-systematic-theology-vol-1": "lib015-miley-systematic-theology-vol-1-retained",
    "miley-systematic-theology-vol-2": "lib015-miley-systematic-theology-vol-2-retained",
    "shedd-dogmatic-theology-vol-1": "lib015-shedd-dogmatic-theology-vol-1-retained",
    "shedd-dogmatic-theology-vol-2": "lib015-shedd-dogmatic-theology-vol-2-retained",
    "shedd-dogmatic-theology-vol-3": "lib015-shedd-dogmatic-theology-vol-3-retained",
}
EXPECTED_AUTHORITY_NAMES = (
    "retained-source",
    "source-readme",
    "reconstruction-profile",
    "source-accountability-schema",
    "validation-policy",
    "tei-p5-xsd",
    "tei-p5-xsd-teix",
    "tei-p5-xsd-xml",
    "candidate-package-schema",
)
LOCAL_AUTHORITIES = {
    "dabney-systematic-theology": ((563, "5fd704e03d1e773c0433369879f0373a5431addd6841e0ff98e349f77841bc9f"), (631, "fdc68039be82136debbf6114ec57a824aa223e892b99738bd81c6cba8beecb17")),
    "miley-systematic-theology-vol-1": ((580, "03353489c6ddd35cd962d13820443f286d97571d3684f7e8c4f3cf88d951e9a6"), (579, "f06385baea11b1d03e51b5e15d13782575424c8c24f2ddd31b0e5921fb8d9f28")),
    "miley-systematic-theology-vol-2": ((580, "1cf94751263898ea0be1e6ddd1d5e17867d5ca4bba388c1bfaf3f444ea3f204e"), (579, "6ffcf312e726524442b8b60fa8dfbbf1b54b61e6dd71a871c0949ce27c975e72")),
    "shedd-dogmatic-theology-vol-1": ((582, "2256648aa8c61c83347b8964ec5afd2067dbb28410a19646afb1b3dcface17c5"), (588, "3f8eb335987603cbc787e7a05941c9b33d48d46545a4aacef8c4e0dfea33c798")),
    "shedd-dogmatic-theology-vol-2": ((582, "66ac05a6a4e6986577a35e48dbca3dc92168fdafccca4e76bccd3cf77ac50842"), (588, "5443f5784970b4c50e70206db11b1e130c4c7161ee3fdae19277eea4cd455ea5")),
    "shedd-dogmatic-theology-vol-3": ((580, "0564259c985e71cb32644aecfe7546a99ad10c60e4b66ed65e55b509d3108e5e"), (586, "9e866de786df3d4f51fdb4b8308d2eaa23b7a0cdce26136844ea58bb50553655")),
}
STATIC_AUTHORITIES = {
    "source-accountability-schema": ("sources/gutenberg-theology-systematics/source-accountability.schema.json", "complete-source-accountability-schema", 2093, "b33e265d7b468ef15b624b943dd23212958ba161d68f423cb2c4734a5789c364"),
    "validation-policy": ("sources/gutenberg-theology-systematics/validation-policy.json", "independent-validation-policy", 163, "2c531384c03d192ee6059d83f31ce6927809f6e975b2877a11ec8d87ad71a769"),
    "tei-p5-xsd": ("ocd_kernel/tei/vendor/xsd/tei_all.xsd", "tei-validation-schema", 1_108_622, "2d886fb9354567ab91d8a52286ef66276c6a932228ccbec04d7c4c9b6aa5a05f"),
    "tei-p5-xsd-teix": ("ocd_kernel/tei/vendor/xsd/tei_all_teix.xsd", "tei-validation-schema-dependency", 2_202, "51ab8c0071f2abc375090829acadf7cb57c707fe17a993cdb2213e84932a6fac"),
    "tei-p5-xsd-xml": ("ocd_kernel/tei/vendor/xsd/tei_all_xml.xsd", "tei-validation-schema-dependency", 2_359, "4f3a8348802f3bc968cbdd2a9d54a38a0549e5e4e7bc8d4338404f85f89568ba"),
    "candidate-package-schema": ("ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json", "candidate-package-schema", 2_173, "3aea71ac3407e3ac9b82a6ba89e13430251de685f8efd2399e1bd5176f41a4e3"),
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def _strict_json(content: bytes, label: str) -> dict[str, object]:
    def reject(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate key {key}")
            result[key] = value
        return result
    try:
        value = json.loads(content.decode("utf-8"), object_pairs_hook=reject)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _authority(source_manifest: object, name: str) -> tuple[Mapping[str, object], Path]:
    authorities = getattr(source_manifest, "record").get("authorities")
    if not isinstance(authorities, tuple):
        raise ValueError("source manifest authorities are invalid")
    for authority in authorities:
        if isinstance(authority, Mapping) and authority.get("name") == name:
            return authority, getattr(source_manifest, "authority_path")(name)
    raise ValueError(f"missing authority {name}")


def _role_authority(source_manifest: object, role: str) -> Mapping[str, object]:
    authorities = getattr(source_manifest, "record").get("authorities")
    matches = [item for item in authorities if isinstance(item, Mapping) and item.get("role") == role]
    if len(matches) != 1:
        raise ValueError(f"expected one {role} authority")
    return matches[0]


def _verify_authorities(source_manifest: object) -> None:
    authorities = getattr(source_manifest, "record").get("authorities")
    names = tuple(item.get("name") for item in authorities if isinstance(item, Mapping))
    if names != EXPECTED_AUTHORITY_NAMES:
        raise ValueError("source manifest authority inventory drifted")
    work_id = str(getattr(source_manifest, "record").get("work_id"))
    if work_id not in SPECS:
        raise ValueError("source manifest work scope drifted")
    filename, byte_count, digest, _, _, _, _ = SPECS[work_id]
    readme, profile = LOCAL_AUTHORITIES[work_id]
    expected = {
        "retained-source": {"bytes": byte_count, "name": "retained-source", "path": f"raw/gutenberg/{filename}", "role": "primary-source", "sha256": digest},
        "source-readme": {"bytes": readme[0], "name": "source-readme", "path": f"sources/gutenberg-theology-systematics/{work_id}/README.source.md", "role": "source-attribution-readme", "sha256": readme[1]},
        "reconstruction-profile": {"bytes": profile[0], "name": "reconstruction-profile", "path": f"sources/gutenberg-theology-systematics/{work_id}/reconstruction-profile.json", "role": "complete-source-feature-profile", "sha256": profile[1]},
    }
    expected.update({name: {"bytes": values[2], "name": name, "path": values[0], "role": values[1], "sha256": values[3]} for name, values in STATIC_AUTHORITIES.items()})
    for name in names:
        authority, path = _authority(source_manifest, str(name))
        if dict(authority) != expected[str(name)]:
            raise ValueError(f"{name} authority record drift")
        content = path.read_bytes()
        if authority.get("bytes") != len(content) or authority.get("sha256") != _sha(content):
            raise ValueError(f"{name} authority bytes drift")


def _source(source_manifest: object) -> tuple[str, bytes, tuple[bytes, ...]]:
    work_id = getattr(source_manifest, "record").get("work_id")
    if work_id not in SPECS:
        raise ValueError("work is outside LIB-015 exact-source scope")
    if getattr(source_manifest, "record").get("source_id") != EXPECTED_SOURCE_IDS[str(work_id)]:
        raise ValueError("source identity drift")
    _, byte_count, digest, line_count, _, _, _ = SPECS[str(work_id)]
    content = _authority(source_manifest, "retained-source")[1].read_bytes()
    if len(content) != byte_count or _sha(content) != digest or content.startswith(b"\xef\xbb\xbf") or not content.endswith(b"\n") or b"\r" in content:
        raise ValueError("retained source identity or framing drift")
    content.decode("utf-8", errors="strict")
    lines = tuple(content.split(b"\n")[:-1])
    if len(lines) != line_count:
        raise ValueError("retained source line census drift")
    return str(work_id), content, lines


def _crosswalk(work_id: str, lines: tuple[bytes, ...]) -> list[dict[str, object]]:
    byte_count = SPECS[work_id][1]
    result: list[dict[str, object]] = []
    offset = 0
    for number, line in enumerate(lines, 1):
        record = line + b"\n"
        end = offset + len(record)
        text = line.decode("utf-8", errors="strict")
        line_id = f"{work_id}-line-{number:05d}"
        result.append({"id": line_id, "line": number, "byte_start": offset, "byte_end": end, "record_sha256": _sha(record), "text_sha256": _sha(text.encode("utf-8")), "disposition": "represented", "target": f"#{line_id}"})
        offset = end
    if offset != byte_count:
        raise ValueError("independent source byte accounting does not close")
    return result


def _profile_policy(source_manifest: object, work_id: str) -> tuple[dict[str, object], dict[str, object]]:
    filename, byte_count, digest, line_count, title, creator, volume = SPECS[work_id]
    profile = _strict_json(_authority(source_manifest, "reconstruction-profile")[1].read_bytes(), "profile")
    policy = _strict_json(_authority(source_manifest, "validation-policy")[1].read_bytes(), "policy")
    expected_profile = {"contract": "ocd-lib015-reconstruction-profile-v1", "ticket": "LIB-015", "work_id": work_id, "title": title, "creator": creator, "volume": volume, "source": {"logical_path": f"raw/gutenberg/{filename}", "bytes": byte_count, "sha256": digest, "physical_lines": line_count, "encoding": "UTF-8", "line_ending": "LF", "terminal_lf": True}, "coverage": {"represented_lines": line_count, "omitted_lines": 0, "duplicated_lines": 0}, "ocr_uncertainty": "preserve every retained reading; no silent correction"}
    if profile != expected_profile:
        raise ValueError("profile binding drift")
    if policy != {"candidate_status": "nonaccepted", "contract": "ocd-lib015-validation-policy-v1", "human_acceptance_required": True, "publication_authorized": False, "ticket": "LIB-015"}:
        raise ValueError("policy acceptance boundary drift")
    return profile, policy


def _validate_tei(source_manifest: object, candidate: object, work_id: str, lines: tuple[bytes, ...]) -> None:
    filename, byte_count, digest, line_count, title, creator, volume = SPECS[work_id]
    content = getattr(candidate, "member_bytes")("content.tei.xml")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=False)
    root = etree.fromstring(content, parser)
    etree.XMLSchema(etree.parse(str(_authority(source_manifest, "tei-p5-xsd")[1]))).assertValid(etree.ElementTree(root))
    if root.tag != f"{{{TEI_NS}}}TEI" or root.attrib != {f"{{{XML_NS}}}id": f"{work_id}-candidate"}:
        raise ValueError("TEI root scope drift")
    volume_suffix = f"; volume {volume}" if volume else ""
    expected_header = {
        "./tei:fileDesc/tei:titleStmt/tei:title": f"{title}{volume_suffix}: faithful retained-source candidate",
        "./tei:fileDesc/tei:titleStmt/tei:author": creator,
        "./tei:fileDesc/tei:titleStmt/tei:respStmt/tei:resp": "Exact OCR physical-line transcription",
        "./tei:fileDesc/tei:titleStmt/tei:respStmt/tei:name": "Open Christian Data",
        "./tei:fileDesc/tei:publicationStmt/tei:publisher": "Open Christian Data",
        "./tei:fileDesc/tei:publicationStmt/tei:availability/tei:p": "Nonaccepted candidate; publication is not authorized; human identity, edition, rights, textual, and editorial review remain separate.",
        "./tei:fileDesc/tei:sourceDesc/tei:bibl/tei:title": title,
        "./tei:fileDesc/tei:sourceDesc/tei:bibl/tei:author": creator,
        "./tei:fileDesc/tei:sourceDesc/tei:bibl/tei:idno[@type='local-path']": f"raw/gutenberg/{filename}",
        "./tei:fileDesc/tei:sourceDesc/tei:bibl/tei:idno[@type='SHA-256']": digest,
        "./tei:fileDesc/tei:sourceDesc/tei:bibl/tei:extent": f"{byte_count} bytes; {line_count} UTF-8 LF-terminated OCR physical lines",
        "./tei:encodingDesc/tei:projectDesc/tei:p[1]": "Every retained OCR physical line is represented exactly once, verbatim after LF transport framing removal, and in source order.",
        "./tei:encodingDesc/tei:projectDesc/tei:p[2]": "OCR uncertainty is preserved rather than silently corrected; every line remains marked as an unreviewed OCR reading.",
        "./tei:revisionDesc/tei:change": "Deterministic nonaccepted LIB-015 candidate generated from the pinned witness.",
    }
    header = root.find(f"{{{TEI_NS}}}teiHeader")
    if header is None:
        raise ValueError("TEI header missing")
    for xpath, expected in expected_header.items():
        matches = header.xpath(xpath, namespaces=NS)
        if len(matches) != 1 or matches[0].text != expected:
            raise ValueError(f"TEI metadata drift at {xpath}")
    volume_nodes = header.xpath("./tei:fileDesc/tei:sourceDesc/tei:bibl/tei:biblScope", namespaces=NS)
    if volume is None:
        if volume_nodes:
            raise ValueError("unexpected TEI volume")
    elif len(volume_nodes) != 1 or volume_nodes[0].text != volume or dict(volume_nodes[0].attrib) != {"unit": "volume"}:
        raise ValueError("TEI volume drift")
    availability = header.xpath("./tei:fileDesc/tei:publicationStmt/tei:availability", namespaces=NS)
    change = header.xpath("./tei:revisionDesc/tei:change", namespaces=NS)
    bibl = header.xpath("./tei:fileDesc/tei:sourceDesc/tei:bibl", namespaces=NS)
    if len(availability) != 1 or dict(availability[0].attrib) != {"status": "restricted"} or len(change) != 1 or dict(change[0].attrib) != {"status": "draft"} or len(bibl) != 1 or bibl[0].get(f"{{{XML_NS}}}id") != f"{work_id}-retained-source":
        raise ValueError("TEI metadata attributes drift")
    text_node = root.find(f"{{{TEI_NS}}}text")
    file_desc = header.find(f"{{{TEI_NS}}}fileDesc")
    encoding_desc = header.find(f"{{{TEI_NS}}}encodingDesc")
    revision_desc = header.find(f"{{{TEI_NS}}}revisionDesc")
    if text_node is None or file_desc is None or encoding_desc is None or revision_desc is None:
        raise ValueError("TEI required structure missing")
    expected_bibl_children = ["title", "author"] + (["biblScope"] if volume else []) + ["idno", "idno", "extent"]
    exact_children = (
        (root, ["teiHeader", "text"]),
        (header, ["fileDesc", "encodingDesc", "revisionDesc"]),
        (file_desc, ["titleStmt", "publicationStmt", "sourceDesc"]),
        (file_desc[0], ["title", "author", "respStmt"]),
        (file_desc[0][2], ["resp", "name"]),
        (file_desc[1], ["publisher", "availability"]),
        (file_desc[1][1], ["p"]),
        (file_desc[2], ["bibl"]),
        (bibl[0], expected_bibl_children),
        (encoding_desc, ["projectDesc"]),
        (encoding_desc[0], ["p", "p"]),
        (revision_desc, ["change"]),
        (text_node, ["body"]),
        (text_node[0], ["div"]),
    )
    for parent, expected_names in exact_children:
        if [etree.QName(child).localname for child in parent] != expected_names:
            raise ValueError(f"TEI complete structure drift at {etree.QName(parent).localname}")
    title_stmt = file_desc[0]
    publication_stmt = file_desc[1]
    source_desc = file_desc[2]
    project_desc = encoding_desc[0]
    body = text_node[0]
    division_node = body[0]
    expected_div_attrs = {f"{{{XML_NS}}}id": f"{work_id}-retained-lines", "type": "theology", "subtype": "retained-ocr-transcription"}
    exact_attributes = (
        (root, {f"{{{XML_NS}}}id": f"{work_id}-candidate"}),
        (header, {}), (file_desc, {}), (title_stmt, {}), (title_stmt[0], {}), (title_stmt[1], {}),
        (title_stmt[2], {}), (title_stmt[2][0], {}), (title_stmt[2][1], {}),
        (publication_stmt, {}), (publication_stmt[0], {}), (publication_stmt[1], {"status": "restricted"}), (publication_stmt[1][0], {}),
        (source_desc, {}), (bibl[0], {f"{{{XML_NS}}}id": f"{work_id}-retained-source"}),
        (encoding_desc, {}), (project_desc, {}), (project_desc[0], {}), (project_desc[1], {}),
        (revision_desc, {}), (revision_desc[0], {"status": "draft"}),
        (text_node, {}), (body, {}), (division_node, expected_div_attrs),
    )
    for node, expected_attrs in exact_attributes:
        if dict(node.attrib) != expected_attrs:
            raise ValueError(f"TEI attributes drift at {etree.QName(node).localname}")
    bibl_children = list(bibl[0])
    bibl_attr_expectations = [{}, {}] + ([{"unit": "volume"}] if volume else []) + [{"type": "local-path"}, {"type": "SHA-256"}, {}]
    if [dict(node.attrib) for node in bibl_children] != bibl_attr_expectations:
        raise ValueError("TEI bibliography attributes drift")
    leaves = [title_stmt[0], title_stmt[1], title_stmt[2][0], title_stmt[2][1], publication_stmt[0], publication_stmt[1][0], *bibl_children, project_desc[0], project_desc[1], revision_desc[0]]
    if any(len(node) != 0 for node in leaves):
        raise ValueError("TEI leaf-content invention drift")
    idnos = bibl[0].xpath("./tei:idno", namespaces=NS)
    if [dict(node.attrib) for node in idnos] != [{"type": "local-path"}, {"type": "SHA-256"}]:
        raise ValueError("TEI source identifier attributes drift")
    if any(node.tail is not None for node in root.iter()) or any(node.text is not None for node in (root, header, file_desc, title_stmt, file_desc[0][2], file_desc[1], file_desc[1][1], file_desc[2], bibl[0], encoding_desc, encoding_desc[0], revision_desc, text_node, text_node[0], text_node[0][0])):
        raise ValueError("TEI container text or tail drift")
    division = root.xpath("./tei:text/tei:body/tei:div", namespaces=NS)
    if len(division) != 1 or dict(division[0].attrib) != expected_div_attrs:
        raise ValueError("TEI work scope drift")
    nodes = list(division[0])
    if len(nodes) != len(lines):
        raise ValueError("TEI line omission, duplication, or invention")
    reconstructed: list[bytes] = []
    for number, (node, line) in enumerate(zip(nodes, lines, strict=True), 1):
        text = line.decode("utf-8", errors="strict")
        expected_attrs = {f"{{{XML_NS}}}id": f"{work_id}-line-{number:05d}", "n": str(number), "ana": "#source-line #ocr-source #unreviewed-reading"}
        if node.tag != f"{{{TEI_NS}}}ab" or dict(node.attrib) != expected_attrs or len(node) or node.tail is not None or (node.text or "") != text:
            raise ValueError(f"TEI order, text, uncertainty, or scope drift at line {number}")
        reconstructed.append(text.encode("utf-8") + b"\n")
    if b"".join(reconstructed) != _authority(source_manifest, "retained-source")[1].read_bytes():
        raise ValueError("TEI does not losslessly reconstruct retained bytes")


def _validate_members(source_manifest: object, candidate: object, work_id: str, lines: tuple[bytes, ...], profile: Mapping[str, object]) -> None:
    filename, byte_count, digest, line_count, title, creator, volume = SPECS[work_id]
    package = _strict_json(getattr(candidate, "member_bytes")("manifest.json"), "candidate manifest")
    Draft202012Validator(_strict_json(_authority(source_manifest, "candidate-package-schema")[1].read_bytes(), "package schema")).validate(package)
    record = getattr(source_manifest, "record")
    expected_source_manifest = {"path": getattr(source_manifest, "path").relative_to(getattr(source_manifest, "repository_root")).as_posix(), "sha256": getattr(source_manifest, "sha256")}
    if package.get("status") != "nonaccepted" or package.get("source_id") != EXPECTED_SOURCE_IDS[work_id] or package.get("source_manifest") != expected_source_manifest or package.get("converter") != dict(record["converter"]) or package.get("package_schema") != dict(record["package_schema"]):
        raise ValueError("candidate manifest binding drift")
    members = package.get("members")
    expected_member_names = ["README.source.md", "content.tei.xml", "provenance.json", "source-accountability.json", "unresolved.jsonl"]
    if not isinstance(members, list) or [item.get("name") for item in members if isinstance(item, dict)] != expected_member_names or len(members) != len(expected_member_names):
        raise ValueError("candidate package member inventory drift")
    crosswalk = _crosswalk(work_id, lines)
    expected_accountability = {"contract": "ocd-lib015-source-accountability-v1", "ticket": "LIB-015", "work_id": work_id, "source_sha256": digest, "source_bytes": byte_count, "physical_lines": line_count, "represented_lines": line_count, "omitted_lines": 0, "duplicated_lines": 0, "member_census": [{"path": f"raw/gutenberg/{filename}", "bytes": byte_count, "sha256": digest, "included": True, "reason": "Exact frozen LIB-015 direct-file witness."}], "excluded_members": [], "crosswalk_sha256": _sha(_canonical(crosswalk)), "crosswalk": crosswalk}
    accountability = _strict_json(getattr(candidate, "member_bytes")("source-accountability.json"), "accountability")
    Draft202012Validator(_strict_json(_authority(source_manifest, "source-accountability-schema")[1].read_bytes(), "accountability schema")).validate(accountability)
    if accountability != expected_accountability:
        raise ValueError("source accountability drift")
    provenance = _strict_json(getattr(candidate, "member_bytes")("provenance.json"), "provenance")
    expected_provenance = {"contract": "ocd-lib015-provenance-v1", "ticket": "LIB-015", "work_id": work_id, "title": title, "creator": creator, "volume": volume, "source_format": "retained UTF-8 LF-terminated OCR text", "source_logical_path": f"raw/gutenberg/{filename}", "source_sha256": digest, "candidate_status": "nonaccepted", "publication_authorized": False, "technical_validation_is_human_acceptance": False, "rights": {"edition": "unresolved", "worldwide": "unresolved", "publication": "not authorized"}}
    if provenance != expected_provenance:
        raise ValueError("candidate provenance or acceptance drift")
    unresolved = [_strict_json(line + b"\n", "unresolved") for line in getattr(candidate, "member_bytes")("unresolved.jsonl").splitlines()]
    expected_unresolved = [
        {"id": f"{work_id}-identity-edition", "kind": "identity-edition", "status": "human-review-required", "scope": "whole retained witness", "detail": "Title, creator, volume, edition, and witness identity remain unaccepted."},
        {"id": f"{work_id}-ocr-readings", "kind": "ocr-reading", "status": "human-review-required", "scope": f"all {line_count} retained OCR physical lines", "detail": "No OCR correction or substantive reading was silently accepted."},
        {"id": f"{work_id}-rights", "kind": "rights", "status": "human-review-required", "scope": "retained witness and candidate", "detail": "Rights and publication permission remain unresolved."},
        {"id": f"{work_id}-acceptance", "kind": "acceptance-publication", "status": "human-review-required", "scope": "whole candidate", "detail": "Technical validation is not human acceptance or publication authorization."},
    ]
    if unresolved != expected_unresolved or getattr(candidate, "member_bytes")("README.source.md") != _authority(source_manifest, "source-readme")[1].read_bytes():
        raise ValueError("unresolved or README binding drift")
    if profile.get("work_id") != work_id:
        raise ValueError("profile work scope drift")


def _oracle(source_manifest: object, candidate: object) -> dict[str, object]:
    getattr(source_manifest, "verify")()
    _verify_authorities(source_manifest)
    getattr(candidate, "verify_integrity")()
    work_id, content, lines = _source(source_manifest)
    profile, _ = _profile_policy(source_manifest, work_id)
    _validate_tei(source_manifest, candidate, work_id, lines)
    _validate_members(source_manifest, candidate, work_id, lines, profile)
    implementation_sha256 = _sha(Path(__file__).read_bytes())
    validator = getattr(source_manifest, "record")["validator"]
    if validator.get("implementation_sha256") != implementation_sha256 or validator.get("import_closure_sha256") != implementation_sha256:
        raise ValueError("oracle implementation closure drift")
    result: dict[str, object] = {"status": "pass", "oracle_id": ORACLE_ID, "oracle_version": ORACLE_VERSION, "implementation_sha256": implementation_sha256, "import_closure_sha256": implementation_sha256, "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})", "source_manifest_sha256": getattr(source_manifest, "sha256"), "candidate_sha256": getattr(candidate, "sha256"), "profile_sha256": _role_authority(source_manifest, "complete-source-feature-profile")["sha256"], "package_schema_sha256": _role_authority(source_manifest, "candidate-package-schema")["sha256"], "source_sha256": _sha(content), "xsd_sha256": _role_authority(source_manifest, "tei-validation-schema")["sha256"], "policy_sha256": _role_authority(source_manifest, "independent-validation-policy")["sha256"], "findings": []}
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
