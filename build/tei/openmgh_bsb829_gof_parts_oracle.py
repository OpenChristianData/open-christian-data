"""Independent source-tree oracle for eight Goffridus division-21 parts.

The producer is deliberately not imported here. Selection is recovered from
the declared locator pair and checked against the complete source container.
"""

from __future__ import annotations

from collections import Counter
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
ORACLE_ID = "ocd-openmgh-bsb829-gof-parts-source-oracle"
ORACLE_VERSION = "1"


def _sha(value: bytes) -> str:
    return sha256(value).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _equivalent(source: etree._Element, result: etree._Element, *, outer: bool = False) -> bool:
    if (source.tag != result.tag or dict(source.attrib) != dict(result.attrib)
            or source.text != result.text or len(source) != len(result)):
        return False
    if not outer and source.tail != result.tail:
        return False
    return all(_equivalent(a, b) for a, b in zip(source, result, strict=True))


def check(source_bytes: bytes, candidate_bytes: bytes, *, first_id: str,
          last_id: str, selected_type: str, part_ordinal: int,
          section_ordinal: int | None) -> dict[str, object]:
    parser = etree.XMLParser(resolve_entities=False, no_network=True,
                             remove_comments=False, huge_tree=True)
    source = etree.fromstring(source_bytes, parser)
    candidate = etree.fromstring(candidate_bytes, parser)
    if source.getroottree().docinfo.doctype or candidate.getroottree().docinfo.doctype:
        raise ValueError("DOCTYPE is forbidden")
    body = source.find(f"{TEI}text/{TEI}body")
    if body is None or len(body) != 1 or body[0].get("type") != "volume":
        raise ValueError("source volume envelope changed")
    works = list(body[0])
    if len(works) != 21 or works[0].get("type") != "work":
        raise ValueError("source work division envelope changed")
    parts = list(works[20])
    if len(parts) != 8 or not 1 <= part_ordinal <= 8:
        raise ValueError("source division-21 part envelope changed")
    part = parts[part_ordinal - 1]
    if part.get("type") != "part":
        raise ValueError("source part type changed")
    if selected_type != "part" or section_ordinal is not None:
        raise ValueError("Goffridus scope must be a complete native part")
    selected = part
    all_ids = [node.get(XML_ID) for node in selected.iter() if node.get(XML_ID)]
    source_ids = [value for value in all_ids if value.startswith("bsb00000829_")]
    if (first_id not in source_ids or not source_ids
            or source_ids[-1] != last_id or source_ids.index(first_id) > 2):
        raise ValueError("declared locator pair does not bound the complete container")
    occurrences = Counter(node.get(XML_ID) for node in source.iter() if node.get(XML_ID))
    if occurrences[first_id] != 1 or occurrences[last_id] != 1:
        raise ValueError("source locator is not unique")
    candidate_body = candidate.find(f"{TEI}text/{TEI}body")
    if (candidate.tag != f"{TEI}TEI" or candidate_body is None
            or len(candidate_body) != 1 or candidate_body[0].get("type") != "work"
            or len(candidate_body[0]) != 1):
        raise ValueError("candidate is not a single independent work")
    actual = candidate_body[0][0]
    if not _equivalent(selected, actual, outer=True):
        raise ValueError("source and candidate trees differ")
    local = set(all_ids)
    external = [node.get("target") for node in selected.iter() if node.get("target")
                and (not node.get("target").startswith("#")
                     or node.get("target")[1:] not in local)]
    if external:
        raise ValueError(f"external source fragment targets: {external[:3]}")
    return {
        "status": "pass", "source_sha256": sha256(source_bytes).hexdigest(),
        "selection_c14n_sha256": sha256(etree.tostring(selected, method="c14n", with_comments=True)).hexdigest(),
        "element_count": sum(1 for node in selected.iter() if isinstance(node.tag, str)),
        "xml_id_count": len(all_ids), "external_fragment_target_count": 0,
    }


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> dict[str, object]:
    """Validate a bound package without importing the candidate producer."""
    source_manifest.verify()
    candidate.verify_integrity()
    profile_path = source_manifest.authority_path("reconstruction-profile")
    policy_path = source_manifest.authority_path("validation-policy")
    profile = json.loads(profile_path.read_bytes())
    policy = json.loads(policy_path.read_bytes())
    if (profile.get("contract") != "ocd-openmgh-bsb829-gof-parts-profile-v1"
            or policy.get("contract") != "ocd-openmgh-bsb829-gof-parts-policy-v1"):
        raise ValueError("parts profile or policy contract changed")
    source = source_manifest.authority_path("extracted-xml").read_bytes()
    work = json.loads(source_manifest.authority_path("work-sidecar").read_bytes())
    boundary = json.loads(source_manifest.authority_path("boundary-review").read_bytes())
    acquisition_path = source_manifest.repository_root / str(profile["acquisition_path"])
    acquisition_bytes = Path(_io_path(acquisition_path)).read_bytes()
    if _sha(acquisition_bytes) != profile["acquisition_sha256"]:
        raise ValueError("acquisition sidecar hash changed")
    acquisition = json.loads(acquisition_bytes)
    if (work.get("work_id") != profile["work_id"]
            or work.get("title") != profile["work_title"]
            or acquisition.get("acquisition_id") != profile["acquisition_id"]
            or acquisition.get("edition_id") != profile["edition_id"]
            or acquisition.get("source_path") != profile["source_path"]
            or acquisition.get("source_sha256") != _sha(source)):
        raise ValueError("source, work, edition, or acquisition binding changed")
    if not any(item.get("path") == profile["source_path"] and item.get("sha256") == _sha(source)
               for item in acquisition.get("retained_files", [])):
        raise ValueError("extracted XML is absent from retained acquisition")
    if any(item.get("path", "").endswith(".zip") and "archive" not in item.get("scope", "").lower()
           for item in acquisition.get("retained_files", [])):
        raise ValueError("ZIP package role changed")
    bound_fields = ("work_id", "source_path", "source_sha256", "source_part_ordinal",
                    "source_section_ordinal_zero_based", "native_type", "start_xml_id",
                    "end_xml_id", "selection_c14n_sha256", "shared_matter_disposition",
                    "unassigned_fragment_disposition", "declared_locator_ids",
                    "declared_locator_order_disposition")
    if any(boundary.get(key) != profile.get(key) for key in bound_fields):
        raise ValueError("inspected source boundary differs from profile")
    editions = [edition for form in work["textual_forms"] for edition in form["editions"]]
    if len(editions) != 1 or [value.split("#", 1)[1] for value in
            editions[0]["containing_source"]["locator"].split("; ")] != profile["declared_locator_ids"]:
        raise ValueError("declared source locator sequence changed")
    result = check(
        source, candidate.member_bytes("content.tei.xml"),
        first_id=profile["start_xml_id"], last_id=profile["end_xml_id"],
        selected_type=profile["native_type"], part_ordinal=profile["source_part_ordinal"],
        section_ordinal=profile["source_section_ordinal_zero_based"],
    )
    if result["selection_c14n_sha256"] != boundary["selection_c14n_sha256"]:
        raise ValueError("selected source subtree differs from inspected boundary")
    xml = etree.fromstring(candidate.member_bytes("content.tei.xml"),
                           etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    source_xml = etree.fromstring(source,
                                  etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    if xml.get(XML_ID) != f"ocd-{profile['work_id']}-bsb829-gof-parts-electronic-v1":
        raise ValueError("candidate TEI work identity changed")
    title = xml.find(f"{TEI}teiHeader/{TEI}fileDesc/{TEI}titleStmt/{TEI}title")
    if title is None or title.text != profile["work_title"]:
        raise ValueError("candidate title changed")
    for suffix in (f"{TEI}publicationStmt", f"{TEI}sourceDesc/{TEI}biblFull"):
        old = source_xml.find(f"{TEI}teiHeader/{TEI}fileDesc/{suffix}")
        new = xml.find(f"{TEI}teiHeader/{TEI}fileDesc/{suffix}")
        if old is None or new is None or not _equivalent(old, new, outer=True):
            raise ValueError("electronic license or print bibliography changed")
    etree.XMLSchema(etree.parse(str(source_manifest.authority_path("tei-p5-xsd")))).assertValid(xml)
    accounting = json.loads(candidate.member_bytes("source-accountability.json"))
    expected = {
        "work_id": profile["work_id"], "edition_id": profile["edition_id"],
        "acquisition_id": profile["acquisition_id"],
        "source_path": profile["source_path"], "source_sha256": _sha(source),
        "source_division_ordinal": 21, "source_part_ordinal": profile["source_part_ordinal"],
        "source_section_ordinal_zero_based": profile["source_section_ordinal_zero_based"],
        "native_type": profile["native_type"],
        "start_xml_id": profile["start_xml_id"], "end_xml_id": profile["end_xml_id"],
        "declared_locator_ids": profile["declared_locator_ids"],
        "declared_locator_order_disposition": profile["declared_locator_order_disposition"],
        "selection_c14n_sha256": result["selection_c14n_sha256"],
        "shared_matter_disposition": boundary["shared_matter_disposition"],
        "unassigned_fragment_disposition": boundary["unassigned_fragment_disposition"],
    }
    if any(accounting.get(key) != value for key, value in expected.items()):
        raise ValueError("candidate source accounting changed")
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    if (provenance.get("status") != "nonaccepted"
            or provenance.get("work_id") != profile["work_id"]
            or provenance.get("canonical_ir_written") is not False
            or not candidate.member_bytes("unresolved.jsonl").strip()
            or b"Monumenta" not in candidate.member_bytes("README.source.md")):
        raise ValueError("candidate provenance or unresolved handoff changed")
    closure = [_json({"path": relative, "sha256": _sha((source_manifest.repository_root / relative).read_bytes())})
               for relative in policy["closure_inputs"]]
    closure_digest = _sha(_json([json.loads(item) for item in closure]))
    outcome = {
        "status": "pass", "oracle_id": ORACLE_ID, "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": closure_digest,
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(profile_path.read_bytes()),
        "package_schema_sha256": _sha(source_manifest.authority_path("candidate-package-schema").read_bytes()),
        "source_sha256": _sha(source),
        "xsd_sha256": _sha(source_manifest.authority_path("tei-p5-xsd").read_bytes()),
        "policy_sha256": _sha(policy_path.read_bytes()),
        "findings": [],
    }
    outcome["result_sha256"] = _sha(_json(outcome))
    return outcome


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
