"""Independent source-tree oracle for ten bsb829 flat line-bounded works."""

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
ORACLE_ID = "ocd-openmgh-bsb829-flat-slices-source-oracle"
ORACLE_VERSION = "1"


def _sha(value: bytes) -> str:
    return sha256(value).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _equivalent(source: etree._Element, result: etree._Element, *, outer: bool = False) -> bool:
    if (source.tag != result.tag or dict(source.attrib) != dict(result.attrib)
            or source.text != result.text or len(source) != len(result)):
        return False
    if not outer and source.tail != result.tail:
        return False
    return all(_equivalent(a, b) for a, b in zip(source, result, strict=True))


def check(source_bytes: bytes, candidate_bytes: bytes, *, division: int,
          first_id: str, last_id: str) -> dict[str, object]:
    parser = etree.XMLParser(resolve_entities=False, no_network=True,
                             remove_comments=False, huge_tree=True)
    source = etree.fromstring(source_bytes, parser)
    candidate = etree.fromstring(candidate_bytes, parser)
    if source.getroottree().docinfo.doctype or candidate.getroottree().docinfo.doctype:
        raise ValueError("DOCTYPE is forbidden")
    volume = source.find(f"{TEI}text/{TEI}body")
    if volume is None or len(volume) != 1 or volume[0].get("type") != "volume":
        raise ValueError("source volume changed")
    divisions = list(volume[0])
    if len(divisions) != 21 or division not in (6, 15):
        raise ValueError("source division inventory changed")
    source_div = divisions[division - 1]
    if len(source_div) != 1 or source_div[0].tag != f"{TEI}ab":
        raise ValueError("source flat ab changed")
    source_ab = source_div[0]
    children = list(source_ab)
    locations = {node.get(XML_ID): index for index, node in enumerate(children)
                 if node.get(XML_ID)}
    occurrences = Counter(node.get(XML_ID) for node in source.iter() if node.get(XML_ID))
    if (occurrences[first_id] != 1 or occurrences[last_id] != 1
            or first_id not in locations or last_id not in locations):
        raise ValueError("flat locator is absent or repeated")
    start, end = locations[first_id], locations[last_id]
    if start > end or children[start].tag != f"{TEI}lb" or children[end].tag != f"{TEI}lb":
        raise ValueError("flat span does not use ordered line breaks")
    expected = etree.Element(f"{TEI}ab", attrib=dict(source_ab.attrib))
    for node in children[start:end + 1]:
        expected.append(deepcopy(node))
    body = candidate.find(f"{TEI}text/{TEI}body")
    if (candidate.tag != f"{TEI}TEI" or body is None or len(body) != 1
            or body[0].get("type") != "work" or len(body[0]) != 1
            or body[0][0].tag != f"{TEI}ab"):
        raise ValueError("candidate is not one line-bounded work")
    actual = body[0][0]
    if not _equivalent(expected, actual, outer=True):
        raise ValueError("source and candidate line trees differ")
    selected_ids = {node.get(XML_ID) for node in expected.iter() if node.get(XML_ID)}
    external = [node.get("target") for node in expected.iter() if node.get("target")
                and (not node.get("target").startswith("#")
                     or node.get("target")[1:] not in selected_ids)]
    if external:
        raise ValueError(f"outside fragment targets: {external[:3]}")
    broken_words = [node.get(XML_ID) for node in expected.iter() if node.tag == f"{TEI}w"
                    and any(not ref.startswith("#") or ref[1:] not in selected_ids
                            for ref in (node.get("corresp") or "").split())]
    if broken_words:
        raise ValueError(f"cross-boundary source word links: {broken_words[:3]}")
    return {"status": "pass", "source_sha256": _sha(source_bytes),
            "selection_c14n_sha256": _sha(etree.tostring(expected, method="c14n", with_comments=True)),
            "first_child_index": start, "last_child_index": end,
            "element_count": sum(1 for node in expected.iter() if isinstance(node.tag, str)),
            "xml_id_count": len(selected_ids), "external_fragment_target_count": 0}


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> dict[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    profile_path = source_manifest.authority_path("reconstruction-profile")
    policy_path = source_manifest.authority_path("validation-policy")
    plan_path = source_manifest.authority_path("selection-plan")
    review_path = source_manifest.authority_path("reviewed-selection-plan")
    probe_path = source_manifest.authority_path("projection-probe")
    profile = json.loads(profile_path.read_bytes())
    policy = json.loads(policy_path.read_bytes())
    plan = json.loads(plan_path.read_bytes())
    if (profile.get("contract") != "ocd-openmgh-bsb829-flat-slices-profile-v1"
            or policy.get("contract") != "ocd-openmgh-bsb829-flat-slices-policy-v1"
            or plan.get("contract") != "ocd-openmgh-bsb829-flat-slices-stage-plan-v1"):
        raise ValueError("profile, plan, or policy changed")
    if (_sha(plan_path.read_bytes()) != profile["selection_plan_sha256"]
            or _sha(review_path.read_bytes()) != profile["review_plan_sha256"]
            or _sha(probe_path.read_bytes()) != profile["projection_probe_sha256"]
            or plan["review_plan_sha256"] != profile["review_plan_sha256"]
            or plan["projection_probe_sha256"] != profile["projection_probe_sha256"]
            or len(plan["works"]) != 10 or len(plan["held"]) != 2):
        raise ValueError("closed review/projection plan differs")
    source = source_manifest.authority_path("extracted-xml").read_bytes()
    work = json.loads(source_manifest.authority_path("work-sidecar").read_bytes())
    boundary = json.loads(source_manifest.authority_path("boundary-review").read_bytes())
    acquisition_path = source_manifest.repository_root / profile["acquisition_path"]
    acquisition_bytes = Path(_io_path(acquisition_path)).read_bytes()
    if _sha(acquisition_bytes) != profile["acquisition_sha256"]:
        raise ValueError("acquisition sidecar changed")
    acquisition = json.loads(acquisition_bytes)
    if (work.get("work_id") != profile["work_id"]
            or work.get("title") != profile["work_title"]
            or acquisition.get("acquisition_id") != profile["acquisition_id"]
            or acquisition.get("edition_id") != profile["edition_id"]
            or acquisition.get("source_path") != profile["source_path"]
            or acquisition.get("source_sha256") != _sha(source)):
        raise ValueError("source/work/acquisition identity changed")
    declared = [value.split("#", 1)[1] for value in
                work["textual_forms"][0]["editions"][0]["containing_source"]["locator"].split("; ")]
    if declared != profile["declared_locator_ids"]:
        raise ValueError("declared locator sequence changed")
    entries = [item for item in plan["works"] if item["work_id"] == profile["work_id"]]
    if len(entries) != 1 or any(entries[0].get(key) != profile[key]
                                    for key in ("division", "first_id", "last_id", "scope_note")):
        raise ValueError("reviewed selection plan differs")
    probe = json.loads(probe_path.read_bytes())
    probe_rows = [item for item in probe["rows"] if item["work_id"] == profile["work_id"]]
    if (len(probe_rows) != 1 or probe_rows[0]["projection"] != "pass"
            or probe_rows[0]["outside_word_links"]
            or probe_rows[0]["candidate_sha256"] !=
               _sha(candidate.member_bytes("content.tei.xml"))):
        raise ValueError("native projection closure or original candidate differs")
    bound_fields = ("work_id", "source_path", "source_sha256", "division", "first_id",
                    "last_id", "first_child_index", "last_child_index", "declared_locator_ids",
                    "scope_note", "selection_c14n_sha256", "shared_matter_disposition",
                    "unassigned_fragment_disposition")
    if any(boundary.get(key) != profile.get(key) for key in bound_fields):
        raise ValueError("boundary and profile differ")
    result = check(source, candidate.member_bytes("content.tei.xml"),
                   division=profile["division"], first_id=profile["first_id"],
                   last_id=profile["last_id"])
    if (result["selection_c14n_sha256"] != profile["selection_c14n_sha256"]
            or result["first_child_index"] != profile["first_child_index"]
            or result["last_child_index"] != profile["last_child_index"]):
        raise ValueError("source line span differs")
    xml = etree.fromstring(candidate.member_bytes("content.tei.xml"),
                           etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    source_xml = etree.fromstring(source,
                                  etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    if xml.get(XML_ID) != f"ocd-{profile['work_id']}-bsb829-flat-slices-electronic-v1":
        raise ValueError("candidate identity changed")
    title = xml.find(f"{TEI}teiHeader/{TEI}fileDesc/{TEI}titleStmt/{TEI}title")
    if title is None or title.text != profile["work_title"]:
        raise ValueError("candidate title changed")
    for suffix in (f"{TEI}publicationStmt", f"{TEI}sourceDesc/{TEI}biblFull"):
        old = source_xml.find(f"{TEI}teiHeader/{TEI}fileDesc/{suffix}")
        new = xml.find(f"{TEI}teiHeader/{TEI}fileDesc/{suffix}")
        if old is None or new is None or not _equivalent(old, new, outer=True):
            raise ValueError("source license or bibliography changed")
    etree.XMLSchema(etree.parse(str(source_manifest.authority_path("tei-p5-xsd")))).assertValid(xml)
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    for key in bound_fields:
        if key == "work_id" or key in accountability:
            if accountability.get(key) != profile[key]:
                raise ValueError(f"source accounting changed: {key}")
    if accountability.get("contract") != "ocd-openmgh-bsb829-flat-slices-accounting-v1":
        raise ValueError("source accounting contract changed")
    if any(accountability.get(key) != profile[key] for key in (
            "selection_plan_sha256", "review_plan_sha256", "projection_probe_sha256")):
        raise ValueError("source accounting plan/probe pins changed")
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    if (provenance.get("status") != "nonaccepted"
            or provenance.get("work_id") != profile["work_id"]
            or provenance.get("canonical_ir_written") is not False
            or not candidate.member_bytes("unresolved.jsonl").strip()
            or b"Monumenta" not in candidate.member_bytes("README.source.md")):
        raise ValueError("candidate provenance changed")
    closure = [{"path": path, "sha256": _sha((source_manifest.repository_root / path).read_bytes())}
               for path in policy["closure_inputs"]]
    outcome = {"status": "pass", "oracle_id": ORACLE_ID, "oracle_version": ORACLE_VERSION,
               "implementation_sha256": _sha(Path(__file__).read_bytes()),
               "import_closure_sha256": _sha(_json(closure)),
               "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
               "source_manifest_sha256": source_manifest.sha256,
               "candidate_sha256": candidate.sha256,
               "profile_sha256": _sha(profile_path.read_bytes()),
               "package_schema_sha256": _sha(source_manifest.authority_path("candidate-package-schema").read_bytes()),
               "source_sha256": _sha(source),
               "xsd_sha256": _sha(source_manifest.authority_path("tei-p5-xsd").read_bytes()),
               "policy_sha256": _sha(policy_path.read_bytes()), "findings": []}
    outcome["result_sha256"] = _sha(_json(outcome))
    return outcome


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
