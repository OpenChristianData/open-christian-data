"""Independent retained-source checker for one NPNF206 treatise candidate."""

from __future__ import annotations

from hashlib import sha256
import io
import json
from pathlib import Path
import platform
import sys

from lxml import etree

from build.tei import npnf2_lib048_oracle as aggregate_oracle
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.tei.validate import compiled_schema


ORACLE_ID = "ocd-npnf206-treatise-div2-source-oracle"
ORACLE_VERSION = "1"
TEI = "http://www.tei-c.org/ns/1.0"
SOURCE_SHA256 = aggregate_oracle.SOURCES[0][4]


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _oracle(manifest: SourceManifest, candidate: CandidatePackage) -> dict:
    manifest.verify()
    profile_path = manifest.authority_path("reconstruction-profile")
    profile = json.loads(profile_path.read_bytes())
    local_policy_path = manifest.authority_path("validation-policy")
    local_policy = json.loads(local_policy_path.read_bytes())
    aggregate_policy = json.loads(manifest.authority_path("aggregate-validation-policy").read_bytes())
    if (profile.get("contract") != "ocd-npnf206-treatise-profile-v1"
            or local_policy.get("contract") != "ocd-npnf206-treatise-policy-v1"):
        raise ValueError("NPNF206 treatise profile or policy changed")
    source = manifest.authority_path("retained-thml").read_bytes()
    if _sha(source) != SOURCE_SHA256:
        raise ValueError("NPNF206 retained source differs")
    tree = aggregate_oracle._source_tree(source)
    scope, work_id = profile["div2_id"], profile["work_id"]
    assigned = [(key, sid, wid) for key, sid, wid in aggregate_oracle.ASSIGNED
                if key == "npnf206" and sid.startswith("vi.")]
    if ("npnf206", scope, work_id) not in assigned:
        raise ValueError("NPNF206 treatise identity differs")
    matches = tree.xpath("//*[@id=$source_id]", source_id=scope)
    if len(matches) != 1 or matches[0].tag != "div2" or matches[0].getparent().get("id") != "vi":
        raise ValueError("NPNF206 source-native treatise boundary differs")
    node = matches[0]
    preceding = [("v", "jerome-letters")] + [(sid, wid) for _key, sid, wid in assigned]
    index = [sid for sid, _wid in preceding].index(scope)
    offsets = {}
    total = 0
    for sid, _wid in preceding:
        part = tree.xpath("//*[@id=$source_id]", source_id=sid)
        if len(part) != 1:
            raise ValueError("NPNF206 assigned source root changed")
        offsets[sid] = total
        total += len(list(part[0].iter()))
    if (offsets[scope] != profile["feature_offset"]
            or len(list(node.iter())) != profile["feature_count"]
            or node.get("title") != profile["source_title"]
            or _sha(etree.tostring(node, method="c14n")) != profile["source_div2_c14n_sha256"]):
        raise ValueError("NPNF206 source subtree or feature offset differs")
    entries = aggregate_policy["projection"]["reference_classification"]["neutral_non_scripture_exceptions"]
    if not isinstance(entries, list) or len(entries) != 31:
        raise ValueError("aggregate reference policy changed")
    exceptions = {}
    for entry in entries:
        if entry.get("source_member") == "npnf206" and entry.get("source_root_id") == scope:
            if set(entry) != {"source_member", "source_root_id", "source_xml_id", "passage"}:
                raise ValueError("reference exception shape differs")
            matching = node.xpath(".//scripRef[@id=$source_id]", source_id=entry["source_xml_id"])
            if (len(matching) != 1 or matching[0].get("passage") != entry["passage"]
                    or matching[0].get("osisRef") is not None
                    or set(matching[0].attrib) != {"id", "passage"}):
                raise ValueError("reference exception source differs")
            key = ("npnf206", scope, entry["source_xml_id"])
            if key in exceptions:
                raise ValueError("duplicate reference exception")
            exceptions[key] = entry["passage"]
    document = etree.parse(io.BytesIO(candidate.member_bytes("content.tei.xml")),
                           etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False, huge_tree=True))
    root = document.getroot()
    body = root.find(f"{{{TEI}}}text/{{{TEI}}}body")
    if root.tag != f"{{{TEI}}}TEI" or len(root) != 2 or body is None or len(body) != 1:
        raise ValueError("one treatise requires one TEI document and body division")
    number = [profile["feature_offset"]]
    aggregate_oracle._verify_node(node, body[0], "npnf206", aggregate_policy,
                                  number, work_id, scope, exceptions)
    if number[0] != profile["feature_offset"] + profile["feature_count"]:
        raise ValueError("NPNF206 treatise feature census differs")
    current_div = _sha(etree.tostring(body[0], method="c14n"))
    if current_div != profile["aggregate_tei_div_c14n_sha256"]:
        raise ValueError("treatise TEI differs from validated aggregate subtree")
    aggregate_root = Path(profile["aggregate_candidate_root"])
    prior = CandidatePackage.load(aggregate_root / "package")
    validation_bytes = (aggregate_root / "validation.json").read_bytes()
    prior_validation = json.loads(validation_bytes)
    if (prior.sha256 != profile["aggregate_candidate_sha256"]
            or _sha(validation_bytes) != profile["aggregate_validation_sha256"]
            or prior_validation.get("status") != "pass"
            or prior_validation.get("candidate_sha256") != prior.sha256):
        raise ValueError("aggregate proof artifact changed")
    aggregate_doc = etree.parse(io.BytesIO(prior.member_bytes("content.tei.xml")),
                                etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    aggregate_body = aggregate_doc.getroot().find(f"{{{TEI}}}text/{{{TEI}}}body")
    if aggregate_body is None or len(aggregate_body) != 15 or _sha(etree.tostring(aggregate_body[index], method="c14n")) != current_div:
        raise ValueError("NPNF206 treatise output differs from aggregate work subtree")
    compiled_schema().assertValid(document)
    accounting = json.loads(candidate.member_bytes("source-accountability.json"))
    expected = {"work_id": work_id, "div2_id": scope,
                "source_div2_c14n_sha256": profile["source_div2_c14n_sha256"],
                "tei_div_c14n_sha256": current_div, "feature_offset": profile["feature_offset"],
                "feature_count": profile["feature_count"]}
    if any(accounting.get(key) != value for key, value in expected.items()):
        raise ValueError("NPNF206 source accounting differs")
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    if (provenance.get("work_id") != work_id or provenance.get("status") != "nonaccepted"
            or provenance.get("canonical_ir_written") is not False):
        raise ValueError("NPNF206 candidate provenance differs")
    if b"CCEL.org" not in candidate.member_bytes("README.source.md") or not candidate.member_bytes("unresolved.jsonl").strip():
        raise ValueError("NPNF206 attribution or unresolved handoff absent")
    closure = _sha(_json([{"path": rel, "sha256": _sha((manifest.repository_root / rel).read_bytes())}
                         for rel in local_policy["closure_inputs"]]))
    result = {
        "status": "pass", "oracle_id": ORACLE_ID, "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": closure,
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": manifest.sha256, "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(profile_path.read_bytes()),
        "package_schema_sha256": _sha(manifest.authority_path("candidate-package-schema").read_bytes()),
        "source_sha256": _sha(source),
        "xsd_sha256": _sha(manifest.authority_path("tei-p5-xsd").read_bytes()),
        "policy_sha256": _sha(local_policy_path.read_bytes()), "findings": [],
    }
    result["result_sha256"] = _sha(_json(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
