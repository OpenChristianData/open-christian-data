"""Independent exact-HTML oracle for the current Old Elizabeth PG17826 route."""

from __future__ import annotations

import base64
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


ORACLE_ID = "ocd-old-elizabeth-pg17826-independent-extracted-html-oracle"
ORACLE_VERSION = "1"
TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
TAGS = {
    "header": "div", "footer": "div", "div": "div", "blockquote": "div", "ul": "div",
    "p": "p", "li": "p", "h1": "head", "h2": "head", "h3": "head", "h4": "head",
    "i": "hi", "strong": "hi", "span": "seg", "a": "ref", "br": "lb",
    "pre": "ab", "hr": "milestone", "img": "graphic",
}


def _sha(value: bytes) -> str:
    return sha256(value).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def _import_closure_sha256() -> str:
    contract = Path(inspect.getsourcefile(SourceManifest)).resolve(strict=True)
    return _sha(_canonical({"oracle": _sha(Path(__file__).read_bytes()),
                            "reconstruction-contract": _sha(contract.read_bytes())}))


def _oracle(manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    findings: list[str] = []
    try:
        source = manifest.authority_path("retained-source").read_bytes()
        source_member = manifest.record["source_members"][0]
        if (source_member["path"] != "raw/gutenberg/17826/html/pg17826-images.html"
                or len(source) != source_member["bytes"] or _sha(source) != source_member["sha256"]):
            findings.append("retained extracted HTML member differs")
        document = html.document_fromstring(source)
        body = document.find("body")
        if body is None or len(body) != 56:
            findings.append("complete HTML body boundary differs")
        source_nodes = list(body.iterdescendants())
        if len(source_nodes) != 186 or any(node.tag not in TAGS for node in source_nodes):
            findings.append("HTML source carrier census differs")
        source_headings = ["".join(node.itertext()).strip() for node in source_nodes
                           if node.tag in {"h1", "h2", "h3", "h4"}]
        if ("OLD ELIZABETH," not in source_headings or "COLOURED WOMAN." not in source_headings
                or "MEMOIR, &C." not in source_headings):
            findings.append("memoir title and constituent section boundary differs")
        image_path = manifest.authority_path("referenced-image")
        image = image_path.read_bytes()
        if len(image) != 27606 or _sha(image) != "338defe78365ba25b3cc15f4af5bd540fd2061f57ad81fe26254a68d4f601133":
            findings.append("referenced image bytes differ")
        images = [node for node in source_nodes if node.tag == "img"]
        if len(images) != 1 or images[0].get("src") != "images/image_01.jpg":
            findings.append("HTML referenced image boundary differs")
        archive = manifest.authority_path("retained-package")
        with ZipFile(archive) as package:
            members = package.namelist()
            if (len(members) != 3 or set(members) != {"pg17826-images.html", "images/image_01.jpg", "17826-cover.png"}
                    or package.read("pg17826-images.html") != source
                    or package.read("images/image_01.jpg") != image):
                findings.append("retained ZIP package differs from extracted authority")

        account = json.loads(candidate.member_bytes("source-accountability.json"))
        expected_records = []
        identifiers: dict[etree._Element, str] = {}
        for ordinal, node in enumerate(source_nodes, 1):
            identifier = f"src-{ordinal:05d}"
            identifiers[node] = identifier
            expected_records.append({
                "id": identifier, "tag": node.tag,
                "parent": identifiers.get(node.getparent(), "body"),
                "attributes": dict(sorted(node.attrib.items())),
                "text_sha256": _sha((node.text or "").encode("utf-8")),
                "tail_sha256": _sha((node.tail or "").encode("utf-8")),
                "subtree_text_sha256": _sha("".join(node.itertext()).encode("utf-8")),
            })
        expected_account = {
            "contract": "ocd-old-elizabeth-pg17826-current-accountability-v1",
            "work_id": "old-elizabeth-memoir",
            "source_path": source_member["path"], "source_sha256": _sha(source),
            "source_bytes": len(source), "top_level_elements": len(body),
            "represented_elements": len(source_nodes), "omitted_elements": 0,
            "body_text_sha256": _sha("".join(body.itertext()).encode("utf-8")),
            "referenced_image_path": "raw/gutenberg/17826/html/images/image_01.jpg",
            "referenced_image_sha256": _sha(image), "referenced_image_bytes": len(image),
            "crosswalk": expected_records,
        }
        if account != expected_account:
            findings.append("source accountability differs from independent HTML census")

        root = etree.fromstring(candidate.member_bytes("content.tei.xml"),
                                etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True))
        xsd = etree.XMLSchema(etree.parse(str(manifest.authority_path("tei-p5-xsd"))))
        if not xsd.validate(root):
            findings.extend(str(error) for error in xsd.error_log)
        namespaces = {"t": TEI}
        envelopes = root.xpath("./t:text/t:body/t:div[@type='complete-html-body']", namespaces=namespaces)
        if len(envelopes) != 1 or len(root.xpath("./t:text/t:body/*", namespaces=namespaces)) != 1:
            findings.append("TEI complete-body envelope differs")
        else:
            envelope = envelopes[0]
            mapped = [node for node in envelope.iterdescendants()
                      if (node.get(f"{{{XML}}}id") or "").startswith("src-")]
            if len(mapped) != len(source_nodes):
                findings.append("TEI mapped carrier count differs")
            if "".join(envelope.itertext()) != "".join(body.itertext()):
                findings.append("complete HTML body text differs from TEI")
            titles = root.xpath("./t:teiHeader/t:fileDesc/t:titleStmt/t:title/text()", namespaces=namespaces)
            authors = root.xpath("./t:teiHeader/t:fileDesc/t:titleStmt/t:author/text()", namespaces=namespaces)
            if titles != ["Memoir of Old Elizabeth, A Coloured Woman"] or authors != ["Old Elizabeth"]:
                findings.append("TEI title or source-attested creator differs")
            for ordinal, (source_node, tei_node) in enumerate(zip(source_nodes, mapped), 1):
                identifier = f"src-{ordinal:05d}"
                expected_tag = "seg" if source_node.tag == "a" and source_node.get("href") is None else TAGS[source_node.tag]
                if (tei_node.get(f"{{{XML}}}id") != identifier
                        or tei_node.tag != f"{{{TEI}}}{expected_tag}"
                        or "".join(tei_node.itertext()) != "".join(source_node.itertext())
                        or tei_node.get("n") != source_node.get("id")
                        or tei_node.get(f"{{{XML}}}lang") != source_node.get("lang")):
                    findings.append(f"TEI carrier fidelity differs at {identifier}")
                    break
                if source_node.tag == "a" and source_node.get("href") is not None and tei_node.get("target") != source_node.get("href"):
                    findings.append(f"HTML link target differs at {identifier}")
                    break
                if source_node.tag == "a" and source_node.get("href") is None and tei_node.get("type") != "page-anchor":
                    findings.append(f"HTML page anchor differs at {identifier}")
                    break
                if source_node.tag == "i" and tei_node.get("rend") != "italic":
                    findings.append(f"HTML emphasis differs at {identifier}")
                    break
                if source_node.tag == "strong" and tei_node.get("rend") != "bold":
                    findings.append(f"HTML strong emphasis differs at {identifier}")
                    break
                if source_node.tag == "img" and (tei_node.get("corresp") != source_node.get("src")
                        or tei_node.get("url") != "data:image/jpeg;base64," + base64.b64encode(image).decode("ascii")):
                    findings.append(f"HTML referenced image differs at {identifier}")
                    break
                if source_node.tag == "hr" and tei_node.get("unit") != "source-horizontal-rule":
                    findings.append(f"HTML horizontal rule differs at {identifier}")
                    break
                if source_node.tag == "pre" and (tei_node.get("type") != "source-block"
                        or tei_node.get("subtype") != "preformatted"):
                    findings.append(f"HTML preformatted block differs at {identifier}")
                    break
                source_parent = source_node.getparent()
                mapped_parent = next((ancestor for ancestor in tei_node.iterancestors()
                                      if (ancestor.get(f"{{{XML}}}id") or "").startswith("src-")), None)
                if source_parent is body:
                    if mapped_parent is not None:
                        findings.append(f"TEI parent differs at {identifier}")
                        break
                elif mapped_parent is None or mapped_parent.get(f"{{{XML}}}id") != identifiers[source_parent]:
                    findings.append(f"TEI parent differs at {identifier}")
                    break
        if candidate.member_bytes("README.source.md") != manifest.authority_path("source-readme").read_bytes():
            findings.append("source attribution README differs")
        if manifest.record["validator"]["import_closure_sha256"] != _import_closure_sha256():
            findings.append("oracle import closure differs")
    except (OSError, ValueError, KeyError, TypeError, etree.XMLSyntaxError, json.JSONDecodeError) as exc:
        findings.append(str(exc))

    result: dict[str, object] = {
        "status": "pass" if not findings else "fail", "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": _import_closure_sha256(),
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": manifest.sha256, "candidate_sha256": candidate.sha256,
        **_validation_authority_bindings(manifest), "findings": sorted(findings),
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
