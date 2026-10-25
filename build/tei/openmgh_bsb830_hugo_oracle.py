"""Independent exact-source oracle for two Hugo Metellus native parts in bsb830."""

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
ORACLE_ID = "ocd-openmgh-bsb830-hugo-part-source-oracle"
ORACLE_VERSION = "1"
NATIVE = {
    1: ("hugo-metellus-letter-to-garbodus",
        "bsb00000830_00722", "bsb00000830_00723_24",
        "bsb00000830_00722_1", "prose"),
    2: ("hugo-metellus-certamen-papae-et-regis",
        "bsb00000830_00723_25", "bsb00000830_00728_30",
        "bsb00000830_00723_25", "poetry"),
}


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _equal(a: etree._Element, b: etree._Element, *, outer: bool = False) -> bool:
    if (a.tag != b.tag or dict(a.attrib) != dict(b.attrib)
            or a.text != b.text or len(a) != len(b)):
        return False
    if not outer and a.tail != b.tail:
        return False
    return all(_equal(x, y) for x, y in zip(a, b, strict=True))


def check(source_bytes: bytes, candidate_bytes: bytes, *, first_id: str,
          last_id: str, part_ordinal: int) -> dict[str, object]:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False,
                             huge_tree=True)
    source = etree.fromstring(source_bytes, parser)
    candidate = etree.fromstring(candidate_bytes, parser)
    if source.getroottree().docinfo.doctype or candidate.getroottree().docinfo.doctype:
        raise ValueError("DOCTYPE is forbidden")
    source_body = source.find(f"{TEI}text/{TEI}body")
    if (source_body is None or len(source_body) != 1
            or source_body[0].get("type") != "volume" or len(source_body[0]) != 29):
        raise ValueError("bsb830 source volume changed")
    parent = source_body[0][25]
    parts = list(parent)
    if (parent.get("n") != "Hugonis Metelli opuscula"
            or len(parts) != 3 or part_ordinal not in (1, 2)
            or parts[0].tag != f"{TEI}ab"
            or " ".join("".join(parts[0].itertext()).split()) != "HUGONIS METELLI OPUSCULA."
            or any(node.tag != f"{TEI}div" or node.get("type") != "part" for node in parts[1:])):
        raise ValueError("Hugo Metellus parent or part inventory changed")
    selected = parts[part_ordinal]
    ids = [node.get(XML_ID) for node in selected.iter() if node.get(XML_ID)]
    native_ids = [item for item in ids if item.startswith("bsb00000830_")]
    if (not native_ids or native_ids[0] != first_id or native_ids[-1] != last_id):
        raise ValueError("declared locator pair does not bound the complete Hugo Metellus part")
    if (part_ordinal not in NATIVE or (first_id, last_id) != NATIVE[part_ordinal][1:3]):
        raise ValueError("Hugo Metellus work-native locator map changed")
    if selected.xpath(".//tei:gap|.//tei:unclear", namespaces={"tei": TEI[1:-1]}):
        raise ValueError("selected Hugo Metellus part has a lacuna or unclear element")
    counts = (len(selected.findall(f".//{TEI}ab")), len(selected.findall(f".//{TEI}pb")),
              len(selected.findall(f".//{TEI}lb")), len(selected.findall(f".//{TEI}lg")),
              len(selected.findall(f".//{TEI}l")))
    if counts != {1: (1, 2, 54, 0, 0), 2: (1, 5, 189, 0, 0)}[part_ordinal]:
        raise ValueError("Hugo Metellus native prose or flat-verse structure changed")
    occurrences = Counter(node.get(XML_ID) for node in source.iter() if node.get(XML_ID))
    if occurrences[first_id] != 1 or occurrences[last_id] != 1:
        raise ValueError("declared source locator is not unique")
    candidate_body = candidate.find(f"{TEI}text/{TEI}body")
    if (candidate.tag != f"{TEI}TEI" or candidate_body is None
            or len(candidate_body) != 1 or candidate_body[0].get("type") != "work"
            or len(candidate_body[0]) != 1):
        raise ValueError("candidate is not one separately addressable work")
    actual = candidate_body[0][0]
    if not _equal(selected, actual, outer=True):
        raise ValueError("complete source and candidate part trees differ")
    local = set(ids)
    external = [node.get("target") for node in selected.iter()
                if node.get("target") and (not node.get("target").startswith("#")
                                           or node.get("target")[1:] not in local)]
    if external:
        raise ValueError(f"fragment target escaped selected part: {external[:3]}")
    return {
        "status": "pass", "source_sha256": _sha(source_bytes),
        "selection_c14n_sha256": _sha(etree.tostring(selected, method="c14n", with_comments=True)),
        "element_count": sum(isinstance(node.tag, str) for node in selected.iter()),
        "xml_id_count": len(ids), "external_fragment_target_count": 0,
    }


def _oracle(manifest: SourceManifest, candidate: CandidatePackage) -> dict[str, object]:
    manifest.verify()
    candidate.verify_integrity()
    profile_path = manifest.authority_path("reconstruction-profile")
    policy_path = manifest.authority_path("validation-policy")
    profile = json.loads(profile_path.read_bytes())
    policy = json.loads(policy_path.read_bytes())
    if (profile.get("contract") != "ocd-openmgh-bsb830-hugo-profile-v1"
            or policy.get("contract") != "ocd-openmgh-bsb830-hugo-policy-v1"):
        raise ValueError("Hugo Metellus profile or policy contract changed")
    source = manifest.authority_path("extracted-xml").read_bytes()
    work = json.loads(manifest.authority_path("work-sidecar").read_bytes())
    boundary = json.loads(manifest.authority_path("boundary-review").read_bytes())
    acquisition_bytes = Path(_io_path(manifest.repository_root / profile["acquisition_path"])).read_bytes()
    acquisition = json.loads(acquisition_bytes)
    if (_sha(acquisition_bytes) != profile["acquisition_sha256"]
            or work.get("work_id") != profile["work_id"]
            or work.get("title") != profile["work_title"]
            or acquisition.get("acquisition_id") != profile["acquisition_id"]
            or acquisition.get("edition_id") != profile["edition_id"]
            or acquisition.get("source_path") != profile["source_path"]
            or acquisition.get("source_sha256") != _sha(source)):
        raise ValueError("source, work, edition, or acquisition binding changed")
    retained = acquisition.get("retained_files", [])
    if (not any(item.get("path") == profile["source_path"] and item.get("sha256") == _sha(source)
                for item in retained)
            or any(item.get("path", "").endswith(".zip")
                   and "archive" not in item.get("scope", "").lower() for item in retained)):
        raise ValueError("extracted XML or ZIP role changed")
    bound = ("work_id", "source_path", "source_sha256", "source_division_ordinal",
             "source_part_ordinal", "native_type", "start_xml_id", "end_xml_id",
             "category",
             "catalog_start_xml_id", "catalog_end_xml_id",
             "selection_c14n_sha256", "shared_matter_disposition",
             "unassigned_fragment_disposition")
    if any(boundary.get(key) != profile.get(key) for key in bound):
        raise ValueError("inspected Hugo Metellus boundary differs from profile")
    result = check(source, candidate.member_bytes("content.tei.xml"),
                   first_id=profile["start_xml_id"], last_id=profile["end_xml_id"],
                   part_ordinal=profile["source_part_ordinal"])
    native = NATIVE[profile["source_part_ordinal"]]
    if (profile["work_id"] != native[0]
            or profile["catalog_start_xml_id"] != native[3]
            or profile["catalog_end_xml_id"] != native[2]
            or profile["category"] != native[4]):
        raise ValueError("catalog locator does not identify this complete Hugo Metellus part")
    locators = work["textual_forms"][0]["editions"][0]["containing_source"]["locator"]
    if locators != (f"{profile['source_path']}#{native[3]}; "
                    f"{profile['source_path']}#{native[2]}"):
        raise ValueError("installed work catalog locator changed")
    if result["selection_c14n_sha256"] != profile["selection_c14n_sha256"]:
        raise ValueError("selected native part differs")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    xml = etree.fromstring(candidate.member_bytes("content.tei.xml"), parser)
    source_xml = etree.fromstring(source, parser)
    if xml.get(XML_ID) != f"ocd-{profile['work_id']}-bsb830-hugo-electronic-v1":
        raise ValueError("candidate TEI identity changed")
    title = xml.find(f"{TEI}teiHeader/{TEI}fileDesc/{TEI}titleStmt/{TEI}title")
    if title is None or title.text != profile["work_title"]:
        raise ValueError("candidate title changed")
    for suffix in (f"{TEI}publicationStmt", f"{TEI}sourceDesc/{TEI}biblFull"):
        original = source_xml.find(f"{TEI}teiHeader/{TEI}fileDesc/{suffix}")
        actual = xml.find(f"{TEI}teiHeader/{TEI}fileDesc/{suffix}")
        if original is None or actual is None or not _equal(original, actual, outer=True):
            raise ValueError("source electronic rights or print bibliography changed")
    etree.XMLSchema(etree.parse(str(manifest.authority_path("tei-p5-xsd")))).assertValid(xml)
    accounting = json.loads(candidate.member_bytes("source-accountability.json"))
    expected = {
        "work_id": profile["work_id"], "edition_id": profile["edition_id"],
        "acquisition_id": profile["acquisition_id"], "source_path": profile["source_path"],
        "source_sha256": _sha(source), "source_division_ordinal": 26,
        "source_part_ordinal": profile["source_part_ordinal"], "native_type": "part",
        "category": profile["category"],
        "start_xml_id": profile["start_xml_id"], "end_xml_id": profile["end_xml_id"],
        "catalog_start_xml_id": profile["catalog_start_xml_id"],
        "catalog_end_xml_id": profile["catalog_end_xml_id"],
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
    closure = [{"path": path, "sha256": _sha((manifest.repository_root / path).read_bytes())}
               for path in policy["closure_inputs"]]
    outcome = {
        "status": "pass", "oracle_id": ORACLE_ID, "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": _sha(_json(closure)),
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": manifest.sha256, "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(profile_path.read_bytes()),
        "package_schema_sha256": _sha(manifest.authority_path("candidate-package-schema").read_bytes()),
        "source_sha256": _sha(source),
        "xsd_sha256": _sha(manifest.authority_path("tei-p5-xsd").read_bytes()),
        "policy_sha256": _sha(policy_path.read_bytes()), "findings": [],
    }
    outcome["result_sha256"] = _sha(_json(outcome))
    return outcome


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
