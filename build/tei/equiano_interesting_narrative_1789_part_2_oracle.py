"""Producer-independent oracle for Equiano ECCO-TCP K053415.002."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import platform
import sys
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest


ORACLE_ID = "ocd-ecco-tcp-k053415-002-independent-oracle"
ORACLE_VERSION = "1"
TEI_NS = "http://www.tei-c.org/ns/1.0"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def _strict_json_object(content: bytes, label: str) -> dict[str, object]:
    def reject(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate key {key!r}")
            result[key] = value
        return result
    try:
        value = json.loads(content.decode("utf-8"), object_pairs_hook=reject)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _strict_jsonl(content: bytes, label: str) -> list[dict[str, object]]:
    if not content or not content.endswith(b"\n") or any(not line for line in content.splitlines()):
        raise ValueError(f"{label} must be nonempty LF-terminated JSONL")
    return [_strict_json_object(line, f"{label}[{index}]") for index, line in enumerate(content.splitlines())]


def _closure_paths() -> tuple[Path, ...]:
    root = Path(__file__).resolve().parents[2]
    return (Path(__file__).resolve(), root / "ocd_kernel/__init__.py", root / "ocd_kernel/reconstruction/__init__.py", root / "ocd_kernel/reconstruction/contract.py")


def _closure_digest() -> str:
    root = Path(__file__).resolve().parents[2]
    return _sha(_canonical([{"path": path.relative_to(root).as_posix(), "sha256": _sha(path.read_bytes())} for path in _closure_paths()]))


def _parse(content: bytes) -> etree._Element:
    return etree.fromstring(content, etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False, huge_tree=True))


def _elements(root: etree._Element, name: str) -> list[etree._Element]:
    return [item for item in root.iter() if etree.QName(item).localname == name]


def _census(root: etree._Element) -> tuple[dict[str, int], dict[str, int]]:
    elements = list(root.iter())
    return dict(sorted(Counter(etree.QName(item).localname for item in elements).items())), {
        "elements": len(elements), "attributes": sum(len(item.attrib) for item in elements),
        "text_nodes": sum(item.text is not None for item in elements),
        "tail_nodes": sum(item.tail is not None for item in elements),
        "characters": sum(len((item.text or "") + (item.tail or "")) for item in elements),
    }


def _source_findings(root: etree._Element) -> list[str]:
    findings: list[str] = []
    if root.tag != "ETS":
        return ["retained source root is not ETS"]
    if (root.xpath("string(/ETS/EEBO/IDG/@ID)"), root.xpath("string(/ETS/EEBO/IDG/BIBNO)"), root.xpath("string(/ETS/EEBO/IDG/VID)")) != ("K053415.002", "CW3301535045", "0324600502"):
        findings.append("retained source identifiers drifted")
    source_changes = root.xpath("/ETS/TEMPHEAD/REVDESCR/CHANGE")
    if len(source_changes) != 1 or (
        source_changes[0].xpath("string(DATE)"),
        source_changes[0].xpath("string(RESPSTMT/NAME)"),
        source_changes[0].xpath("string(RESPSTMT/RESP)"),
        source_changes[0].xpath("string(ITEM)"),
    ) != ("2007-10-04", "Simon Charles", "MURP", "Proofed and reviewed"):
        findings.append("retained source revision metadata drifted")
    outer = root.xpath("/ETS/EEBO/TEXT/FRONT/DIV1 | /ETS/EEBO/TEXT/BODY/DIV1")
    if [(item.get("TYPE"), item.get("N")) for item in outer] != [("frontispiece", None), ("chapter", "7"), ("chapter", "8"), ("chapter", "9"), ("chapter", "10"), ("chapter", "11"), ("chapter", "12")]:
        findings.append("retained outer divisions drifted")
    if [item.get("TYPE") for item in root.xpath("/ETS/EEBO/TEXT//TEXT/BODY/DIV1")] != ["grant", "order", "petition", "petition"]:
        findings.append("retained embedded documents drifted")
    if len(root.xpath("//LETTER")) != 5 or len(root.xpath("//DIV2[@TYPE='poem']")) != 1:
        findings.append("retained letters or poem division drifted")
    if [item.get("REF") for item in root.xpath("//PB")] != [str(number) for number in range(1, 270)]:
        findings.append("retained page references drifted")
    if Counter(item.get("EXTENT") for item in root.xpath("//GAP")) != Counter({"1 letter": 7, "1 span": 3, "1 word": 12, "1+ letters": 10, "2 letters": 3, "3 letters": 1}):
        findings.append("retained gap extent census drifted")
    text = "".join(root.xpath("/ETS/EEBO/TEXT")[0].itertext())
    if text.count("∣") != 795 or text.count("—") != 121:
        findings.append("retained diplomatic typography drifted")
    if len(root.xpath("//L")) != 124 or len(root.xpath("//LG")) != 28 or len(root.xpath("//NOTE")) != 6:
        findings.append("retained line, group, or note census drifted")
    if "MISCELLANEOUS VERSES" not in "".join(root.xpath("//DIV2[@TYPE='poem']")[0].itertext()):
        findings.append("retained Miscellaneous Verses drifted")
    if not text.rstrip().endswith("THE END."):
        findings.append("retained ending drifted")
    return findings


def _candidate_findings(source: etree._Element, candidate: etree._Element) -> list[str]:
    findings: list[str] = []
    if etree.QName(candidate).namespace != TEI_NS or etree.QName(candidate).localname != "TEI":
        return ["candidate root is not TEI P5"]
    identifiers = {(item.get("type"), "".join(item.itertext())) for item in _elements(candidate, "idno")}
    if not {("TCP", "K053415.002"), ("ESTC", "T61470"), ("Gale", "CW3301535045"), ("image-set", "0324600502"), ("Michigan", "004837188.0001.002")}.issubset(identifiers):
        findings.append("candidate bibliographic identifiers drifted")
    if "Equiano, Olaudah, b. 1745." not in {"".join(item.itertext()) for item in _elements(candidate, "author")} or "Second edition." not in {"".join(item.itertext()) for item in _elements(candidate, "edition")}:
        findings.append("candidate author or edition identity drifted")
    source_change = source.xpath("/ETS/TEMPHEAD/REVDESCR/CHANGE")
    candidate_changes = candidate.xpath(
        "/*[local-name()='TEI']/*[local-name()='teiHeader']"
        "/*[local-name()='revisionDesc']/*[local-name()='change']"
    )
    if len(source_change) != 1 or len(candidate_changes) != 2:
        findings.append("candidate revision history drifted")
    else:
        expected_date = source_change[0].xpath("string(DATE)")
        expected_text = (
            f"{source_change[0].xpath('string(ITEM)')} by "
            f"{source_change[0].xpath('string(RESPSTMT/NAME)')}; responsibility "
            f"{source_change[0].xpath('string(RESPSTMT/RESP)')}."
        )
        if (
            candidate_changes[0].get("when"),
            "".join(candidate_changes[0].itertext()),
        ) != (expected_date, expected_text):
            findings.append("candidate source revision metadata drifted")
    source_text = "".join(source.xpath("/ETS/EEBO/TEXT")[0].itertext())
    text_nodes = _elements(candidate, "text")
    if len(text_nodes) != 1 or "".join(text_nodes[0].itertext()) != source_text:
        findings.append("candidate text is not exact outer source TEXT")
    outer = candidate.xpath("/*[local-name()='TEI']/*[local-name()='text']/*[local-name()='front']/*[local-name()='div'] | /*[local-name()='TEI']/*[local-name()='text']/*[local-name()='body']/*[local-name()='div']")
    if [(item.get("type"), item.get("n")) for item in outer] != [("frontispiece", None), ("chapter", "7"), ("chapter", "8"), ("chapter", "9"), ("chapter", "10"), ("chapter", "11"), ("chapter", "12")]:
        findings.append("candidate outer divisions drifted")
    floating_divs = candidate.xpath("//*[local-name()='floatingText']/*[local-name()='body']/*[local-name()='div']")
    if [item.get("type") for item in floating_divs if item.get("type") != "letter"] != ["grant", "order", "petition", "petition"] or sum(item.get("type") == "letter" for item in floating_divs) != 5:
        findings.append("candidate embedded documents or letters drifted")
    poem = candidate.xpath("//*[local-name()='div'][@type='poem']")
    if len(poem) != 1 or "MISCELLANEOUS VERSES" not in "".join(poem[0].itertext()) or len(_elements(candidate, "lg")) != 28 or len(_elements(candidate, "l")) != 124:
        findings.append("candidate poem or verse hierarchy drifted")
    source_pages, candidate_pages = source.xpath("//PB"), _elements(candidate, "pb")
    expected_pages = [(item.get("N"), "https://quod.lib.umich.edu/cgi/t/text/pageviewer-idx?cc=ecco&idno=004837188.0001.002&seq=" + item.get("REF")) for item in source_pages]
    if [(item.get("n"), item.get("facs")) for item in candidate_pages] != expected_pages:
        findings.append("candidate page mapping drifted")
    expected_gaps = [(item.get("DESC"), "#" + item.get("RESP"), item.get("EXTENT"), item.get("DISP")) for item in source.xpath("//GAP")]
    if [(item.get("reason"), item.get("resp"), item.get("extent"), item.get("rend")) for item in _elements(candidate, "gap")] != expected_gaps:
        findings.append("candidate gap mapping drifted")
    if [(item.get("place"), item.get("n")) for item in _elements(candidate, "note")] != [("bottom", item.get("N")) for item in source.xpath("//NOTE")]:
        findings.append("candidate note mapping drifted")
    if [item.get("rend") for item in _elements(candidate, "q")] != [item.get("REND") for item in source.xpath("//Q")]:
        findings.append("candidate quotation rendition mapping drifted")
    if any(item.get("rend") != "source-emphasis" for item in _elements(candidate, "hi")):
        findings.append("candidate emphasis mapping drifted")
    trailers = _elements(candidate, "trailer")
    if len(trailers) != 1 or "".join(trailers[0].itertext()) != "THE END.":
        findings.append("candidate ending drifted")
    return findings


def _plain_mapping(value: object) -> dict[str, object] | None:
    return dict(value) if isinstance(value, Mapping) else None


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    source_bytes = source_manifest.authority_path("retained-ets-xml").read_bytes()
    candidate_bytes = candidate.member_bytes("content.tei.xml")
    profile = _strict_json_object(source_manifest.authority_path("reconstruction-profile").read_bytes(), "reconstruction profile")
    policy = _strict_json_object(source_manifest.authority_path("validation-policy").read_bytes(), "validation policy")
    findings: list[str] = []
    expected_source_manifest = {"path": source_manifest.path.relative_to(source_manifest.repository_root).as_posix(), "sha256": source_manifest.sha256}
    if candidate.manifest.get("status") != "nonaccepted": findings.append("candidate manifest status is not nonaccepted")
    if candidate.manifest.get("source_id") != source_manifest.record.get("source_id"): findings.append("candidate manifest source_id binding failed")
    if _plain_mapping(candidate.manifest.get("source_manifest")) != expected_source_manifest: findings.append("candidate manifest source-manifest binding failed")
    if _plain_mapping(candidate.manifest.get("converter")) != dict(source_manifest.record["converter"]): findings.append("candidate manifest converter binding failed")
    if _plain_mapping(candidate.manifest.get("package_schema")) != dict(source_manifest.record["package_schema"]): findings.append("candidate manifest package-schema binding failed")
    readme = candidate.member_bytes("README.source.md")
    if readme != source_manifest.authority_path("source-local-attribution-readme").read_bytes() or _sha(readme) != policy.get("readme_sha256"): findings.append("source README bytes differ")
    provenance = candidate.member_bytes("provenance.json")
    try: parsed_provenance = _strict_json_object(provenance, "provenance")
    except ValueError: parsed_provenance = None
    if parsed_provenance is None or provenance != _canonical(policy.get("provenance")): findings.append("provenance bytes differ")
    unresolved_bytes = candidate.member_bytes("unresolved.jsonl")
    expected_rows = policy.get("unresolved")
    expected_unresolved = b"".join(_canonical(row) for row in expected_rows) if isinstance(expected_rows, list) else b""
    try: unresolved = _strict_jsonl(unresolved_bytes, "unresolved ledger")
    except ValueError: unresolved = None
    if unresolved != expected_rows or unresolved_bytes != expected_unresolved: findings.append("unresolved ledger differs")
    try:
        source_root = _parse(source_bytes); source_counts, source_census = _census(source_root)
    except etree.XMLSyntaxError as exc:
        findings.append(f"retained source parsing failed: {exc}"); source_root = None; source_counts, source_census = {}, {}
    if source_counts != profile.get("element_counts") or source_census != profile.get("source_census"): findings.append("retained source census differs")
    if source_root is not None: findings.extend(_source_findings(source_root))
    try:
        candidate_root = _parse(candidate_bytes); candidate_counts, candidate_census = _census(candidate_root)
    except etree.XMLSyntaxError as exc:
        findings.append(f"candidate parsing failed: {exc}"); candidate_root = None; candidate_counts, candidate_census = {}, {}
    if candidate_counts != profile.get("candidate_element_counts"): findings.append("candidate element census differs")
    if source_root is not None and candidate_root is not None:
        findings.extend(_candidate_findings(source_root, candidate_root))
        schema = etree.XMLSchema(etree.parse(str(source_manifest.authority_path("tei-p5-xsd"))))
        if not schema.validate(candidate_root): findings.append(f"TEI P5 XSD failure: {schema.error_log.last_error}")
    source_text = "".join(source_root.xpath("/ETS/EEBO/TEXT")[0].itertext()) if source_root is not None else ""
    candidate_text = "".join(_elements(candidate_root, "text")[0].itertext()) if candidate_root is not None and len(_elements(candidate_root, "text")) == 1 else ""
    accountability_policy = policy.get("accountability")
    expected_accountability = ({**accountability_policy, "source_id": source_manifest.record["source_id"], "source_content_bytes": len(source_bytes), "source_content_sha256": _sha(source_bytes), "candidate_content_bytes": len(candidate_bytes), "candidate_content_sha256": _sha(candidate_bytes), "source_text_characters": len(source_text), "source_text_sha256": _sha(source_text.encode("utf-8")), "candidate_text_characters": len(candidate_text), "candidate_text_sha256": _sha(candidate_text.encode("utf-8")), "source_census": source_census, "element_counts": source_counts, "candidate_census": candidate_census, "candidate_element_counts": candidate_counts} if isinstance(accountability_policy, dict) else {})
    accountability_bytes = candidate.member_bytes("source-accountability.json")
    try: accountability = _strict_json_object(accountability_bytes, "source accountability")
    except ValueError: accountability = None
    if accountability is None or accountability_bytes != _canonical(expected_accountability): findings.append("source accountability differs")
    bindings = {item["role"]: item for item in source_manifest.record["authorities"]}
    result: dict[str, object] = {
        "status": "pass" if not findings else "fail", "oracle_id": ORACLE_ID, "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()), "import_closure_sha256": _closure_digest(),
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source_manifest.sha256, "candidate_sha256": candidate.sha256,
        "profile_sha256": bindings["complete-source-feature-profile"]["sha256"], "package_schema_sha256": bindings["candidate-package-schema"]["sha256"],
        "source_sha256": bindings["primary-source"]["sha256"], "xsd_sha256": bindings["tei-validation-schema"]["sha256"],
        "policy_sha256": bindings["independent-validation-policy"]["sha256"], "findings": findings,
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()


__all__: tuple[str, ...] = ()
