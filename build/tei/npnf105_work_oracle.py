"""Check one NPNF105 TEI work against its complete retained XML subtree."""

from __future__ import annotations

from hashlib import sha256
import io
import json
from pathlib import Path
import platform
import sys

from lxml import etree

from build.tei import npnf105_oracle as source_rules
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.tei.validate import compiled_schema


ORACLE_ID = "ocd-npnf105-work-div1-source-oracle"
ORACLE_VERSION = "1"
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
SOURCE_SHA = "224f0e6a188ddfe691c1433c8db9a883755a9f030b71fede644d4af6c18ee63f"


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _compare(source: etree._Element, target: etree._Element,
             ordinals: dict[int, int]) -> None:
    ordinal = ordinals[id(source)]
    expected_tag = source_rules.TAG_MAP[source.tag]
    if target.tag != TEI + expected_tag:
        raise ValueError(f"TEI tag differs at feature {ordinal}")
    if dict(target.attrib) != source_rules._expected_attrs(source, ordinal):
        raise ValueError(f"TEI attributes differ at feature {ordinal}")
    if (target.text or "") != (source.text or "") or (target.tail or "") != (source.tail or ""):
        raise ValueError(f"TEI direct or tail text differs at feature {ordinal}")
    expected_children: list[tuple[str, etree._Element | str]] = []
    title = source.get("title") if source.tag.startswith("div") else None
    if title is not None:
        expected_children.append(("head", title))
    for child in source:
        expected_children.append(("element" if isinstance(child.tag, str) else "comment", child))
    if len(target) != len(expected_children):
        raise ValueError(f"TEI child count differs at feature {ordinal}")
    for actual, (kind, expected) in zip(target, expected_children, strict=True):
        if kind == "head":
            if (actual.tag != TEI + "head" or actual.text != expected or actual.tail is not None
                    or actual.attrib or len(actual)):
                raise ValueError(f"division heading differs at feature {ordinal}")
        elif kind == "comment":
            assert isinstance(expected, etree._Element)
            if (not isinstance(actual, etree._Comment) or actual.text != expected.text
                    or (actual.tail or "") != (expected.tail or "")):
                raise ValueError(f"source comment differs at feature {ordinal}")
        else:
            assert isinstance(expected, etree._Element)
            _compare(expected, actual, ordinals)


def _oracle(manifest: SourceManifest, candidate: CandidatePackage) -> dict:
    manifest.verify()
    candidate.verify_integrity()
    profile_path = manifest.authority_path("reconstruction-profile")
    policy_path = manifest.authority_path("validation-policy")
    profile = json.loads(profile_path.read_bytes())
    policy = json.loads(policy_path.read_bytes())
    if (profile.get("contract") != "ocd-npnf105-work-profile-v1"
            or policy.get("contract") != "ocd-npnf105-work-policy-v1"):
        raise ValueError("NPNF105 work profile or policy changed")
    source_bytes = manifest.authority_path("retained-thml").read_bytes()
    if _sha(source_bytes) != SOURCE_SHA:
        raise ValueError("NPNF105 source digest differs")
    parser = etree.XMLParser(resolve_entities=False, no_network=True,
                             remove_comments=False, huge_tree=True)
    source_tree = etree.parse(io.BytesIO(source_bytes), parser)
    body = source_tree.getroot().find("ThML.body")
    if body is None:
        raise ValueError("retained source body absent")
    divisions = [child for child in body if isinstance(child.tag, str) and child.tag == "div1"]
    if tuple(child.get("id") for child in divisions) != source_rules.ALL_DIV1:
        raise ValueError("retained source division order differs")
    scope = profile["div1_id"]
    matches = [child for child in divisions if child.get("id") == scope]
    if len(matches) != 1 or dict(source_rules.ASSIGNED).get(scope) != profile["work_id"]:
        raise ValueError("source division is not one selected work")
    selected = matches[0]
    features = [node for node in selected.iter() if isinstance(node.tag, str)]
    offset = sum(len([node for node in prior.iter() if isinstance(node.tag, str)])
                 for prior in divisions[9:divisions.index(selected)])
    if (offset != profile["feature_offset"] or len(features) != profile["feature_count"]
            or selected.get("title") != profile["source_title"]
            or _sha(etree.tostring(selected, method="c14n")) != profile["source_div1_c14n_sha256"]):
        raise ValueError("selected source work boundary differs")
    document = etree.parse(io.BytesIO(candidate.member_bytes("content.tei.xml")), parser)
    root = document.getroot()
    output = root.find(TEI + "text/" + TEI + "body")
    if (root.tag != TEI + "TEI" or output is None or len(output) != 1
            or output[0].tag != TEI + "div"):
        raise ValueError("candidate does not contain one complete work")
    ordinals = {id(node): offset + number for number, node in enumerate(features, start=1)}
    _compare(selected, output[0], ordinals)
    compiled_schema().assertValid(document)
    title = root.find(TEI + "teiHeader/" + TEI + "fileDesc/" + TEI + "titleStmt/" + TEI + "title")
    if root.get(XML_ID) != f"npnf105-{profile['work_id']}-electronic" or title is None or title.text != profile["source_title"]:
        raise ValueError("work header identity or title differs")
    header = root.find(TEI + "teiHeader")
    header_text = " ".join(header.itertext())
    source_ptr = header.find(TEI + "fileDesc/" + TEI + "sourceDesc/" + TEI + "bibl/" + TEI + "ptr")
    if (source_ptr is None or source_ptr.get("target") != "https://www.ccel.org/ccel/schaff/npnf105.xml"
            or SOURCE_SHA not in header_text or profile["translator"] not in header_text):
        raise ValueError("source or translator credit absent from header")
    credit = source_tree.xpath("//*[@id=$value]", value=profile["translator_evidence_id"])
    if len(credit) != 1 or profile["translator_evidence_id"] not in policy["credit_evidence_ids"]:
        raise ValueError("translator allocation locus absent")
    credit_text = "".join(credit[0].itertext())
    if profile["translator_evidence_id"].startswith("iii-"):
        note = source_tree.xpath("//*[@id='iii-p74']")
        if (len(note) != 1 or "others by Dr. Holmes" not in "".join(note[0].itertext())
                or "*" in credit_text or profile["translator"] != "Peter Holmes"):
            raise ValueError("contents-note translator allocation differs")
    elif ("only the first was from the pen of Dr. Holmes" not in credit_text
          or "rest being the work of Dr. Robert Ernest Wallis" not in credit_text):
        raise ValueError("preface translator allocation differs")
    expected_translator = "Peter Holmes" if scope == "xix" else "Robert Ernest Wallis"
    if profile["translator_evidence_id"] == "ix-p14" and profile["translator"] != expected_translator:
        raise ValueError("translator allocation differs")
    accounting = json.loads(candidate.member_bytes("source-accountability.json"))
    expected = {"work_id": profile["work_id"], "div1_id": scope,
                "source_div1_c14n_sha256": profile["source_div1_c14n_sha256"],
                "feature_offset": offset, "feature_count": len(features),
                "tei_div_c14n_sha256": _sha(etree.tostring(output[0], method="c14n"))}
    if any(accounting.get(key) != value for key, value in expected.items()):
        raise ValueError("candidate source accounting differs")
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    if (provenance.get("work_id") != profile["work_id"] or provenance.get("status") != "nonaccepted"
            or provenance.get("canonical_ir_written") is not False):
        raise ValueError("candidate provenance differs")
    if b"CCEL.org" not in candidate.member_bytes("README.source.md") or not candidate.member_bytes("unresolved.jsonl").strip():
        raise ValueError("candidate attribution or unresolved record absent")
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
        "source_sha256": SOURCE_SHA,
        "xsd_sha256": _sha(manifest.authority_path("tei-p5-xsd").read_bytes()),
        "policy_sha256": _sha(policy_path.read_bytes()), "findings": [],
    }
    result["result_sha256"] = _sha(_json(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
