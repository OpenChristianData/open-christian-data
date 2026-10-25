"""Source-first independent checker for each NPNF104 work-local candidate."""

from __future__ import annotations

from hashlib import sha256
import io
import json
from pathlib import Path
import platform
import sys

from lxml import etree

from build.tei import npnf104_lib038_oracle as aggregate_oracle
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.tei.validate import compiled_schema


ORACLE_ID = "ocd-npnf104-work-div2-source-oracle"
ORACLE_VERSION = "1"
TEI = "http://www.tei-c.org/ns/1.0"


def _sha(value: bytes) -> str:
    return sha256(value).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _check_node(source: etree._Element, actual: etree._Element, number: list[int], *, work_id: str | None = None) -> None:
    ordinal = number[0] + 1
    number[0] = ordinal
    attrs, _ = aggregate_oracle._expected_attrs(source, ordinal, work_id)
    if actual.tag != aggregate_oracle.Q(aggregate_oracle._expected_tag(source)):
        raise ValueError("TEI source feature tag drift")
    if aggregate_oracle._normalized_attrs(actual) != attrs:
        raise ValueError("TEI source attribute drift")
    if (actual.text or "") != (source.text or ""):
        raise ValueError("TEI source direct text drift")
    expected_tail = "" if work_id else (source.tail or "")
    if (actual.tail or "") != expected_tail:
        raise ValueError("TEI source tail text drift")
    source_children = [child for child in source if isinstance(child.tag, str)]
    actual_children = [child for child in actual if isinstance(child.tag, str)]
    title = source.get("title") if source.tag.startswith("div") else None
    if title is not None:
        if (not actual_children or actual_children[0].tag != aggregate_oracle.Q("head")
                or actual_children[0].text != title or actual_children[0].attrib
                or len(actual_children[0])):
            raise ValueError("TEI source title projection drift")
        actual_children = actual_children[1:]
    if len(actual_children) != len(source_children):
        raise ValueError("TEI source feature omission or invention")
    for child, target in zip(source_children, actual_children, strict=True):
        _check_node(child, target, number)


def _oracle(manifest: SourceManifest, candidate: CandidatePackage) -> dict:
    manifest.verify()
    profile_path = manifest.authority_path("reconstruction-profile")
    profile = json.loads(profile_path.read_bytes())
    policy_path = manifest.authority_path("validation-policy")
    policy = json.loads(policy_path.read_bytes())
    if profile.get("contract") != "ocd-npnf104-work-profile-v1" or policy.get("contract") != "ocd-npnf104-work-policy-v1":
        raise ValueError("NPNF104 work profile or policy changed")
    source = manifest.authority_path("retained-thml").read_bytes()
    if _sha(source) != aggregate_oracle.SOURCE_SHA256:
        raise ValueError("NPNF104 retained source differs")
    tree = etree.parse(io.BytesIO(source), etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False, huge_tree=True))
    selected = aggregate_oracle._source_roots(tree)
    assigned = dict(aggregate_oracle.ASSIGNED)
    scope, work_id = profile["div2_id"], profile["work_id"]
    if assigned.get(scope) != work_id:
        raise ValueError("NPNF104 work boundary differs")
    index = [key for key, _ in aggregate_oracle.ASSIGNED].index(scope)
    node = selected[index]
    offset = sum(len(list(prior.iter())) for prior in selected[:index])
    if (offset != profile["feature_offset"]
            or len(list(node.iter())) != profile["feature_count"]
            or node.get("title") != profile["source_title"]
            or _sha(etree.tostring(node, method="c14n")) != profile["source_div2_c14n_sha256"]):
        raise ValueError("NPNF104 selected source div2 changed")
    document = etree.parse(io.BytesIO(candidate.member_bytes("content.tei.xml")),
                           etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    root = document.getroot()
    if root.tag != f"{{{TEI}}}TEI" or len(root) != 2:
        raise ValueError("one work requires one TEI document")
    body = root.find(f"{{{TEI}}}text/{{{TEI}}}body")
    if body is None or len(body) != 1 or body[0].tag != f"{{{TEI}}}div":
        raise ValueError("one work requires one div2-derived TEI body")
    number = [offset]
    _check_node(node, body[0], number, work_id=work_id)
    if number[0] != offset + profile["feature_count"]:
        raise ValueError("NPNF104 work feature census differs")
    current_div = _sha(etree.tostring(body[0], method="c14n"))
    if current_div != profile["aggregate_tei_div_c14n_sha256"]:
        raise ValueError("work div differs from independently validated aggregate")
    aggregate_root = Path(profile["aggregate_candidate_root"])
    prior = CandidatePackage.load(aggregate_root / "package")
    prior_validation = json.loads((aggregate_root / "validation.json").read_bytes())
    if (prior.sha256 != profile["aggregate_candidate_sha256"]
            or _sha((aggregate_root / "validation.json").read_bytes())
               != profile["aggregate_validation_sha256"]
            or prior_validation.get("status") != "pass"
            or prior_validation.get("candidate_sha256") != prior.sha256):
        raise ValueError("aggregate proof artifact changed")
    aggregate_doc = etree.parse(io.BytesIO(prior.member_bytes("content.tei.xml")),
                                etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    aggregate_body = aggregate_doc.getroot().find(f"{{{TEI}}}text/{{{TEI}}}body")
    if aggregate_body is None or len(aggregate_body) != 10 or _sha(etree.tostring(aggregate_body[index], method="c14n")) != current_div:
        raise ValueError("work output differs from aggregate work subtree")
    compiled_schema().assertValid(document)
    accounting = json.loads(candidate.member_bytes("source-accountability.json"))
    expected = {"work_id": work_id, "div2_id": scope,
                "source_div2_c14n_sha256": profile["source_div2_c14n_sha256"],
                "tei_div_c14n_sha256": current_div, "feature_offset": offset,
                "feature_count": profile["feature_count"]}
    if any(accounting.get(key) != value for key, value in expected.items()):
        raise ValueError("work source accounting differs")
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    if (provenance.get("work_id") != work_id or provenance.get("status") != "nonaccepted"
            or provenance.get("canonical_ir_written") is not False):
        raise ValueError("work candidate provenance differs")
    if b"CCEL.org" not in candidate.member_bytes("README.source.md") or not candidate.member_bytes("unresolved.jsonl").strip():
        raise ValueError("work attribution or unresolved handoff absent")
    closure = _sha(_json([{"path": rel, "sha256": _sha((manifest.repository_root / rel).read_bytes())}
                         for rel in policy["closure_inputs"]]))
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
        "policy_sha256": _sha(policy_path.read_bytes()), "findings": [],
    }
    result["result_sha256"] = _sha(_json(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
