"""Independent HTMLParser and TEI checks for the PG 16455 candidate."""

from __future__ import annotations

import ast
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import platform
import re
import sys
from typing import Mapping
import zipfile

from jsonschema import Draft202012Validator
from lxml import etree, html

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest


ORACLE_ID = "ocd-otterbein-pg16455-independent-html-oracle-v1"
ORACLE_VERSION = "1"
TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
SOURCE_SHA = "49221d85bf34139c6ddad71dcd31076da47236042cf346fd93da39da1a2d7362"
SOURCE_BYTES = 823187
SOURCE_PATH = "raw/gutenberg/16455/html/pg16455-images.html"
PROFILE_ID = "otterbein-pg16455-retained-html-v1"
POLICY_ID = "otterbein-pg16455-retained-html-policy-v1"
IDENTITY = {
    "work_id": "otterbein-hymnal",
    "textual_form_id": "otterbein-hymnal-gutenberg-retained",
    "edition_id": "otterbein-hymnal-gutenberg-electronic",
    "acquisition_id": "otterbein-hymnal-gutenberg-acquired",
}


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def _strict(value: bytes, label: str) -> dict[str, object]:
    result = json.loads(value.decode("utf-8", errors="strict"))
    if not isinstance(result, dict):
        raise ValueError(f"{label} must be a JSON object")
    return result


class _HTMLInventory(HTMLParser):
    """Flat parser traversal independent of the producer's lxml tree mapping."""

    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_body = False
        self.depth = 0
        self.parts: list[str] = []
        self.links: list[str] = []
        self.hymns: list[tuple[str, str]] = []
        self.stanzas = 0
        self.comments: list[str] = []
        self.ids: list[str] = []
        self.direct = 0
        self.direct_comments = 0
        self.elements = 0
        self.images = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "body":
            self.in_body = True
            self.depth = 0
            return
        if not self.in_body:
            return
        if self.depth == 0:
            self.direct += 1
        self.elements += 1
        classes = (values.get("class") or "").split()
        if values.get("id"):
            self.ids.append(str(values["id"]))
        if tag == "div" and "hymn" in classes:
            self.hymns.append((str(values.get("id") or ""), ""))
        if tag == "div" and "verse" in classes:
            self.stanzas += 1
        if tag == "a" and values.get("href") is not None:
            self.links.append(str(values["href"]))
        if tag == "img":
            self.images += 1
        if tag not in self.VOID:
            self.depth += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag == "body" and self.in_body:
            self.in_body = False
            self.depth = 0
            return
        if self.in_body and tag not in self.VOID:
            self.depth = max(0, self.depth - 1)

    def handle_data(self, data: str) -> None:
        if self.in_body:
            self.parts.append(data)

    def handle_comment(self, data: str) -> None:
        if self.in_body:
            if self.depth == 0:
                self.direct_comments += 1
            self.comments.append(data.strip())


def _scan_source(source: bytes) -> _HTMLInventory:
    if len(source) != SOURCE_BYTES or _sha(source) != SOURCE_SHA:
        raise ValueError("retained PG 16455 HTML identity drifted")
    scanner = _HTMLInventory()
    scanner.feed(source.decode("utf-8", errors="strict"))
    scanner.close()
    return scanner


def _source_href_targets(hrefs: list[str], source_ids: set[str]) -> list[str]:
    return ["#ob-" + re.sub(r"[^A-Za-z0-9_.-]", "-", href[1:]) if href.startswith("#") and href[1:] in source_ids else href for href in hrefs]


def _verify_tei(source: bytes, tei_bytes: bytes, profile: Mapping[str, object], scanner: _HTMLInventory) -> None:
    try:
        root = etree.fromstring(tei_bytes)
    except etree.XMLSyntaxError as exc:
        raise ValueError("candidate TEI is not well-formed") from exc
    if root.tag != f"{{{TEI}}}TEI" or root.get(XML_ID) != "otterbein-hymnal-candidate":
        raise ValueError("candidate work identity or TEI root drifted")
    bodies = root.xpath("./tei:text/tei:body", namespaces={"tei": TEI})
    if len(bodies) != 1:
        raise ValueError("candidate must contain exactly one TEI body")
    body = bodies[0]
    if "".join(body.itertext()) != "".join(scanner.parts):
        raise ValueError("source body text was omitted, changed, invented, or reordered")
    source_hymn_ids = [identifier for identifier, _ in scanner.hymns]
    candidate_hymns = root.xpath(".//tei:div[@type='hymn']", namespaces={"tei": TEI})
    candidate_ids = [node.get(XML_ID, "") for node in candidate_hymns]
    expected_ids = ["ob-" + re.sub(r"[^A-Za-z0-9_.-]", "-", value) for value in source_hymn_ids]
    if len(candidate_hymns) != 548 or candidate_ids != expected_ids:
        raise ValueError("hymn omission, duplication, order, or identity drifted")
    for number, node in enumerate(candidate_hymns, 1):
        if node.get("n") != str(number):
            raise ValueError(f"hymn number or order drifted at {number}")
    if len(root.xpath(".//tei:lg[@type='stanza']", namespaces={"tei": TEI})) != scanner.stanzas or scanner.stanzas != 2322:
        raise ValueError("source stanza groups were omitted, duplicated, or altered")
    source_ids = set(scanner.ids)
    expected_hrefs = _source_href_targets(scanner.links, source_ids)
    actual_hrefs = [node.get("target", "") for node in root.xpath(".//tei:ref", namespaces={"tei": TEI})]
    if actual_hrefs != expected_hrefs or len(actual_hrefs) != 588:
        raise ValueError("source link identity, target, order, or count drifted")
    candidate_ids_all = root.xpath("//@xml:id", namespaces={"xml": "http://www.w3.org/XML/1998/namespace"})
    if len(candidate_ids_all) != len(set(candidate_ids_all)):
        raise ValueError("candidate xml:id values are not unique")
    targets = [target[1:] for target in actual_hrefs if target.startswith("#")]
    idset = set(candidate_ids_all)
    if any(target not in idset for target in targets):
        raise ValueError("candidate local reference target does not resolve")
    source_page_numbers = [re.fullmatch(r'script:\s*pg\("([0-9]+)"\)', value).group(1) for value in scanner.comments if re.fullmatch(r'script:\s*pg\("([0-9]+)"\)', value)]
    candidate_page_numbers = [node.get("n", "") for node in root.xpath(".//tei:pb[@type='source-comment']", namespaces={"tei": TEI})]
    if len(scanner.comments) != 394 or candidate_page_numbers != source_page_numbers:
        raise ValueError("source page-marker comments were omitted, altered, or reordered")
    identity = profile["identity"]
    assert isinstance(identity, Mapping)
    title = root.xpath("string(./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title)", namespaces={"tei": TEI})
    if title != identity["work_title"]:
        raise ValueError("candidate TEI title does not match its source profile")


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    if source_manifest.record.get("ticket_id") != "L743" or source_manifest.record.get("work_id") != "otterbein-hymnal":
        raise ValueError("candidate work route is not L743 Otterbein Hymnal")
    source = source_manifest.authority_path("retained-html").read_bytes()
    profile_bytes = source_manifest.authority_path("reconstruction-profile").read_bytes()
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    profile = _strict(profile_bytes, "Otterbein profile")
    policy = _strict(policy_bytes, "Otterbein policy")
    if profile.get("profile_id") != PROFILE_ID or policy.get("policy_id") != POLICY_ID:
        raise ValueError("candidate profile or validation policy identity drifted")
    converter = source_manifest.record["converter"]
    validator = source_manifest.record["validator"]
    assert isinstance(converter, Mapping) and isinstance(validator, Mapping)
    manifest_path = source_manifest.path.relative_to(source_manifest.repository_root).as_posix()
    if candidate.manifest.get("status") != "nonaccepted" or candidate.manifest.get("source_id") != source_manifest.record["source_id"] or candidate.manifest.get("source_manifest") != {"path": manifest_path, "sha256": source_manifest.sha256} or candidate.manifest.get("converter") != dict(converter):
        raise ValueError("candidate manifest source, producer, or lifecycle binding drifted")
    scanner = _scan_source(source)
    _verify_tei(source, candidate.member_bytes("content.tei.xml"), profile, scanner)
    if len(scanner.hymns) != 548 or scanner.stanzas != 2322 or len(scanner.links) != 588 or len(scanner.comments) != 394 or scanner.direct + scanner.direct_comments != 592 or scanner.images != 0:
        raise ValueError("independent HTMLParser inventory contradicts the declared source profile")
    accounting = _strict(candidate.member_bytes("source-accountability.json"), "Otterbein accounting")
    schema = _strict(source_manifest.authority_path("source-accountability-schema").read_bytes(), "Otterbein accounting schema")
    errors = sorted(Draft202012Validator(schema).iter_errors(accounting), key=str)
    if errors:
        raise ValueError(f"source-accountability schema failure: {errors[0].message}")
    if accounting.get("identity") != IDENTITY or accounting.get("source", {}).get("sha256") != SOURCE_SHA or accounting.get("scope_counts", {}).get("hymns") != len(scanner.hymns) or accounting.get("scope_counts", {}).get("stanzas") != scanner.stanzas or accounting.get("scope_counts", {}).get("links") != len(scanner.links) or accounting.get("scope_counts", {}).get("page_comments") != len(scanner.comments):
        raise ValueError("source accounting does not match independent inventory")
    content = candidate.member_bytes("content.tei.xml")
    xsd = etree.XMLSchema(etree.parse(str(source_manifest.authority_path("tei-p5-xsd"))))
    if not xsd.validate(etree.fromstring(content)):
        raise ValueError(f"candidate fails TEI P5 XSD: {xsd.error_log.last_error}")
    zip_bytes = source_manifest.authority_path("acquisition-package").read_bytes()
    with zipfile.ZipFile(source_manifest.authority_path("acquisition-package")) as archive:
        names = [item.filename for item in archive.infolist() if not item.is_dir()]
        if names != ["pg16455-images.html", "16455-cover.png"] or archive.read("pg16455-images.html") != source:
            raise ValueError("retained ZIP envelope or selected HTML member drifted")
    expected_members = {item["path"]: item for item in accounting["member_census"]}
    if expected_members[SOURCE_PATH]["sha256"] != SOURCE_SHA or expected_members["raw/gutenberg/16455/pg16455-h.zip"]["sha256"] != _sha(zip_bytes):
        raise ValueError("acquisition package member accounting drifted")
    provenance = _strict(candidate.member_bytes("provenance.json"), "Otterbein provenance")
    if provenance.get("status") != "nonaccepted" or provenance.get("work_id") != "otterbein-hymnal" or provenance.get("candidate_boundary", {}).get("canonical_master_written") is not False or provenance.get("candidate_boundary", {}).get("lifecycle_state_changed") is not False:
        raise ValueError("candidate provenance changed status, work identity, or lifecycle")
    unresolved = [_strict(line, "Otterbein unresolved record") for line in candidate.member_bytes("unresolved.jsonl").splitlines()]
    expected_unresolved = set(policy.get("required_unresolved_ids", []))
    if {item.get("id") for item in unresolved} != expected_unresolved or any(item.get("status") != "unresolved" for item in unresolved):
        raise ValueError("candidate unresolved human decisions are incomplete")
    if candidate.member_bytes("README.source.md") != source_manifest.authority_path("source-attribution-readme").read_bytes():
        raise ValueError("candidate source README drifted")
    result: dict[str, object] = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": str(validator["import_closure_sha256"]),
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(profile_bytes),
        "package_schema_sha256": _sha(source_manifest.authority_path("candidate-package-schema").read_bytes()),
        "source_sha256": SOURCE_SHA,
        "xsd_sha256": _sha(source_manifest.authority_path("tei-p5-xsd").read_bytes()),
        "policy_sha256": _sha(policy_bytes),
        "findings": [],
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


def _import_closure_sha256() -> str:
    root = Path(__file__).resolve().parents[2]
    logical_paths = (
        "build/tei/otterbein_pg16455_oracle.py",
        "ocd_kernel/reconstruction/contract.py",
    )
    members = []
    for logical in logical_paths:
        data = (root / logical).read_bytes()
        members.append({"path": logical, "bytes": len(data), "sha256": _sha(data)})
    result = {"contract": "ocd-otterbein-pg16455-oracle-closure-v1", "members": members,
              "lxml": list(etree.LXML_VERSION), "libxml2": list(etree.LIBXML_VERSION),
              "jsonschema": __import__("importlib.metadata", fromlist=["version"]).version("jsonschema")}
    return _sha(_canonical(result))


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
