"""Independent source/TEI checks for the complete retained PG36264 witness.

Does not import or execute the converter. HTMLParser independently checks the
literal token census; lxml observes source and candidate structure/text.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
from html.parser import HTMLParser
import inspect
import json
from pathlib import Path
import platform
import sys
from urllib.parse import quote
from zipfile import ZipFile

from lxml import etree, html
from ocd_kernel.reconstruction.contract import SourceManifest, _validation_authority_bindings

ORACLE_ID = "ocd-robertson-pg36264-independent-html-oracle"
ORACLE_VERSION = "1"
TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
SOURCE_SHA = "105aac29a024f9771c1f8fe4917e668eabe5d2abe39c1afcbd67e91960a20418"
TAGS = {"pre": "ab", "table": "table", "tr": "row", "td": "cell", "img": "graphic", "br": "lb",
        "h1": "ab", "h2": "ab", "h3": "ab", "h4": "ab", "center": "ab", "div": "ab",
        "p": "p", "blockquote": "quote", "big": "hi", "i": "hi", "b": "hi", "small": "hi", "sup": "hi", "a": "ref"}
EXPECTED_TAGS = {"pre": 2, "table": 137, "tr": 1317, "td": 3852, "img": 2, "br": 21233,
                 "h1": 1, "center": 185, "big": 1, "i": 2001, "b": 57, "h3": 27,
                 "small": 9354, "a": 1851, "p": 606, "div": 1, "h4": 189, "h2": 1,
                 "sup": 2454, "blockquote": 905}


def _sha(value):
    return sha256(value).hexdigest()


def _canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _closure_sha():
    return _sha(_canonical({"oracle": _sha(Path(__file__).read_bytes()),
                            "reconstruction-contract": _sha(Path(inspect.getsourcefile(SourceManifest)).read_bytes())}))


class LiteralCensus(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_body = False
        self.tags = Counter()
        self.attributes = []

    def handle_starttag(self, tag, attrs):
        if tag == "body":
            self.in_body = True
        elif self.in_body:
            self.tags[tag] += 1
            self.attributes.append((tag, dict(attrs)))

    def handle_endtag(self, tag):
        if tag == "body":
            self.in_body = False


def _oracle(manifest, candidate):
    findings = []
    try:
        source = manifest.authority_path("retained-source").read_bytes()
        if len(source) != 1308053 or _sha(source) != SOURCE_SHA:
            raise ValueError("retained PG36264 HTML differs")
        literal = LiteralCensus()
        literal.feed(source.decode("iso-8859-1"))
        if literal.tags != EXPECTED_TAGS:
            findings.append("independent literal HTML token census differs")
        body = html.document_fromstring(source, parser=html.HTMLParser(encoding="iso-8859-1")).find("body")
        nodes = list(body.iterdescendants())
        if (len(body) != 3974 or len(nodes) != 44176 or
                Counter(n.tag for n in nodes) != EXPECTED_TAGS or
                literal.attributes != [(n.tag, dict(n.attrib)) for n in nodes]):
            findings.append("source HTML parser structure/attribute census differs")
        with ZipFile(manifest.authority_path("retained-package")) as package:
            expected = {"36264-h/36264-h.htm": source,
                        "36264-h/images/1.jpg": manifest.authority_path("retained-map").read_bytes(),
                        "36264-h/images/2.jpg": manifest.authority_path("retained-logo").read_bytes()}
            if {n for n in package.namelist() if not n.endswith("/")} != set(expected):
                findings.append("ZIP complete member census differs")
            for name, content in expected.items():
                if package.read(name) != content:
                    findings.append("ZIP extraction differs: " + name)
        root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
        xsd = etree.XMLSchema(etree.parse(str(manifest.authority_path("tei-p5-xsd"))))
        if not xsd.validate(root):
            findings.extend(str(e) for e in xsd.error_log)
        envelope = root.find(f"{{{TEI}}}text/{{{TEI}}}body/{{{TEI}}}div")
        if envelope is None:
            raise ValueError("complete-body envelope missing")
        mapped = [n for n in envelope.iterdescendants() if n.get(XML_ID)]
        if len(mapped) != len(nodes) or "".join(envelope.itertext()) != "".join(body.itertext()):
            findings.append("complete body node/text correspondence differs")
        ids = {n: n.get("name") or f"src-{i:05d}" for i, n in enumerate(nodes, 1)}
        by_id = {n.get(XML_ID): n for n in mapped}
        if len(by_id) != len(nodes):
            findings.append("source identifiers collide")
        active_group = None
        boundaries = []
        for source_node, target in zip(nodes, mapped):
            ident = ids[source_node]
            expected_tag = "anchor" if source_node.tag == "a" and not source_node.get("href") else TAGS[source_node.tag]
            if (target.get(XML_ID) != ident or target.tag != f"{{{TEI}}}{expected_tag}" or
                    target.text != source_node.text or
                    "".join(target.itertext()) != "".join(source_node.itertext())):
                raise ValueError("source tag/text/order differs at " + ident)
            annotation = "urn:ocd:pg36264:html:" + quote(_canonical({"tag": source_node.tag, "attributes": dict(source_node.attrib)}).decode().strip(), safe="")
            annotation_key = "rend" if expected_tag == "anchor" else "ana"
            if target.get(annotation_key) != annotation:
                raise ValueError("source literal attribute disposition differs at " + ident)
            attributes = {XML_ID: ident, annotation_key: annotation}
            if source_node.tag in {"h1", "h2", "h3", "h4"}:
                attributes["type"] = "source-" + source_node.tag
            elif expected_tag == "ab":
                attributes["type"] = "source-pre" if source_node.tag == "pre" else "source-block"
            if expected_tag == "table":
                attributes["n"] = source_node.get("summary")
            if expected_tag == "cell":
                attributes.update({new: source_node.get(old) for old, new in (("colspan", "cols"), ("rowspan", "rows")) if source_node.get(old)})
            if expected_tag == "ref":
                attributes["target"] = source_node.get("href")
            if expected_tag == "graphic":
                attributes.update(url=source_node.get("src"), n="source-alt:" + source_node.get("alt"))
            if expected_tag == "hi":
                attributes["rend"] = {"i":"italic","b":"bold","small":"small","big":"large","sup":"superscript"}[source_node.tag]
            if source_node.get("align") and expected_tag != "row":
                attributes["rend"] = "source-align:" + source_node.get("align")
            if dict(target.attrib) != attributes or [n.get(XML_ID) for n in target] != [ids[n] for n in source_node]:
                raise ValueError("source child structure or TEI attributes differ at " + ident)
            ancestor = next((n for n in target.iterancestors() if n.get(XML_ID)), None)
            parent = source_node.getparent()
            if (ancestor.get(XML_ID) if ancestor is not None else None) != (ids[parent] if parent is not body else None):
                raise ValueError("source parent/cell ownership differs at " + ident)
            if parent is not body and target.tail != source_node.tail:
                raise ValueError("inline source tail differs at " + ident)
            if parent is body:
                carrier = target.getparent() if target.getparent().tag == f"{{{TEI}}}ab" else target
                if (source_node.tail or "").strip():
                    following = carrier.getnext()
                    if (carrier.tail is not None or following is None or following.tag != f"{{{TEI}}}ab"
                            or following.get("type") != "source-block" or following.text != source_node.tail):
                        raise ValueError("inter-block source text differs at " + ident)
                elif carrier.tail != source_node.tail:
                    raise ValueError("inter-block source whitespace differs at " + ident)
            if source_node.get("name") and parent is body:
                active_group = source_node.get("name")
                boundaries.append(active_group)
            group = next((n.get("n") for n in target.iterancestors() if n.tag == f"{{{TEI}}}div" and n.get("n")), None)
            if group != active_group:
                raise ValueError("section/part/note ownership differs at " + ident)
            for source_attr, target_attr in (("href", "target"), ("colspan", "cols"), ("rowspan", "rows"), ("src", "url")):
                if source_node.get(source_attr) != target.get(target_attr):
                    raise ValueError("link, table span, or image target differs at " + ident)
            if source_node.tag == "table" and target.get("n") != source_node.get("summary"):
                raise ValueError("table identity differs at " + ident)
            if source_node.tag.startswith("h") and source_node.tag[1:].isdigit() and target.get("type") != "source-" + source_node.tag:
                raise ValueError("heading role differs at " + ident)
            if source_node.tag in {"i", "b", "small", "big", "sup"} and target.get("rend") != {"i":"italic","b":"bold","small":"small","big":"large","sup":"superscript"}[source_node.tag]:
                raise ValueError("emphasis/superscript role differs at " + ident)
            if source_node.tag == "img" and target.get("n") != "source-alt:" + source_node.get("alt"):
                raise ValueError("image alternative text differs at " + ident)
        source_names = {n.get("name") for n in nodes if n.get("name")}
        links = [n.get("href") for n in nodes if n.get("href")]
        if len(source_names) != 244 or len(links) != 1607 or any(not x.startswith("#") or x[1:] not in source_names for x in links):
            findings.append("complete fragment-link closure differs")
        account = json.loads(candidate.member_bytes("source-accountability.json"))
        if (account["body_elements"] != len(nodes) or account["omitted_elements"] != 0 or
                account["tags"] != EXPECTED_TAGS or account["source_boundaries"] != boundaries or
                account["body_text_sha256"] != _sha("".join(body.itertext()).encode())):
            findings.append("source accountability summary differs")
        if candidate.member_bytes("README.source.md") != manifest.authority_path("source-readme").read_bytes():
            findings.append("source README differs")
    except (OSError, ValueError, KeyError, TypeError, etree.XMLSyntaxError, json.JSONDecodeError) as exc:
        findings.append(str(exc))
    result = dict(status="pass" if not findings else "fail", oracle_id=ORACLE_ID, oracle_version=ORACLE_VERSION,
                  implementation_sha256=_sha(Path(__file__).read_bytes()), import_closure_sha256=_closure_sha(),
                  runtime=f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
                  source_manifest_sha256=manifest.sha256, candidate_sha256=candidate.sha256,
                  **_validation_authority_bindings(manifest), findings=sorted(findings))
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
