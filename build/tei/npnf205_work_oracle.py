"""Source-first work-root oracle for retained Gregory NPNF2-05 ThML."""

from __future__ import annotations

from hashlib import sha256
import io
import json
from pathlib import Path
import platform
import sys

from lxml import etree

from build.tei import npnf2_lib047_oracle as independent_nodes
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.tei.install_accepted import _io_path
from ocd_kernel.tei.validate import compiled_schema


ORACLE_ID = "ocd-npnf205-work-root-source-oracle"
ORACLE_VERSION = "1"
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
SOURCE_SHA = "43e87ed232457fd2d5862f72dd2d5d84fe1e8b69f4c3eec839bad04579327bf3"
SOURCE_URL = "https://www.ccel.org/ccel/schaff/npnf205.xml"


def _sha(value: bytes) -> str:
    return sha256(value).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def check(source_bytes: bytes, candidate_bytes: bytes, *, source_root_id: str,
          source_parent_id: str, source_tag: str, work_id: str,
          legacy_policy: dict, exceptions: list[dict]) -> dict:
    parser = etree.XMLParser(resolve_entities=False, no_network=True,
                             remove_comments=False, remove_pis=False, huge_tree=True)
    source = etree.fromstring(source_bytes, parser)
    candidate = etree.parse(io.BytesIO(candidate_bytes), parser)
    if source.getroottree().docinfo.doctype or candidate.docinfo.doctype:
        raise ValueError("source or candidate DOCTYPE is forbidden")
    if _sha(source_bytes) != SOURCE_SHA:
        raise ValueError("retained XML hash differs")
    body = source.find("ThML.body")
    if body is None or len(body) != 16:
        raise ValueError("retained volume envelope changed")
    matches = source.xpath("//*[@id=$scope]", scope=source_root_id)
    if len(matches) != 1:
        raise ValueError("source root absent or repeated")
    selected = matches[0]
    parent = selected.getparent()
    if (selected.tag != source_tag or parent is None
            or parent.get("id") != source_parent_id):
        raise ValueError("source work root parent or element changed")
    if source_parent_id == "xiii":
        raise ValueError("nested letters are not the selected collection root")
    if source_root_id == "xiii":
        if selected.getparent() is not body or selected.tag != "div1":
            raise ValueError("letters collection is not a complete direct volume division")
    elif (selected.tag != "div2" or parent.getparent() is not body
          or parent.tag != "div1"):
        raise ValueError("selected work is not a complete direct div2 root")
    root = candidate.getroot()
    text = root.find(f"{TEI}text")
    output = text.find(f"{TEI}body") if text is not None else None
    if (root.tag != f"{TEI}TEI" or text is None or output is None
            or len(output) != 1 or output[0].tag != f"{TEI}div"):
        raise ValueError("one work requires exactly one complete TEI div root")
    neutral = {}
    for item in exceptions:
        key = (item["source_member"], item["source_root_id"], item["source_xml_id"])
        if key in neutral or key[0] != "npnf205" or key[1] != source_root_id:
            raise ValueError("neutral reference exception binding changed")
        hits = selected.xpath(".//scripRef[@id=$i]", i=key[2])
        if (len(hits) != 1 or hits[0].get("passage") != item["passage"]
                or hits[0].get("osisRef") is not None):
            raise ValueError("neutral reference source evidence changed")
        neutral[key] = item["passage"]
    count = [0]
    independent_nodes._verify_node(
        selected, output[0], "npnf205", legacy_policy, count,
        work_id=work_id, source_root_id=source_root_id, reference_exceptions=neutral,
    )
    compiled_schema().assertValid(candidate)
    title = root.find(f"{TEI}teiHeader/{TEI}fileDesc/{TEI}titleStmt/{TEI}title")
    url_text = root.find(f"{TEI}teiHeader/{TEI}fileDesc/{TEI}sourceDesc/{TEI}bibl/{TEI}idno[@type='source-url']")
    digest = root.find(f"{TEI}teiHeader/{TEI}fileDesc/{TEI}sourceDesc/{TEI}bibl/{TEI}idno[@type='sha256']")
    if (root.get(XML_ID) != f"npnf205-{work_id}-electronic"
            or title is None or title.text != selected.get("title")
            or url_text is None or url_text.text != SOURCE_URL
            or digest is None or digest.text != SOURCE_SHA):
        raise ValueError("work header source identity or title differs")
    return {"source_root_c14n_sha256": _sha(etree.tostring(selected, method="c14n")),
            "tei_work_c14n_sha256": _sha(etree.tostring(output[0], method="c14n")),
            "element_count": count[0],
            "source_xml_id_count": sum(bool(node.get("id")) for node in selected.iter()),
            "source_title": selected.get("title")}


def _oracle(manifest: SourceManifest, candidate: CandidatePackage) -> dict:
    manifest.verify()
    candidate.verify_integrity()
    profile_path = manifest.authority_path("reconstruction-profile")
    policy_path = manifest.authority_path("validation-policy")
    profile = json.loads(Path(_io_path(profile_path)).read_bytes())
    policy = json.loads(Path(_io_path(policy_path)).read_bytes())
    if (profile.get("contract") != "ocd-npnf205-work-profile-v1"
            or policy.get("contract") != "ocd-npnf205-work-policy-v1"):
        raise ValueError("NPNF2-05 work profile or policy changed")
    plan_bytes = Path(_io_path(manifest.authority_path("selection-plan"))).read_bytes()
    plan = json.loads(plan_bytes)
    matches = [row for row in plan.get("works", []) if row.get("work_id") == profile["work_id"]]
    fields = ("work_id", "source_root_id", "source_parent_id", "source_tag",
              "source_title", "source_root_c14n_sha256", "element_count", "source_xml_id_count")
    if (plan.get("contract") != "ocd-npnf205-fourteen-selection-plan-v1"
            or plan.get("source_sha256") != SOURCE_SHA
            or len(plan.get("works", [])) != 14 or len(matches) != 1
            or profile.get("selection_plan_sha256") != _sha(plan_bytes)
            or policy.get("selection_plan_sha256") != _sha(plan_bytes)
            or any(matches[0][name] != profile[name] for name in fields)):
        raise ValueError("fourteen-work source selection plan changed")
    source = Path(_io_path(manifest.authority_path("retained-thml"))).read_bytes()
    legacy_policy = json.loads(Path(_io_path(manifest.authority_path("legacy-projection-policy"))).read_bytes())
    candidate_bytes = candidate.member_bytes("content.tei.xml")
    result = check(source, candidate_bytes, source_root_id=profile["source_root_id"],
                   source_parent_id=profile["source_parent_id"], source_tag=profile["source_tag"],
                   work_id=profile["work_id"], legacy_policy=legacy_policy,
                   exceptions=policy["neutral_reference_exceptions"]
                   if profile["source_root_id"] == "xiii" else [])
    result_fields = ("source_root_c14n_sha256", "element_count", "source_xml_id_count", "source_title")
    if any(result[name] != profile[name] for name in result_fields):
        raise ValueError("work source profile differs from independent source check")
    work = Path("library/works") / profile["work_id"] / "work.json"
    acquisition = Path(profile["acquisition_path"])
    work_bytes = Path(_io_path(manifest.repository_root / work)).read_bytes()
    acquisition_bytes = Path(_io_path(manifest.repository_root / acquisition)).read_bytes()
    work_record = json.loads(work_bytes)
    edition_matches = [edition for form in work_record["textual_forms"]
                       for edition in form["editions"]
                       if edition["edition_id"] == profile["edition_id"]]
    acquisition_record = json.loads(acquisition_bytes)
    if (_sha(work_bytes) != profile["work_sha256"]
            or _sha(acquisition_bytes) != profile["acquisition_sha256"]
            or len(edition_matches) != 1
            or edition_matches[0]["containing_source"]["locator"]
            != f"{profile['source_path']}#{profile['source_root_id']}"
            or profile["acquisition_id"] not in edition_matches[0]["acquisition_ids"]
            or acquisition_record.get("source_path") != profile["source_path"]
            or acquisition_record.get("source_sha256") != SOURCE_SHA
            or acquisition_record.get("url") != SOURCE_URL):
        raise ValueError("work or acquisition authority changed")
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    if (accountability.get("contract") != "ocd-npnf205-work-accounting-v1"
            or accountability.get("work_id") != profile["work_id"]
            or any(accountability.get(name) != result[name] for name in (*result_fields, "tei_work_c14n_sha256"))
            or accountability.get("source_root_id") != profile["source_root_id"]
            or accountability.get("source_parent_id") != profile["source_parent_id"]
            or accountability.get("scope_note") != profile["scope_note"]
            or accountability.get("shared_matter_disposition") != profile["shared_matter_disposition"]):
        raise ValueError("candidate source accountability differs")
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    if (provenance.get("status") != "nonaccepted"
            or provenance.get("work_id") != profile["work_id"]
            or provenance.get("edition_id") != profile["edition_id"]
            or provenance.get("acquisition_id") != profile["acquisition_id"]
            or provenance.get("canonical_ir_written") is not False):
        raise ValueError("candidate provenance differs")
    if (b"William Moore" not in candidate.member_bytes("README.source.md")
            or b"Henry Austin Wilson" not in candidate.member_bytes("README.source.md")
            or not candidate.member_bytes("unresolved.jsonl").strip()):
        raise ValueError("source attribution or unresolved handoff absent")
    closure = _sha(_json([{"path": path, "sha256": _sha(Path(_io_path(manifest.repository_root / path)).read_bytes())}
                          for path in policy["closure_inputs"]]))
    attestation = {
        "status": "pass", "oracle_id": ORACLE_ID, "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": closure,
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": manifest.sha256, "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(Path(_io_path(profile_path)).read_bytes()),
        "package_schema_sha256": _sha(Path(_io_path(manifest.authority_path("candidate-package-schema"))).read_bytes()),
        "source_sha256": _sha(source),
        "xsd_sha256": _sha(Path(_io_path(manifest.authority_path("tei-p5-xsd"))).read_bytes()),
        "policy_sha256": _sha(Path(_io_path(policy_path)).read_bytes()), "findings": [],
    }
    attestation["result_sha256"] = _sha(_json(attestation))
    return attestation


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
