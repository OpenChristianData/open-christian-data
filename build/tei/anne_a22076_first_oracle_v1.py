"""Independent source-walk and mutation checks for the A22076 first work."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import platform
import sys
from typing import Mapping
from xml.etree import ElementTree as ET

from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest


TEI = "{http://www.tei-c.org/ns/1.0}"
SOURCE_SHA = "211a2c0d5029ca1dc6622b419fea356a0bba0ee28a363bd8c4e28331b3b6f92a"
ORACLE_ID = "ocd-anne-a22076-first-independent-scope"
ORACLE_VERSION = "1"


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _tree_digest(node: ET.Element) -> str:
    return _sha(ET.tostring(node, encoding="utf-8"))


def _pages(node: ET.Element) -> list[tuple[tuple[str, str], ...]]:
    return [tuple(sorted(element.attrib.items())) for element in node.iter(TEI + "pb")]


def _counts(node: ET.Element) -> dict[str, int]:
    return dict(sorted(Counter(element.tag.rsplit("}", 1)[-1] for element in node.iter()).items()))


def _check(source: bytes, candidate: bytes, profile: Mapping[str, object], *, schema_path: Path | None) -> list[str]:
    findings: list[str] = []
    try:
        original = ET.fromstring(source)
        result = ET.fromstring(candidate)
    except ET.ParseError as exc:
        return [f"XML parse failed: {exc}"]
    source_header = original.find(TEI + "teiHeader")
    source_group = original.find(f"{TEI}text/{TEI}group")
    candidate_header = result.find(TEI + "teiHeader")
    candidate_text = result.find(TEI + "text")
    if source_header is None or source_group is None or len(source_group) != 2:
        return ["retained source envelope no longer has one header and two nested texts"]
    first, second = source_group
    if candidate_header is None or candidate_text is None or len(result) != 2 or result.find(f"{TEI}text/{TEI}group") is not None:
        findings.append("candidate is not one directly addressable first-work TEI text")
        return findings
    if _tree_digest(source_header) != _tree_digest(candidate_header):
        findings.append("candidate header differs from retained source")
    if _tree_digest(first) != _tree_digest(candidate_text):
        findings.append("candidate first text differs from complete retained first text")
    if _tree_digest(first) != profile.get("first_text_tree_sha256") or _tree_digest(second) != profile.get("second_text_tree_sha256"):
        findings.append("source first/second boundary differs from independent profile")
    if _tree_digest(source_header) != profile.get("header_tree_sha256"):
        findings.append("source header differs from independent profile")
    if _counts(original) != profile.get("source_element_counts"):
        findings.append("complete retained source element census differs")
    if _counts(first) != profile.get("first_element_counts") or _counts(second) != profile.get("second_element_counts"):
        findings.append("work or excluded matter element census differs")
    if len(_pages(first)) != profile.get("first_page_breaks") or len(_pages(second)) != profile.get("second_page_breaks"):
        findings.append("source page-break partition differs")
    if _pages(first) != _pages(candidate_text):
        findings.append("candidate page milestones differ from first work")
    trailer = first.find(f"{TEI}body/{TEI}trailer")
    appendix = first.find(f"{TEI}back/{TEI}div[@type='appendix']")
    preface = second.find(f"{TEI}front/{TEI}div[@type='preface']")
    if trailer is None or "Thus endeth the first examyna" not in "".join(trailer.itertext()) or appendix is None:
        findings.append("first-work terminal matter differs")
    if preface is None or "Who euer hearde anye goodnesse" not in "".join(preface.itertext()):
        findings.append("out-of-work preface anchor differs")
    if any(page.get("facs") == "tcp:384:60" for page in first.iter(TEI + "pb")):
        findings.append("first-work selection includes the trailing image-60 fragment")
    if not any(page.get("facs") == "tcp:384:60" for page in second.iter(TEI + "pb")):
        findings.append("excluded source fragment no longer identifies image 60")
    if schema_path is not None:
        schema = etree.XMLSchema(etree.parse(str(schema_path), etree.XMLParser(resolve_entities=False, no_network=True)))
        document = etree.ElementTree(etree.fromstring(candidate, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)))
        if not schema.validate(document):
            findings.append(f"TEI P5 validation failed: {schema.error_log.last_error}")
    return findings


def _closure_digest() -> str:
    root = Path(__file__).resolve().parents[2]
    paths = (Path(__file__).resolve(), root / "ocd_kernel/__init__.py", root / "ocd_kernel/reconstruction/__init__.py", root / "ocd_kernel/reconstruction/contract.py")
    return _sha(_json([{"path": path.relative_to(root).as_posix(), "sha256": _sha(path.read_bytes())} for path in paths]))


def _oracle(manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    source = manifest.authority_path("retained-tei-p5").read_bytes()
    content = candidate.member_bytes("content.tei.xml")
    profile_bytes = manifest.authority_path("reconstruction-profile").read_bytes()
    policy_bytes = manifest.authority_path("validation-policy").read_bytes()
    profile = json.loads(profile_bytes)
    policy = json.loads(policy_bytes)
    problems = _check(source, content, profile, schema_path=manifest.authority_path("tei-p5-xsd"))
    if _sha(source) != SOURCE_SHA or profile.get("source_sha256") != SOURCE_SHA:
        problems.append("retained source digest differs")
    if manifest.record.get("source_id") != "tcp-A22076" or manifest.record.get("work_id") != "anne-askew-first-examinacyon":
        problems.append("candidate source/work identity differs")
    if candidate.member_bytes("README.source.md") != manifest.authority_path("source-local-attribution-readme").read_bytes():
        problems.append("source credit differs")
    if candidate.member_bytes("provenance.json") != _json(policy["provenance"]):
        problems.append("provenance policy differs")
    if candidate.member_bytes("unresolved.jsonl") != b"".join(_json(item) for item in policy["unresolved"]):
        problems.append("unresolved ledger differs")
    account = json.loads(candidate.member_bytes("source-accountability.json"))
    if (account.get("source_sha256") != SOURCE_SHA or account.get("candidate_sha256") != _sha(content)
            or account.get("included", {}).get("selector") != "/TEI/text/group/text[1]"
            or account.get("included", {}).get("source_tree_sha256") != profile.get("first_text_tree_sha256")
            or account.get("excluded", {}).get("selector") != "/TEI/text/group/text[2]"
            or account.get("excluded", {}).get("source_tree_sha256") != profile.get("second_text_tree_sha256")
            or account.get("excluded", {}).get("physical_placement") != "unverified"):
        problems.append("accounting does not bind included and excluded source scopes")
    mutations: list[str] = []
    try:
        altered = ET.fromstring(content)
        body = altered.find(f"{TEI}text/{TEI}body")
        assert body is not None
        first_word = next(node for node in body.iter() if node.text and node.text.strip())
        first_word.text = (first_word.text or "") + " MUTATED"
        if "candidate first text differs" in " ".join(_check(source, ET.tostring(altered, encoding="utf-8"), profile, schema_path=None)):
            mutations.append("text")
        altered = ET.fromstring(content)
        page = next(altered.iter(TEI + "pb"))
        page.set("n", "MUTATED")
        if "candidate page milestones differ" in " ".join(_check(source, ET.tostring(altered, encoding="utf-8"), profile, schema_path=None)):
            mutations.append("page")
        altered = ET.fromstring(content)
        excluded = deepcopy(ET.fromstring(source).find(f"{TEI}text/{TEI}group/{TEI}text[2]"))
        altered.append(excluded)
        if "candidate is not one directly addressable" in " ".join(_check(source, ET.tostring(altered, encoding="utf-8"), profile, schema_path=None)):
            mutations.append("wrong-work")
    except (ET.ParseError, StopIteration, AssertionError, AttributeError) as exc:
        problems.append(f"mutation setup failed: {exc}")
    if mutations != ["text", "page", "wrong-work"]:
        problems.append(f"mutation rejection coverage differs: {mutations}")
    result = {
        "status": "pass" if not problems else "fail",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": _closure_digest(),
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(profile_bytes),
        "package_schema_sha256": str(manifest.record["package_schema"]["sha256"]),
        "source_sha256": SOURCE_SHA,
        "xsd_sha256": _sha(manifest.authority_path("tei-p5-xsd").read_bytes()),
        "policy_sha256": _sha(policy_bytes),
        "findings": problems + [f"mutation rejected: {name}" for name in mutations],
    }
    result["result_sha256"] = _sha(_json(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
