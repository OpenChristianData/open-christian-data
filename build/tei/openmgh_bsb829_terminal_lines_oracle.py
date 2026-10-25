"""Independent source-tree check for two bsb829 terminal-line slices."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import platform
import sys

from lxml import etree
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.tei.install_accepted import _io_path


TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
ORACLE_ID = "ocd-openmgh-bsb829-terminal-lines-source-oracle"
ORACLE_VERSION = "1"


def _sha(value: bytes) -> str:
    return sha256(value).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _same(left: etree._Element, right: etree._Element, *, root: bool = False) -> bool:
    if (left.tag != right.tag or dict(left.attrib) != dict(right.attrib)
            or left.text != right.text or len(left) != len(right)
            or (not root and left.tail != right.tail)):
        return False
    return all(_same(a, b) for a, b in zip(left, right, strict=True))


def check(source_bytes: bytes, candidate_bytes: bytes, *, division: int,
          first_id: str, last_line_id: str, next_line_id: str) -> dict:
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False,
                             no_network=True, remove_comments=False, huge_tree=True)
    source = etree.fromstring(source_bytes, parser)
    actual = etree.fromstring(candidate_bytes, parser)
    if source.getroottree().docinfo.doctype or actual.getroottree().docinfo.doctype:
        raise ValueError("source or candidate DOCTYPE is forbidden")
    body = source.find(f"{TEI}text/{TEI}body")
    if body is None or len(body) != 1 or body[0].get("type") != "volume":
        raise ValueError("source volume envelope differs")
    divisions = list(body[0])
    if len(divisions) != 21 or division not in (6, 15):
        raise ValueError("source division inventory differs")
    source_div = divisions[division - 1]
    if len(source_div) != 1 or source_div[0].tag != f"{TEI}ab":
        raise ValueError("source flat container differs")
    source_ab = source_div[0]
    children = list(source_ab)
    positions = {node.get(XML_ID): i for i, node in enumerate(children) if node.get(XML_ID)}
    counts = Counter(node.get(XML_ID) for node in source.iter() if node.get(XML_ID))
    if any(counts[identifier] != 1 for identifier in (first_id, last_line_id, next_line_id)):
        raise ValueError("source endpoint absent or repeated")
    start, last_line, stop = (positions[identifier] for identifier in
                              (first_id, last_line_id, next_line_id))
    if not (start <= last_line < stop) or any(
        children[i].tag != f"{TEI}lb" for i in (start, last_line, stop)
    ):
        raise ValueError("terminal-line boundaries differ")
    if any(node.tag == f"{TEI}lb" for node in children[last_line + 1:stop]):
        raise ValueError("unexpected line break before next section")
    expected = etree.Element(f"{TEI}ab", attrib=dict(source_ab.attrib))
    for node in children[start:stop]:
        expected.append(deepcopy(node))
    candidate_body = actual.find(f"{TEI}text/{TEI}body")
    if (actual.tag != f"{TEI}TEI" or candidate_body is None
            or len(candidate_body) != 1 or candidate_body[0].get("type") != "work"
            or len(candidate_body[0]) != 1
            or candidate_body[0][0].tag != f"{TEI}ab"
            or not _same(expected, candidate_body[0][0], root=True)):
        raise ValueError("source and candidate terminal-line trees differ")
    ids = {node.get(XML_ID) for node in expected.iter() if node.get(XML_ID)}
    for node in expected.iter():
        if node.tag == f"{TEI}w":
            refs = (node.get("corresp") or "").split()
            if len(refs) < 2 or f"#{node.get(XML_ID)}" not in refs or any(
                not ref.startswith("#") or ref[1:] not in ids for ref in refs
            ):
                raise ValueError("source word-segment linkage is not locally closed")
        target = node.get("target")
        if target and (not target.startswith("#") or target[1:] not in ids):
            raise ValueError("source target is not locally closed")
    old_file = source.find(f"{TEI}teiHeader/{TEI}fileDesc")
    new_file = actual.find(f"{TEI}teiHeader/{TEI}fileDesc")
    if old_file is None or new_file is None:
        raise ValueError("source or candidate file description absent")
    for suffix in (f"{TEI}publicationStmt", f"{TEI}sourceDesc/{TEI}biblFull"):
        old = old_file.find(suffix)
        new = new_file.find(suffix)
        if old is None or new is None or not _same(old, new, root=True):
            raise ValueError("source publication or bibliography differs")
    return {
        "status": "pass",
        "source_sha256": sha256(source_bytes).hexdigest(),
        "selection_c14n_sha256": sha256(
            etree.tostring(expected, method="c14n", with_comments=True)
        ).hexdigest(),
        "first_child_index": start,
        "last_line_child_index": last_line,
        "last_selected_child_index": stop - 1,
        "next_line_child_index": stop,
        "element_count": sum(isinstance(node.tag, str) for node in expected.iter()),
        "xml_id_count": len(ids),
        "outside_fragment_target_count": 0,
    }


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> dict:
    source_manifest.verify()
    candidate.verify_integrity()
    profile_path = source_manifest.authority_path("reconstruction-profile")
    policy_path = source_manifest.authority_path("validation-policy")
    plan_path = source_manifest.authority_path("selection-plan")
    boundary_path = source_manifest.authority_path("boundary-review")
    source = source_manifest.authority_path("extracted-xml").read_bytes()
    work = json.loads(source_manifest.authority_path("work-sidecar").read_bytes())
    profile = json.loads(profile_path.read_bytes())
    policy = json.loads(policy_path.read_bytes())
    plan = json.loads(plan_path.read_bytes())
    boundary = json.loads(boundary_path.read_bytes())
    if (profile.get("contract") != "ocd-openmgh-bsb829-terminal-lines-profile-v1"
            or policy.get("contract") != "ocd-openmgh-bsb829-terminal-lines-policy-v1"
            or plan.get("contract") != "ocd-openmgh-bsb829-terminal-lines-selection-v1"
            or boundary.get("contract") != "ocd-openmgh-bsb829-terminal-lines-boundary-v1"
            or _sha(plan_path.read_bytes()) != profile["selection_plan_sha256"]
            or _sha(source) != profile["source_sha256"]):
        raise ValueError("source, selection, or policy differs")
    if work.get("work_id") != profile["work_id"] or work.get("title") != profile["work_title"]:
        raise ValueError("work identity differs")
    editions = [edition for form in work["textual_forms"] for edition in form["editions"]]
    if len(editions) != 1:
        raise ValueError("ambiguous work edition")
    declared = [value.split("#", 1)[1] for value in
                editions[0]["containing_source"]["locator"].split("; ")]
    if declared != profile["declared_locator_ids"]:
        raise ValueError("declared source locators differ")
    entries = [item for item in plan["works"] if item["work_id"] == profile["work_id"]]
    fields = (
        "division", "first_id", "last_line_id", "next_line_id",
        "first_child_index", "last_line_child_index", "last_selected_child_index",
        "next_line_child_index", "terminal_word_ids", "scope_note",
    )
    if len(entries) != 1 or any(
        entries[0][key] != profile[key] or boundary[key] != profile[key] for key in fields
    ):
        raise ValueError("profile, boundary, or selection plan differs")
    acquisition_bytes = Path(_io_path(
        source_manifest.repository_root / profile["acquisition_path"]
    )).read_bytes()
    acquisition = json.loads(acquisition_bytes)
    if (acquisition.get("acquisition_id") != profile["acquisition_id"]
            or acquisition.get("edition_id") != profile["edition_id"]
            or acquisition.get("source_path") != profile["source_path"]
            or acquisition.get("source_sha256") != _sha(source)
            or _sha(acquisition_bytes) != profile["acquisition_sha256"]):
        raise ValueError("acquisition and extracted source differ")
    content = candidate.member_bytes("content.tei.xml")
    if _sha(content) != profile["candidate_sha256"]:
        raise ValueError("candidate differs from inspected direct result")
    result = check(source, content, division=profile["division"],
                   first_id=profile["first_id"],
                   last_line_id=profile["last_line_id"],
                   next_line_id=profile["next_line_id"])
    if any(result[key] != profile[key] for key in (
        "selection_c14n_sha256", "first_child_index", "last_line_child_index",
        "last_selected_child_index", "next_line_child_index",
    )):
        raise ValueError("candidate source selection differs")
    xml = etree.fromstring(content, etree.XMLParser(
        resolve_entities=False, load_dtd=False, no_network=True, huge_tree=True))
    if xml.get(XML_ID) != f"ocd-{profile['work_id']}-bsb829-terminal-lines-electronic-v1":
        raise ValueError("candidate document identity differs")
    title = xml.find(f"{TEI}teiHeader/{TEI}fileDesc/{TEI}titleStmt/{TEI}title")
    if title is None or title.text != profile["work_title"]:
        raise ValueError("candidate title differs")
    etree.XMLSchema(etree.parse(str(
        source_manifest.authority_path("tei-p5-xsd")
    ))).assertValid(xml)
    accounting = json.loads(candidate.member_bytes("source-accountability.json"))
    if (accounting.get("contract") != "ocd-openmgh-bsb829-terminal-lines-accounting-v1"
            or any(accounting.get(key) != profile[key] for key in (
                "work_id", "edition_id", "acquisition_id", "source_path",
                "source_sha256", *fields, "selection_c14n_sha256",
                "selection_plan_sha256",
            ))):
        raise ValueError("candidate source accounting differs")
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    if (provenance.get("status") != "nonaccepted"
            or provenance.get("work_id") != profile["work_id"]
            or provenance.get("canonical_ir_written") is not False
            or not candidate.member_bytes("unresolved.jsonl").strip()
            or b"Monumenta" not in candidate.member_bytes("README.source.md")):
        raise ValueError("candidate provenance differs")
    closure = _json([
        {"path": path, "sha256": _sha(
            Path(_io_path(source_manifest.repository_root / path)).read_bytes())}
        for path in policy["closure_inputs"]
    ])
    outcome = {
        "status": "pass", "oracle_id": ORACLE_ID, "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": _sha(closure),
        "runtime": (f"{platform.python_implementation()} {platform.python_version()} "
                    f"({Path(sys.executable).resolve(strict=True)})"),
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(profile_path.read_bytes()),
        "package_schema_sha256": _sha(
            source_manifest.authority_path("candidate-package-schema").read_bytes()),
        "source_sha256": _sha(source),
        "xsd_sha256": _sha(source_manifest.authority_path("tei-p5-xsd").read_bytes()),
        "policy_sha256": _sha(policy_path.read_bytes()),
        "findings": [],
    }
    outcome["result_sha256"] = _sha(_json(outcome))
    return outcome


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
