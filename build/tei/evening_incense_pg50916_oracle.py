"""Independent retained-HTML accounting for the PG50916 candidate."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
import inspect
import json
from pathlib import Path
import platform
import sys
from typing import Mapping
from zipfile import ZipFile

from lxml import etree, html

from ocd_kernel.reconstruction.contract import (
    CandidatePackage, SourceManifest, _validation_authority_bindings,
)


ORACLE_ID = "ocd-evening-incense-pg50916-independent-html-oracle"
ORACLE_VERSION = "1"
TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
SOURCE = "raw/gutenberg/50916/html/pg50916-images.html"
SOURCE_SHA = "621b8c4c06f315fe19ac05ae267a281a814f3d8240e6968d7162f0694d35264b"
TAG_MAP = {
    "header": "div", "footer": "div", "div": "div", "blockquote": "div",
    "ul": "list", "li": "item", "table": "table", "tr": "row",
    "td": "cell", "th": "cell", "h1": "head", "h2": "head",
    "p": "p", "i": "hi", "strong": "hi", "small": "hi", "span": "seg",
    "br": "lb", "hr": "milestone",
}
EXPECTED_TAGS = {
    "p": 297, "span": 168, "a": 133, "br": 104, "td": 96,
    "div": 81, "i": 66, "h2": 35, "hr": 33, "tr": 32,
    "strong": 6, "small": 5, "li": 4, "header": 1, "h1": 1,
    "table": 1, "tbody": 1, "footer": 1, "ul": 1,
    "blockquote": 1,
}


def _sha(value: bytes) -> str:
    return sha256(value).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def _closure_sha() -> str:
    contract = Path(inspect.getsourcefile(SourceManifest)).resolve(strict=True)
    return _sha(_canonical({"oracle": _sha(Path(__file__).read_bytes()),
                            "reconstruction-contract": _sha(contract.read_bytes())}))


def _expected_tag(node: etree._Element) -> str:
    if node.tag == "div":
        classes = (node.get("class") or "").split()
        if "verse" in classes:
            return "l"
    if node.tag == "a":
        if node.get("href"):
            return "ref"
        return "anchor" if not "".join(node.itertext()).strip() else "seg"
    return TAG_MAP[node.tag]


def _oracle(manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    findings: list[str] = []
    try:
        source = manifest.authority_path("retained-source").read_bytes()
        member = manifest.record["source_members"]
        if (len(member) != 1 or member[0]["path"] != SOURCE or
                member[0]["bytes"] != len(source) or member[0]["sha256"] != _sha(source) or
                len(source) != 151518 or _sha(source) != SOURCE_SHA):
            findings.append("extracted HTML source boundary differs")
        document = html.document_fromstring(source)
        body = document.find("body")
        if body is None:
            raise ValueError("retained HTML has no body")
        nodes = list(body.iterdescendants())
        if len(body) != 366 or len(nodes) != 1067 or Counter(n.tag for n in nodes) != EXPECTED_TAGS:
            findings.append("complete source body carrier census differs")
        if any(n.tag not in TAG_MAP and n.tag not in {"a", "tbody"} for n in nodes):
            findings.append("unmodeled source HTML carrier")
        headings = ["".join(n.itertext()).strip() for n in nodes if n.tag == "h2"]
        if (len(headings) != 35 or
                sum("EVENING." in title and title != "Table of Contents" for title in headings) != 31 or
                sum(n.tag == "div" and "verse" in (n.get("class") or "").split() for n in nodes) != 12 or
                sum("pagenum" in (n.get("class") or "").split() for n in nodes) != 97):
            findings.append("evening, verse, or page boundary differs")
        source_ids = [n.get("id") for n in nodes if n.get("id")]
        if len(source_ids) != 112 or len(set(source_ids)) != 112:
            findings.append("source HTML identifier census differs")
        fragment_links = [n.get("href")[1:] for n in nodes if n.tag == "a" and (n.get("href") or "").startswith("#")]
        if len(fragment_links) != 31 or not set(fragment_links).issubset(source_ids):
            findings.append("source HTML fragment link closure differs")
        with ZipFile(manifest.authority_path("retained-package")) as package:
            if (package.namelist() != ["pg50916-images.html", "images/cover.jpg"] or
                    package.read("pg50916-images.html") != source or
                    package.read("images/cover.jpg") != manifest.authority_path("retained-cover").read_bytes()):
                findings.append("retained ZIP members differ from extracted files")

        identifiers: dict[etree._Element, str] = {}
        crosswalk = []
        for ordinal, node in enumerate(nodes, 1):
            identifier = node.get("id") or f"src-{ordinal:05d}"
            identifiers[node] = identifier
            crosswalk.append({
                "tei_id": None if node.tag == "tbody" else identifier,
                "source_tag": node.tag, "parent": identifiers.get(node.getparent(), "body"),
                "attributes": dict(sorted(node.attrib.items())),
                "text_sha256": _sha((node.text or "").encode("utf-8")),
                "tail_sha256": _sha((node.tail or "").encode("utf-8")),
                "subtree_text_sha256": _sha("".join(node.itertext()).encode("utf-8")),
                "disposition": "flattened-table-wrapper" if node.tag == "tbody" else "represented",
            })
        expected_account = {
            "contract": "ocd-evening-incense-pg50916-accountability-v1",
            "work_id": "evening-incense-macduff", "source_path": SOURCE,
            "source_sha256": _sha(source), "source_bytes": len(source),
            "top_level_elements": len(body), "body_elements": len(nodes),
            "represented_elements": len(nodes) - 1, "flattened_wrappers": 1,
            "omitted_elements": 0,
            "body_text_sha256": _sha("".join(body.itertext()).encode("utf-8")),
            "crosswalk": crosswalk,
        }
        if json.loads(candidate.member_bytes("source-accountability.json")) != expected_account:
            findings.append("source accountability differs from independent HTML traversal")

        root = etree.fromstring(candidate.member_bytes("content.tei.xml"),
                                etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True))
        xsd = etree.XMLSchema(etree.parse(str(manifest.authority_path("tei-p5-xsd"))))
        if not xsd.validate(root):
            findings.extend(str(error) for error in xsd.error_log)
        envelope = root.xpath("./t:text/t:body/t:div[@type='complete-html-body']", namespaces={"t": TEI})
        if len(envelope) != 1 or len(root.xpath("./t:text/t:body/*", namespaces={"t": TEI})) != 1:
            findings.append("complete-body TEI envelope differs")
        else:
            envelope = envelope[0]
            source_identifier_set = set(identifiers.values())
            mapped = [n for n in envelope.iterdescendants() if n.get(XML_ID) in source_identifier_set]
            if len(mapped) != 1066 or "".join(envelope.itertext()) != "".join(body.itertext()):
                findings.append("TEI mapped carrier or complete body text differs")
            for source_node, tei_node in zip((n for n in nodes if n.tag != "tbody"), mapped):
                identifier = identifiers[source_node]
                if (tei_node.get(XML_ID) != identifier or
                        tei_node.tag != f"{{{TEI}}}{_expected_tag(source_node)}" or
                        "".join(tei_node.itertext()) != "".join(source_node.itertext())):
                    findings.append(f"TEI tag, identity, or subtree text differs at {identifier}")
                    break
                if source_node.tag == "a" and source_node.get("href") and tei_node.get("target") != source_node.get("href"):
                    findings.append(f"TEI link target differs at {identifier}")
                    break
                rendition = (["italic"] if source_node.tag == "i" else
                             ["bold"] if source_node.tag == "strong" else
                             ["small"] if source_node.tag == "small" else [])
                rendition.extend(value for value in (source_node.get("class"), source_node.get("style")) if value)
                if tei_node.get("rend") != ("; ".join(rendition) if rendition else None):
                    findings.append(f"TEI source rendition differs at {identifier}")
                    break
                source_parent = source_node.getparent()
                if source_parent.tag == "tbody":
                    source_parent = source_parent.getparent()
                mapped_parent = next((a for a in tei_node.iterancestors()
                                      if a is not envelope and a.get(XML_ID) in source_identifier_set), None)
                expected_parent = None if source_parent is body else identifiers[source_parent]
                if (mapped_parent.get(XML_ID) if mapped_parent is not None else None) != expected_parent:
                    findings.append(f"TEI hierarchy differs at {identifier}")
                    break
            if len(set(identifiers.values())) != 1067:
                findings.append("source-to-TEI IDs collide")
            tei_ids = {n.get(XML_ID) for n in envelope.iterdescendants() if n.get(XML_ID)}
            if not set(source_ids).issubset(tei_ids):
                findings.append("source identifier closure missing in TEI")
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
