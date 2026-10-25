"""Producer-independent oracle for Equiano ECCO-TCP K053415.001."""

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


ORACLE_ID = "ocd-ecco-tcp-k053415-001-independent-oracle"
ORACLE_VERSION = "1"
TEI_NS = "http://www.tei-c.org/ns/1.0"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _strict_json_object(content: bytes, label: str) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(content.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _strict_jsonl(content: bytes, label: str) -> list[dict[str, object]]:
    if not content or not content.endswith(b"\n"):
        raise ValueError(f"{label} must be nonempty LF-terminated JSONL")
    lines = content.splitlines()
    if any(not line for line in lines):
        raise ValueError(f"{label} has an empty record")
    return [
        _strict_json_object(line, f"{label}[{index}]")
        for index, line in enumerate(lines)
    ]


def _closure_paths() -> tuple[Path, ...]:
    root = Path(__file__).resolve().parents[2]
    return (
        Path(__file__).resolve(),
        root / "ocd_kernel/__init__.py",
        root / "ocd_kernel/reconstruction/__init__.py",
        root / "ocd_kernel/reconstruction/contract.py",
    )


def _closure_digest() -> str:
    root = Path(__file__).resolve().parents[2]
    records = [
        {"path": path.relative_to(root).as_posix(), "sha256": _sha(path.read_bytes())}
        for path in _closure_paths()
    ]
    return _sha(_canonical(records))


def _parse(content: bytes) -> etree._Element:
    return etree.fromstring(
        content,
        etree.XMLParser(
            resolve_entities=False,
            no_network=True,
            remove_comments=False,
            huge_tree=True,
        ),
    )


def _elements(root: etree._Element, name: str) -> list[etree._Element]:
    return [item for item in root.iter() if etree.QName(item).localname == name]


def _census(root: etree._Element) -> tuple[dict[str, int], dict[str, int]]:
    elements = list(root.iter())
    counts = Counter(etree.QName(element).localname for element in elements)
    census = {
        "elements": len(elements),
        "attributes": sum(len(element.attrib) for element in elements),
        "text_nodes": sum(element.text is not None for element in elements),
        "tail_nodes": sum(element.tail is not None for element in elements),
        "characters": sum(
            len((element.text or "") + (element.tail or "")) for element in elements
        ),
    }
    return dict(sorted(counts.items())), census


def _source_feature_findings(root: etree._Element) -> list[str]:
    findings: list[str] = []
    if root.tag != "ETS":
        return ["retained source root is not ETS"]
    if root.xpath("string(/ETS/EEBO/IDG/@ID)") != "K053415.001":
        findings.append("retained TCP identity drifted")
    if root.xpath("string(/ETS/EEBO/IDG/BIBNO)") != "CW3301534748":
        findings.append("retained Gale document identity drifted")
    if root.xpath("string(/ETS/EEBO/IDG/VID)") != "0324600501":
        findings.append("retained image-set identity drifted")
    divisions = root.xpath("/ETS/EEBO/TEXT/FRONT/DIV1 | /ETS/EEBO/TEXT/BODY/DIV1")
    if [(item.get("TYPE"), item.get("N")) for item in divisions] != [
        ("frontispiece", None),
        ("title page", None),
        ("dedication", None),
        ("list of subscribers", None),
        ("errata", None),
        ("table of contents", None),
        ("chapter", "1"),
        ("chapter", "2"),
        ("chapter", "3"),
        ("chapter", "4"),
        ("chapter", "5"),
        ("chapter", "6"),
    ]:
        findings.append("retained part-one divisions drifted")
    pages = root.xpath("//PB")
    if [item.get("REF") for item in pages] != [str(number) for number in range(1, 298)]:
        findings.append("retained page-reference sequence drifted")
    if Counter(item.get("EXTENT") for item in root.xpath("//GAP")) != Counter(
        {"1 letter": 12, "1 span": 15, "1 word": 6, "1+ letters": 8,
         "2 letters": 5, "3 letters": 1, "3+ letters": 4, "4+ letters": 3}
    ):
        findings.append("retained gap extent census drifted")
    text = "".join(root.xpath("/ETS/EEBO/TEXT")[0].itertext())
    if text.count("∣") != 789 or text.count("—") != 102:
        findings.append("retained diplomatic typography census drifted")
    if len(root.xpath("//NOTE")) != 20 or len(root.xpath("//L")) != 48:
        findings.append("retained notes or verse-line census drifted")
    if not text.rstrip().endswith("END OF THE FIRST VOLUME."):
        findings.append("retained volume-one ending drifted")
    return findings


def _candidate_feature_findings(
    source: etree._Element, candidate: etree._Element
) -> list[str]:
    findings: list[str] = []
    if etree.QName(candidate).namespace != TEI_NS or etree.QName(candidate).localname != "TEI":
        findings.append("candidate root is not TEI P5")
        return findings
    identifiers = {
        (item.get("type"), "".join(item.itertext()))
        for item in _elements(candidate, "idno")
    }
    if not {
        ("TCP", "K053415.001"),
        ("ESTC", "T61470"),
        ("Gale", "CW3301534748"),
        ("image-set", "0324600501"),
        ("Michigan", "004837188.0001.001"),
    }.issubset(identifiers):
        findings.append("candidate bibliographic identifiers drifted")
    if "Equiano, Olaudah, b. 1745." not in {
        "".join(item.itertext()) for item in _elements(candidate, "author")
    }:
        findings.append("candidate author identity drifted")
    if "Second edition." not in {
        "".join(item.itertext()) for item in _elements(candidate, "edition")
    }:
        findings.append("candidate edition identity drifted")

    source_text = "".join(source.xpath("/ETS/EEBO/TEXT")[0].itertext())
    candidate_text_elements = _elements(candidate, "text")
    if len(candidate_text_elements) != 1 or "".join(
        candidate_text_elements[0].itertext()
    ) != source_text:
        findings.append("candidate text is not the exact source TEXT character stream")

    source_divisions = source.xpath(
        "/ETS/EEBO/TEXT/FRONT/DIV1 | /ETS/EEBO/TEXT/BODY/DIV1"
    )
    candidate_divisions = _elements(candidate, "div")
    expected_divisions = [
        ((item.get("TYPE") or "unspecified").replace(" ", "_"), item.get("N"))
        for item in source_divisions
    ]
    if [(item.get("type"), item.get("n")) for item in candidate_divisions] != expected_divisions:
        findings.append("candidate division mapping drifted")

    source_pages = source.xpath("//PB")
    candidate_pages = _elements(candidate, "pb")
    expected_pages = [
        (
            item.get("N"),
            "https://quod.lib.umich.edu/cgi/t/text/pageviewer-idx"
            "?cc=ecco&idno=004837188.0001.001&seq=" + item.get("REF"),
            "source-MS-" + item.get("MS") if item.get("MS") else None,
        )
        for item in source_pages
    ]
    if [(item.get("n"), item.get("facs"), item.get("rend")) for item in candidate_pages] != expected_pages:
        findings.append("candidate page milestone attribute mapping drifted")

    source_gaps = source.xpath("//GAP")
    candidate_gaps = _elements(candidate, "gap")
    expected_gaps = [
        (item.get("DESC"), "#" + item.get("RESP"), item.get("EXTENT"), item.get("DISP"))
        for item in source_gaps
    ]
    if [
        (item.get("reason"), item.get("resp"), item.get("extent"), item.get("rend"))
        for item in candidate_gaps
    ] != expected_gaps:
        findings.append("candidate illegible-gap attribute mapping drifted")

    source_notes = source.xpath("//NOTE")
    expected_notes = [
        ({"foot": "bottom", "marg": "margin"}.get(item.get("PLACE")), item.get("N"))
        for item in source_notes
    ]
    if [(item.get("place"), item.get("n")) for item in _elements(candidate, "note")] != expected_notes:
        findings.append("candidate note place or label mapping drifted")
    if [item.get("rend") for item in _elements(candidate, "q")] != [
        item.get("REND") for item in source.xpath("//Q")
    ]:
        findings.append("candidate quotation rendition mapping drifted")
    if any(item.get("rend") != "source-emphasis" for item in _elements(candidate, "hi")):
        findings.append("candidate emphasis mapping drifted")
    if len(_elements(candidate, "l")) != 48:
        findings.append("candidate verse-line census drifted")
    trailers = _elements(candidate, "trailer")
    if len(trailers) != 1 or "".join(trailers[0].itertext()) != "END OF THE FIRST VOLUME.":
        findings.append("candidate volume-one ending drifted")
    return findings


def _plain_mapping(value: object) -> dict[str, object] | None:
    return dict(value) if isinstance(value, Mapping) else None


def _oracle(
    source_manifest: SourceManifest,
    candidate: CandidatePackage,
) -> Mapping[str, object]:
    source_bytes = source_manifest.authority_path("retained-ets-xml").read_bytes()
    candidate_bytes = candidate.member_bytes("content.tei.xml")
    profile = _strict_json_object(
        source_manifest.authority_path("reconstruction-profile").read_bytes(),
        "reconstruction profile",
    )
    policy = _strict_json_object(
        source_manifest.authority_path("validation-policy").read_bytes(),
        "validation policy",
    )
    findings: list[str] = []

    expected_source_manifest = {
        "path": source_manifest.path.relative_to(
            source_manifest.repository_root
        ).as_posix(),
        "sha256": source_manifest.sha256,
    }
    if candidate.manifest.get("status") != "nonaccepted":
        findings.append("candidate manifest status is not nonaccepted")
    if candidate.manifest.get("source_id") != source_manifest.record.get("source_id"):
        findings.append("candidate manifest source_id binding failed")
    if _plain_mapping(candidate.manifest.get("source_manifest")) != expected_source_manifest:
        findings.append("candidate manifest source-manifest binding failed")
    if _plain_mapping(candidate.manifest.get("converter")) != dict(
        source_manifest.record["converter"]
    ):
        findings.append("candidate manifest converter binding failed")
    if _plain_mapping(candidate.manifest.get("package_schema")) != dict(
        source_manifest.record["package_schema"]
    ):
        findings.append("candidate manifest package-schema binding failed")

    readme_bytes = candidate.member_bytes("README.source.md")
    if (
        readme_bytes
        != source_manifest.authority_path("source-local-attribution-readme").read_bytes()
        or _sha(readme_bytes) != policy.get("readme_sha256")
    ):
        findings.append("source README bytes do not match authority")

    provenance_bytes = candidate.member_bytes("provenance.json")
    expected_provenance = _canonical(policy.get("provenance"))
    try:
        provenance = _strict_json_object(provenance_bytes, "provenance")
    except ValueError:
        provenance = None
    if provenance is None or provenance_bytes != expected_provenance:
        findings.append("provenance bytes do not match validation policy")

    unresolved_bytes = candidate.member_bytes("unresolved.jsonl")
    expected_rows = policy.get("unresolved")
    expected_unresolved = (
        b"".join(_canonical(row) for row in expected_rows)
        if isinstance(expected_rows, list)
        else b""
    )
    try:
        unresolved = _strict_jsonl(unresolved_bytes, "unresolved ledger")
    except ValueError:
        unresolved = None
    if unresolved != expected_rows or unresolved_bytes != expected_unresolved:
        findings.append("unresolved ledger records or bytes differ")

    try:
        source_root = _parse(source_bytes)
        source_counts, source_census = _census(source_root)
    except etree.XMLSyntaxError as exc:
        findings.append(f"retained source parsing failed: {exc}")
        source_root = None
        source_counts, source_census = {}, {}
    if source_counts != profile.get("element_counts") or source_census != profile.get("source_census"):
        findings.append("retained source census does not match profile")
    if source_root is not None:
        findings.extend(_source_feature_findings(source_root))

    try:
        candidate_root = _parse(candidate_bytes)
        candidate_counts, candidate_census = _census(candidate_root)
    except etree.XMLSyntaxError as exc:
        findings.append(f"candidate XML parsing failed: {exc}")
        candidate_root = None
        candidate_counts, candidate_census = {}, {}
    if candidate_counts != profile.get("candidate_element_counts"):
        findings.append("candidate element census does not match profile")
    if source_root is not None and candidate_root is not None:
        findings.extend(_candidate_feature_findings(source_root, candidate_root))
        schema = etree.XMLSchema(
            etree.parse(str(source_manifest.authority_path("tei-p5-xsd")))
        )
        if not schema.validate(candidate_root):
            findings.append(f"TEI P5 XSD failure: {schema.error_log.last_error}")

    source_text = (
        "".join(source_root.xpath("/ETS/EEBO/TEXT")[0].itertext())
        if source_root is not None
        else ""
    )
    candidate_text = (
        "".join(_elements(candidate_root, "text")[0].itertext())
        if candidate_root is not None and len(_elements(candidate_root, "text")) == 1
        else ""
    )
    accountability_policy = policy.get("accountability")
    expected_accountability = (
        {
            **accountability_policy,
            "source_id": source_manifest.record["source_id"],
            "source_content_bytes": len(source_bytes),
            "source_content_sha256": _sha(source_bytes),
            "candidate_content_bytes": len(candidate_bytes),
            "candidate_content_sha256": _sha(candidate_bytes),
            "source_text_characters": len(source_text),
            "source_text_sha256": _sha(source_text.encode("utf-8")),
            "candidate_text_characters": len(candidate_text),
            "candidate_text_sha256": _sha(candidate_text.encode("utf-8")),
            "source_census": source_census,
            "element_counts": source_counts,
            "candidate_census": candidate_census,
            "candidate_element_counts": candidate_counts,
        }
        if isinstance(accountability_policy, dict)
        else {}
    )
    accountability_bytes = candidate.member_bytes("source-accountability.json")
    try:
        accountability = _strict_json_object(
            accountability_bytes, "source accountability"
        )
    except ValueError:
        accountability = None
    if accountability is None or accountability_bytes != _canonical(expected_accountability):
        findings.append("source accountability does not bind zero-loss mapping")

    bindings = {item["role"]: item for item in source_manifest.record["authorities"]}
    result: dict[str, object] = {
        "status": "pass" if not findings else "fail",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": _closure_digest(),
        "runtime": (
            f"{platform.python_implementation()} {platform.python_version()} "
            f"({Path(sys.executable).resolve(strict=True)})"
        ),
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": bindings["complete-source-feature-profile"]["sha256"],
        "package_schema_sha256": bindings["candidate-package-schema"]["sha256"],
        "source_sha256": bindings["primary-source"]["sha256"],
        "xsd_sha256": bindings["tei-validation-schema"]["sha256"],
        "policy_sha256": bindings["independent-validation-policy"]["sha256"],
        "findings": findings,
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()


__all__: tuple[str, ...] = ()
