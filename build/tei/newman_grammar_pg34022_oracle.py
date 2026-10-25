"""Independent extracted-HTML oracle for the PG34022 electronic witness."""

from __future__ import annotations

from hashlib import sha256
import inspect
from io import BytesIO
import json
from pathlib import Path
import platform
import re
import sys
from typing import Mapping
from zipfile import ZipFile

from lxml import etree, html

from ocd_kernel.reconstruction.contract import (
    CandidatePackage, SourceManifest, _validation_authority_bindings,
)


ORACLE_ID = "ocd-newman-grammar-pg34022-independent-html-oracle"
ORACLE_VERSION = "1"
TEI = "http://www.tei-c.org/ns/1.0"
NS = {"t": TEI}
SOURCE_SHA = "798d867ac82ef0df1f2496cceaf06aea6fef8160f1c947dc95e4f7b2ae6def08"
ZIP_SHA = "27f6e1c54a0b5ac43b15b1ac26dabeff05a78aa27e2e2989f1633093200cedec"
COVER_SHA = "1e4c52a14131a78573156916ec5ba3954d52db27025f0acdaa23420ba05d8162"


def _sha(value: bytes) -> str:
    return sha256(value).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _closure_sha() -> str:
    contract = Path(inspect.getsourcefile(SourceManifest)).resolve(strict=True)
    return _sha(_canonical({"oracle": _sha(Path(__file__).read_bytes()),
                            "reconstruction-contract": _sha(contract.read_bytes())}))


def _norm(value: str) -> str:
    return " ".join(value.split())


def _text(node: etree._Element) -> str:
    return _norm("".join(node.itertext()))


def _class(node: etree._Element, name: str) -> bool:
    return name in (node.get("class") or "").split()


def inspect_pair(source: bytes, package: bytes, cover: bytes, candidate: bytes,
                 xsd_path: Path) -> list[str]:
    """Compare source-led carriers, order, attachments, and text without converter calls."""
    findings: list[str] = []
    if len(source) != 997641 or _sha(source) != SOURCE_SHA:
        findings.append("extracted HTML source hash or size differs")
    if len(package) != 559549 or _sha(package) != ZIP_SHA or _sha(cover) != COVER_SHA:
        findings.append("ZIP or cover authority differs")
    with ZipFile(BytesIO(package)) as archive:
        if archive.namelist() != ["pg34022-images.html", "images/cover.jpg"]:
            findings.append("ZIP member envelope differs")
        elif archive.read("pg34022-images.html") != source or archive.read("images/cover.jpg") != cover:
            findings.append("ZIP members differ from extracted files")

    document = html.document_fromstring(source)
    body = document.find("body")
    if body is None:
        return findings + ["retained HTML body absent"]
    top = list(body)
    if len(top) != 11 or [n.tag for n in top] != [
        "header", "div", "div", "hr", "div", "hr", "div", "div", "hr", "div", "footer"
    ]:
        return findings + ["complete HTML body envelope differs"]
    if top[0].get("id") != "pg-header" or top[10].get("id") != "pg-footer":
        findings.append("Project Gutenberg wrapper boundaries differ")
    if any(_text(top[i]) for i in (1, 2, 3, 5, 8)):
        findings.append("excluded spacers contain source text")
    if not top[4].xpath("./h1") or not top[6].xpath("./h2[normalize-space()='Contents']"):
        findings.append("title page or contents boundary differs")
    if not _class(top[7], "tei-body") or not _class(top[9], "tei-back"):
        findings.append("book body or footnote back matter differs")
    book = [top[i] for i in (4, 6, 7, 9)]
    if len(list(body.iterdescendants())) != 4086 or len("".join(body.itertext())) != 816105:
        findings.append("complete HTML body census differs")

    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    tei = etree.fromstring(candidate, parser)
    schema = etree.XMLSchema(etree.parse(str(xsd_path)))
    if not schema.validate(tei):
        findings.append("TEI P5 XSD fails: " + str(schema.error_log[0]))
    if tei.tag != f"{{{TEI}}}TEI":
        findings.append("TEI root differs")
    front = tei.xpath("./t:text/t:front", namespaces=NS)
    core = tei.xpath("./t:text/t:body", namespaces=NS)
    back = tei.xpath("./t:text/t:back", namespaces=NS)
    if len(front) != 1 or len(core) != 1 or len(back) != 1:
        return findings + ["front/body/back work envelope differs"]
    text_node = tei.xpath("./t:text", namespaces=NS)[0]
    source_fragments = []
    for root in book:
        for fragment in root.xpath(".//text()"):
            parent = fragment.getparent()
            if parent is not None and _class(parent, "tei-pb"):
                continue
            source_fragments.append(str(fragment))
    if _norm(" ".join(source_fragments)) != _norm(" ".join(text_node.itertext())):
        findings.append("complete selected book text differs from TEI")

    source_heads = [_text(n) for root in book for n in root.iterdescendants()
                    if n.tag in {"h1", "h2", "h3", "h4"}]
    tei_heads = [_text(n) for n in text_node.xpath(".//t:head", namespaces=NS)]
    if source_heads != tei_heads:
        findings.append("source heading order or wording differs")
    source_pages = [re.sub(r"^\[pg\s+|\]$", "", _text(n), flags=re.IGNORECASE)
                    for root in book for n in root.iterdescendants() if _class(n, "tei-pb")]
    tei_pages = text_node.xpath(".//t:pb/@n", namespaces=NS)
    if len(source_pages) != 491 or source_pages != tei_pages:
        findings.append("printed-page milestone order or labels differ")
    toc = [n for n in book[1].iterdescendants() if n.tag == "li"]
    tei_toc = text_node.xpath(".//t:list[@type='contents']/t:item", namespaces=NS)
    if len(toc) != 35 or [_text(n) for n in toc] != [_text(n) for n in tei_toc]:
        findings.append("contents entries differ")
    refs = [n for root in book for n in root.iterdescendants()
            if n.tag == "a" and (n.get("id") or "").startswith("noteref_")]
    source_notes = [n for n in book[3].iterdescendants() if n.tag == "dd" and _class(n, "tei-notetext")]
    tei_refs = text_node.xpath(".//t:ref[@type='note']", namespaces=NS)
    tei_notes = text_node.xpath(".//t:note[@place='end']", namespaces=NS)
    source_ref_numbers = [n.get("id").removeprefix("noteref_") for n in refs]
    if (len(refs) != 56 or len(source_notes) != 56 or len(tei_refs) != 56 or len(tei_notes) != 56
            or source_ref_numbers != [n.get("n") for n in tei_refs]
            or source_ref_numbers != [n.get("n") for n in tei_notes]
            or any(ref.get("target") != "#" + note.get("{http://www.w3.org/XML/1998/namespace}id")
                   for ref, note in zip(tei_refs, tei_notes))):
        findings.append("linked endnote order or attachment differs")
    source_foreign = [(n.get("lang"), _text(n)) for root in book for n in root.iterdescendants()
                      if _class(n, "tei-foreign")]
    tei_foreign = [(n.get("{http://www.w3.org/XML/1998/namespace}lang"), _text(n))
                   for n in text_node.xpath(".//t:foreign", namespaces=NS)]
    if len(source_foreign) != 135 or source_foreign != tei_foreign:
        findings.append("foreign-language span order, label, or text differs")
    source_quotes = [
        _norm(" ".join(str(fragment) for fragment in n.xpath(".//text()")
                       if not _class(fragment.getparent(), "tei-pb")))
        for root in book for n in root.iterdescendants() if _class(n, "tei-q")
    ]
    tei_quotes = [_norm(" ".join(n.itertext())) for n in text_node.xpath(".//t:q", namespaces=NS)]
    if len(source_quotes) != 829 or source_quotes != tei_quotes:
        findings.append("inline quotation order or text differs")
    if len(text_node.xpath(".//t:milestone[@unit='source-horizontal-rule']", namespaces=NS)) != 13:
        findings.append("typographic break count differs")
    return findings


def _oracle(manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    findings: list[str] = []
    try:
        findings = inspect_pair(
            manifest.authority_path("retained-source").read_bytes(),
            manifest.authority_path("retained-package").read_bytes(),
            manifest.authority_path("retained-cover").read_bytes(),
            candidate.member_bytes("content.tei.xml"),
            manifest.authority_path("tei-p5-xsd"),
        )
        account = json.loads(candidate.member_bytes("source-accountability.json"))
        if account.get("source_sha256") != SOURCE_SHA or account.get("excluded") != [
            "Project Gutenberg header", "Project Gutenberg footer"
        ]:
            findings.append("candidate source accounting or wrapper disposition differs")
        if candidate.member_bytes("README.source.md") != manifest.authority_path("source-readme").read_bytes():
            findings.append("source attribution README differs")
        if manifest.record["validator"]["import_closure_sha256"] != _closure_sha():
            findings.append("oracle import closure differs")
    except (OSError, ValueError, KeyError, TypeError, etree.XMLSyntaxError, json.JSONDecodeError) as exc:
        findings.append(str(exc))
    result: dict[str, object] = {
        "status": "pass" if not findings else "fail", "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": _closure_sha(),
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": manifest.sha256, "candidate_sha256": candidate.sha256,
        **_validation_authority_bindings(manifest), "findings": sorted(findings),
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
