"""Independent retained-HTML accounting for the complete PG63579 Nancy Prince book."""

from __future__ import annotations

from collections import Counter
from html.parser import HTMLParser
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


ORACLE_ID = "ocd-nancy-prince-pg63579-independent-html-oracle"
ORACLE_VERSION = "2"
TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
SOURCE = "raw/gutenberg/63579/html/pg63579-images.html"
SOURCE_SHA = "94b5050708e3a11818ab0154e3f18999239b3752a4aa042e07986ca6088b8931"
TAG_MAP = {
    "header": "div", "footer": "div", "div": "div", "blockquote": "div",
    "ul": "list", "li": "item", "table": "table", "tr": "row",
    "td": "cell", "th": "cell", "h1": "head", "h2": "head", "h3": "head",
    "h4": "head", "h5": "head", "h6": "head",
    "pre": "ab", "p": "p", "i": "hi", "strong": "hi", "b": "hi", "sup": "hi",
    "small": "hi", "span": "seg", "img": "figure",
    "br": "lb", "hr": "milestone",
}
EXPECTED_TAGS = {"div":134,"a":110,"p":92,"span":91,"td":28,"br":22,"i":16,"tr":14,"hr":10,"strong":6,"h3":6,"h2":5,"li":4,"img":2,"header":1,"h1":1,"table":1,"tbody":1,"footer":1,"blockquote":1,"ul":1}


def _sha(value: bytes) -> str:
    return sha256(value).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def _closure_sha() -> str:
    contract = Path(inspect.getsourcefile(SourceManifest)).resolve(strict=True)
    return _sha(_canonical({"oracle": _sha(Path(__file__).read_bytes()),
                            "reconstruction-contract": _sha(contract.read_bytes())}))


def _expected_tag(node: etree._Element) -> str:
    if node.tag == "div" and any(ancestor.tag in {"td", "th"} for ancestor in node.iterancestors()):
        return "seg"
    if node.tag == "div":
        classes = (node.get("class") or "").split()
        if node.getparent().get("class") == "stanza":
            return "l"
        if "poem" in classes or "stanza" in classes:
            return "lg"
        if "footnote" in classes:
            return "note"
        if any(ancestor.get("class") == "footnote" for ancestor in node.iterancestors()):
            return "quote"
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
                len(source) != 145052 or _sha(source) != SOURCE_SHA):
            findings.append("extracted HTML source boundary differs")
        class Census(HTMLParser):
            def __init__(self):
                super().__init__(convert_charrefs=True)
                self.inside = False
                self.counts = Counter()
                self.stack = []
                self.records = []
                self.text = []
            def handle_starttag(self, tag, attrs):
                if tag == "body": self.inside = True
                elif self.inside:
                    self.counts[tag] += 1
                    position = len(self.records) + 1
                    self.records.append((tag, dict(attrs), self.stack[-1][1] if self.stack else 0))
                    if tag not in {"br", "hr", "img"}:
                        self.stack.append((tag, position))
            def handle_endtag(self, tag):
                if tag == "body": self.inside = False
                elif self.inside:
                    if not self.stack or self.stack[-1][0] != tag:
                        raise ValueError("lexical source HTML nesting differs")
                    self.stack.pop()
            def handle_data(self, data):
                if self.inside:
                    self.text.append(data)
        lexical = Census()
        lexical.feed(source.decode("utf-8"))
        if lexical.counts != EXPECTED_TAGS:
            findings.append("independent lexical HTMLParser source census differs")
        document = html.document_fromstring(source)
        body = document.find("body")
        if body is None:
            raise ValueError("retained HTML has no body")
        nodes = list(body.iterdescendants())
        source_positions = {node: position for position, node in enumerate(nodes, 1)}
        if lexical.records != [(node.tag, dict(node.attrib), source_positions.get(node.getparent(), 0)) for node in nodes]:
            findings.append("independent lexical source hierarchy/attributes differs")
        if "".join(lexical.text) != "".join(body.itertext()):
            findings.append("independent lexical decoded source text differs")
        if len(body) != 116 or len(nodes) != 547 or Counter(n.tag for n in nodes) != EXPECTED_TAGS:
            findings.append("complete source body carrier census differs")
        if any(n.tag not in TAG_MAP and n.tag not in {"a", "tbody"} for n in nodes):
            findings.append("unmodeled source HTML carrier")
        headings = ["".join(n.itertext()).strip() for n in nodes if n.tag in {"h1", "h2", "h3", "h4", "h5", "h6"}]
        image_sources = [n.get("src") for n in nodes if n.tag == "img"]
        if [value.replace("\r\n", "\n") for value in headings[1:4]] != ["A NARRATIVE OF THE LIFE AND TRAVELS, OF\n MRS. NANCY PRINCE.", "CONTENTS.", "NARRATIVE."] or "DIVINE CONTENTMENT." not in headings or image_sources != ["images/front.jpg", "images/title.jpg"]:
            findings.append("title, contents, narrative, appended devotional or illustration boundary differs")
        source_ids = [n.get("id") for n in nodes if n.get("id")]
        if len(source_ids) != len(set(source_ids)):
            findings.append("source HTML identifier census differs")
        source_id_set = set(source_ids)
        fragment_links = [n.get("href")[1:] for n in nodes if n.tag == "a" and (n.get("href") or "").startswith("#")]
        missing_fragment_targets = sorted(set(fragment_links) - source_id_set)
        if missing_fragment_targets:
            findings.append("source HTML fragment link closure differs")
        with ZipFile(manifest.authority_path("retained-package")) as package:
            expected_members = manifest.record["archive_members"]
            observed_names = [info.filename for info in package.infolist()]
            if observed_names != [item["path"] for item in expected_members]:
                findings.append("retained ZIP members differ from extracted files")
            for info, item in zip(package.infolist(), expected_members):
                payload = package.read(info.filename)
                extracted = manifest.authority_path(item["authority"])
                if (len(payload) != item["bytes"] or f"{info.CRC:08x}" != item["crc32"] or
                        _sha(payload) != item["sha256"] or extracted.read_bytes() != payload):
                    findings.append(f"retained ZIP member differs: {info.filename}")

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
            "contract": "ocd-nancy-prince-pg63579-accountability-v1",
            "work_id": "nancy-prince-narrative-life-travels",
            "edition_id": "nancy-prince-narrative-life-travels-gutenberg-electronic",
            "acquisition_id": "nancy-prince-narrative-life-travels-gutenberg-acquired",
            "source_path": SOURCE,
            "source_sha256": _sha(source),
            "source_bytes": len(source),
            "archive_sha256": _sha(manifest.authority_path("retained-package").read_bytes()),
            "archive_members": [
                {key: item[key] for key in ("path", "bytes", "crc32", "sha256", "extracted_path", "role")}
                for item in manifest.record["archive_members"]
            ],
            "top_level_elements": len(body),
            "body_elements": len(nodes),
            "represented_elements": sum(node.tag != "tbody" for node in nodes),
            "flattened_wrappers": sum(node.tag == "tbody" for node in nodes),
            "omitted_elements": 0,
            "body_text_sha256": _sha("".join(body.itertext()).encode("utf-8")),
            "body_image_references": [node.get("src") for node in nodes if node.tag == "img"],
            "crosswalk": crosswalk,
        }
        if json.loads(candidate.member_bytes("source-accountability.json")) != expected_account:
            findings.append("source accountability differs from independent HTML traversal")

        root = etree.fromstring(candidate.member_bytes("content.tei.xml"),
                                etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True))
        xsd = etree.XMLSchema(etree.parse(str(manifest.authority_path("tei-p5-xsd"))))
        if not xsd.validate(root):
            findings.extend(str(error) for error in xsd.error_log)
        envelope = root.xpath("./t:text/t:body", namespaces={"t": TEI})
        if len(envelope) != 1:
            findings.append("complete-body TEI envelope differs")
        else:
            envelope = envelope[0]
            if ([n.get(XML_ID) for n in envelope] != ["pg63579-front", "pg63579-narrative", "pg63579-divine-contentment", "pg63579-provider-footer"]
                    or [len(n) for n in envelope] != [22, 75, 18, 1]):
                findings.append("source-defined front/narrative/appendix/footer unit boundaries differ")
            source_identifier_set = set(identifiers.values())
            mapped = [n for n in envelope.iterdescendants() if n.get(XML_ID) in source_identifier_set]
            if len(mapped) != 546 or "".join(envelope.itertext()) != "".join(body.itertext()):
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
                if source_node.tag == "div" and _expected_tag(source_node) == "lg":
                    expected_type = "stanza" if "stanza" in (source_node.get("class") or "").split() else "poem"
                    if tei_node.get("type") != expected_type:
                        findings.append(f"TEI verse grouping differs at {identifier}")
                        break
                if _expected_tag(source_node) == "note" and tei_node.get("type") != "source-footnote":
                    findings.append(f"TEI footnote role differs at {identifier}")
                    break
                if source_node.tag == "hr" and tei_node.get("unit") != "source-horizontal-rule":
                    findings.append(f"TEI source rule differs at {identifier}")
                    break
                if source_node.tag == "img":
                    graphics = tei_node.xpath("./t:graphic", namespaces={"t": TEI})
                    if (len(graphics) != 1 or
                            graphics[0].get("url") != source_node.get("src") or
                            graphics[0].get("n") != "; ".join(f"{name}={source_node.get(name)}" for name in ("alt", "width", "height") if source_node.get(name))):
                        findings.append(f"TEI graphic source differs at {identifier}")
                        break
                if source_node.get("title") and tei_node.get("n") != source_node.get("title"):
                    findings.append(f"TEI source title attribute differs at {identifier}")
                    break
                if source_node.get("data-summary") and tei_node.get("n") != source_node.get("data-summary"):
                    findings.append(f"TEI source data-summary differs at {identifier}")
                    break
                if source_node.tag == "div" and source_node.get("role") == "figure":
                    if (tei_node.get("type") != "source-figure" or
                            tei_node.get("corresp") != "#" + source_node.get("aria-labelledby")):
                        findings.append(f"TEI figure-caption relationship differs at {identifier}")
                        break
                rendition = (["italic"] if source_node.tag == "i" else
                             ["bold"] if source_node.tag in {"strong", "b"} else
                             ["superscript"] if source_node.tag == "sup" else
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
            if len(set(identifiers.values())) != 547:
                findings.append("source-to-TEI IDs collide")
            tei_ids = {n.get(XML_ID) for n in envelope.iterdescendants() if n.get(XML_ID)}
            if not set(source_ids).issubset(tei_ids):
                findings.append("source identifier closure missing in TEI")
            title_stmt = root.xpath("./t:teiHeader/t:fileDesc/t:titleStmt/t:title", namespaces={"t": TEI})
            if len(root.xpath("self::t:TEI", namespaces={"t": TEI})) != 1 or len(title_stmt) != 1 or "Nancy Prince" not in "".join(title_stmt[0].itertext()):
                findings.append("single source-titled work identity differs")
            candidate_manifest = candidate.manifest
            if (manifest.record.get("work_id") != "nancy-prince-narrative-life-travels" or
                    manifest.record.get("edition_id") != "nancy-prince-narrative-life-travels-gutenberg-electronic" or
                    manifest.record.get("acquisition_id") != "nancy-prince-narrative-life-travels-gutenberg-acquired" or
                    candidate_manifest.get("status") != "nonaccepted"):
                findings.append("canonical work, edition, acquisition, or candidate status binding differs")
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
