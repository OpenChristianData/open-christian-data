"""Producer-independent oracle for the exact-byte Evans-TCP N15943 candidate."""

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


ORACLE_ID = "ocd-evans-tcp-n15943-exact-source-oracle"
ORACLE_VERSION = "2"


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


def _feature_findings(root: etree._Element) -> list[str]:
    findings: list[str] = []
    identifiers = {
        (item.get("type"), "".join(item.itertext()))
        for item in _elements(root, "idno")
    }
    if not {
        ("TCP", "N15943"),
        ("STC", "Evans 20400"),
        ("IMAGE-SET", "20400"),
    }.issubset(identifiers):
        findings.append("N15943, Evans 20400, or image-set identity is absent")

    authors = {"".join(item.itertext()) for item in _elements(root, "author")}
    publishers = {"".join(item.itertext()) for item in _elements(root, "publisher")}
    places = {"".join(item.itertext()) for item in _elements(root, "pubPlace")}
    titles = ["".join(item.itertext()) for item in _elements(root, "title")]
    if "Hammon, Jupiter, 1711-ca. 1800." not in authors:
        findings.append("Jupiter Hammon authority identity is absent")
    if not any("Printed by Carroll and Patterson" in value for value in publishers):
        findings.append("Carroll and Patterson publication identity is absent")
    if not any("New-York" in value for value in places):
        findings.append("New-York publication place is absent")
    if not any("address to the Negroes" in value for value in titles):
        findings.append("Hammon address title identity is absent")

    div_types = Counter(item.get("type") for item in _elements(root, "div"))
    if div_types != Counter(
        {"title_page": 1, "dedication": 1, "to_the_reader": 1, "address": 1}
    ):
        findings.append("source-defined division types or counts drifted")
    heads = ["".join(item.itertext()) for item in _elements(root, "head")]
    required_heads = ("AFRICAN SOCIETY", "PUBLIC", "ADDRESS TO THE NEGROES")
    if any(not any(required in head for head in heads) for required in required_heads):
        findings.append("African Society, public notice, or main-address heading drifted")

    g_refs = Counter(item.get("ref") for item in _elements(root, "g"))
    if g_refs != Counter({"char:EOLhyphen": 83, "char:punc": 1}):
        findings.append("encoded-character references or counts drifted")
    gaps = _elements(root, "gap")
    if len(gaps) != 1 or (
        gaps[0].get("reason"), gaps[0].get("extent")
    ) != ("illegible: blotted", "1 word"):
        findings.append("blotted-word gap drifted")
    if gaps and "".join(gaps[0].itertext()).strip() != "〈◊〉":
        findings.append("blotted-word gap description drifted")

    pages = _elements(root, "pb")
    expected_page_numbers = [None, None, "iii", "iv", None] + [
        str(number) for number in range(6, 21)
    ]
    if [item.get("n") for item in pages] != expected_page_numbers:
        findings.append("page milestone sequence drifted")
    if any(not (item.get("facs") or "").startswith("unknown:") for item in pages):
        findings.append("preserved unknown facsimile targets drifted")
    if len(pages) < 2 or pages[1].get("rendition") != "simple:additions":
        findings.append("title-page additions rendition drifted")

    paragraph_numbers = Counter(item.get("n") for item in _elements(root, "p"))
    if paragraph_numbers != Counter({None: 30, "1": 1, "2": 1}):
        findings.append("numbered counsel paragraphs drifted")
    if (
        len(_elements(root, "q")) != 2
        or len(_elements(root, "hi")) != 15
        or len(_elements(root, "dateline")) != 2
        or len(_elements(root, "signed")) != 2
        or len(_elements(root, "closer")) != 2
    ):
        findings.append("quotation, emphasis, dateline, signature, or closer structure drifted")
    if ["".join(item.itertext()) for item in _elements(root, "trailer")] != [
        "FINIS."
    ]:
        findings.append("final FINIS trailer drifted")
    return findings


def _plain_mapping(value: object) -> dict[str, object] | None:
    return dict(value) if isinstance(value, Mapping) else None


def _oracle(
    source_manifest: SourceManifest,
    candidate: CandidatePackage,
) -> Mapping[str, object]:
    source_bytes = source_manifest.authority_path("retained-tei-p5").read_bytes()
    candidate_bytes = candidate.member_bytes("content.tei.xml")
    profile_bytes = source_manifest.authority_path("reconstruction-profile").read_bytes()
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    profile = _strict_json_object(profile_bytes, "reconstruction profile")
    policy = _strict_json_object(policy_bytes, "validation policy")
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
        findings.append("candidate manifest source-manifest path or digest binding failed")
    if _plain_mapping(candidate.manifest.get("converter")) != dict(
        source_manifest.record["converter"]
    ):
        findings.append("candidate manifest converter binding failed")
    if _plain_mapping(candidate.manifest.get("package_schema")) != dict(
        source_manifest.record["package_schema"]
    ):
        findings.append("candidate manifest package-schema binding failed")

    readme_bytes = candidate.member_bytes("README.source.md")
    expected_readme = source_manifest.authority_path(
        "source-local-attribution-readme"
    ).read_bytes()
    if readme_bytes != expected_readme or _sha(readme_bytes) != policy.get(
        "readme_sha256"
    ):
        findings.append("source README bytes do not match the attribution authority")

    provenance_bytes = candidate.member_bytes("provenance.json")
    expected_provenance = _canonical(policy.get("provenance"))
    try:
        provenance = _strict_json_object(provenance_bytes, "provenance")
    except ValueError:
        provenance = None
    if provenance is None or provenance_bytes != expected_provenance:
        findings.append("provenance bytes do not match the validation policy")

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
    if (
        unresolved is None
        or unresolved != expected_rows
        or unresolved_bytes != expected_unresolved
    ):
        findings.append("unresolved ledger records, order, status, or bytes differ")

    try:
        source_root = _parse(source_bytes)
        source_counts, source_census = _census(source_root)
    except etree.XMLSyntaxError as exc:
        findings.append(f"retained source XML parsing failed: {exc}")
        source_root = None
        source_counts = {}
        source_census = {}
    if source_counts != profile.get("element_counts") or source_census != profile.get(
        "source_census"
    ):
        findings.append("retained source census does not match profile")
    if source_root is not None:
        findings.extend(_feature_findings(source_root))

    accountability_policy = policy.get("accountability")
    expected_accountability = (
        {
            **accountability_policy,
            "source_id": source_manifest.record["source_id"],
            "source_content_bytes": len(source_bytes),
            "source_content_sha256": _sha(source_bytes),
            "candidate_content_bytes": len(candidate_bytes),
            "candidate_content_sha256": _sha(candidate_bytes),
            "source_census": source_census,
            "element_counts": source_counts,
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
    if accountability is None or accountability_bytes != _canonical(
        expected_accountability
    ):
        findings.append("source accountability does not bind the complete zero-loss policy")

    if candidate_bytes != source_bytes:
        findings.append("candidate TEI is not byte-identical to retained N15943 XML")

    if not findings and source_root is not None:
        try:
            candidate_root = _parse(candidate_bytes)
        except etree.XMLSyntaxError as exc:
            findings.append(f"candidate XML parsing failed: {exc}")
        else:
            candidate_counts, candidate_census = _census(candidate_root)
            if candidate_counts != source_counts or candidate_census != source_census:
                findings.append("candidate census does not match retained source")
            findings.extend(_feature_findings(candidate_root))
            schema = etree.XMLSchema(
                etree.parse(str(source_manifest.authority_path("tei-p5-xsd")))
            )
            if not schema.validate(candidate_root):
                findings.append(f"TEI P5 XSD failure: {schema.error_log.last_error}")

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
