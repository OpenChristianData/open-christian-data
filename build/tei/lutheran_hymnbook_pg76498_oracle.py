"""Independent token-based source oracle for the retained PG76498 hymn-book."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import platform
import re
import sys
from typing import Mapping
from zipfile import ZipFile

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest

TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
SOURCE = "raw/gutenberg/76498/pg76498-h.zip"
ARCHIVE_SHA = "37de1a88d36166c86377e7451ccaabd6e870259b3089c2eb01f2abbe3b67a2c5"
MEMBERS = (
    ("pg76498-images.html", 1700540, "c13e936c8b681c23ca402237581d9d9208ad0b8a34465315ea8c9138da5b6d3b"),
    ("images/cover.jpg", 126730, "eb9590ad6bf057918abea5131b785d777670e3a155a8980eca0946f328276799"),
    ("images/concordia.jpg", 3583, "089ff870cdf7c780fb50540f4b53da8aac0d8dcf47e188566f13b7b462002ad2"),
)
ORACLE_ID = "ocd-pg76498-lutheran-hymnbook-independent-html-token-oracle"
ORACLE_VERSION = "1"
CLOSURE = ("build/tei/lutheran_hymnbook_pg76498_oracle.py", "ocd_kernel/__init__.py",
           "ocd_kernel/reconstruction/__init__.py", "ocd_kernel/reconstruction/contract.py",
           "ocd_kernel/lib/storage_topology.py")


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _norm(value: str) -> str:
    return " ".join(value.split())


@dataclass(eq=False)
class Node:
    tag: str
    attrs: dict[str, str]
    parent: "Node | None"
    ordinal: int
    parts: list["Node | str"] = field(default_factory=list)

    def text(self, *, omit_page_labels: bool = False) -> str:
        if omit_page_labels and self.tag == "span" and "pagenum" in self.attrs.get("class", "").split():
            return ""
        return "".join(part if isinstance(part, str) else part.text(omit_page_labels=omit_page_labels)
                       for part in self.parts)


class Reader(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
            "param", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.body: Node | None = None
        self.stack: list[Node] = []
        self.nodes: list[Node] = []
        self.lang: str | None = None
        self.doctype: str | None = None
        self.body_comments: list[str] = []

    def handle_decl(self, decl: str) -> None:
        if self.doctype is not None:
            raise ValueError("duplicate source declaration")
        self.doctype = decl

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key: value or "" for key, value in attrs}
        if tag == "html":
            self.lang = attributes.get("lang")
            return
        if tag == "body":
            if self.body is not None:
                raise ValueError("duplicate body")
            self.body = Node(tag, attributes, None, 0)
            self.stack = [self.body]
            return
        if not self.stack:
            return
        parent = self.stack[-1]
        node = Node(tag, attributes, parent, len(self.nodes) + 1)
        parent.parts.append(node)
        self.nodes.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID and self.stack:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if not self.stack:
            return
        if self.stack[-1].tag != tag:
            raise ValueError(f"source HTML requires recovery at </{tag}> after <{self.stack[-1].tag}>")
        self.stack.pop()

    def handle_data(self, data: str) -> None:
        if self.stack:
            self.stack[-1].parts.append(data)

    def handle_comment(self, data: str) -> None:
        if self.stack:
            self.body_comments.append(data)


def _source(source_manifest: SourceManifest) -> tuple[Reader, list[dict[str, object]]]:
    path = resolve_repo_path(source_manifest.repository_root, SOURCE)
    if source_manifest.authority_path("retained-source") != path:
        raise ValueError("retained PG76498 source binding differs")
    raw = path.read_bytes()
    if len(raw) != 461780 or _sha(raw) != ARCHIVE_SHA:
        raise ValueError("retained PG76498 ZIP identity differs")
    rows: list[dict[str, object]] = []
    with ZipFile(path) as archive:
        infos = archive.infolist()
        if tuple(i.filename for i in infos) != tuple(n for n, _, _ in MEMBERS) or archive.testzip() is not None:
            raise ValueError("retained PG76498 archive member inventory or CRC differs")
        for info, (name, size, digest) in zip(infos, MEMBERS, strict=True):
            member = archive.read(info)
            if info.flag_bits & 1 or info.is_dir() or ".." in Path(name).parts or len(member) != size or _sha(member) != digest:
                raise ValueError(f"retained archive member differs: {name}")
            rows.append({"name": name, "bytes": size, "sha256": digest,
                         "crc32": f"{info.CRC:08x}",
                         "disposition": "complete HTML witness" if name.endswith(".html") else
                         ("cover/favicon support image; not visible in body" if "cover" in name else
                          "source-body concordia figure image")})
        html_bytes = archive.read("pg76498-images.html")
    text = html_bytes.decode("utf-8", errors="strict")
    if "\ufffd" in text or not text.startswith("<!DOCTYPE html>"):
        raise ValueError("source HTML encoding or doctype differs")
    reader = Reader()
    reader.feed(text)
    reader.close()
    if reader.body is None or reader.lang != "en" or reader.doctype != "DOCTYPE html" or reader.stack or reader.body_comments:
        raise ValueError("HTML shell, parser recovery, or body comment inventory differs")
    return reader, rows


def _source_text_fields(reader: Reader) -> tuple[list[str], list[str]]:
    own = [""] * (len(reader.nodes) + 1)
    tails = [""] * (len(reader.nodes) + 1)
    assert reader.body is not None
    for parent in [reader.body, *reader.nodes]:
        current: Node | None = None
        for part in parent.parts:
            if isinstance(part, Node):
                current = part
            elif current is None:
                if parent.ordinal:
                    own[parent.ordinal] += part
            else:
                tails[current.ordinal] += part
    return own, tails


def _carrier_tag(node: Node) -> str:
    tag = node.tag
    classes = set(node.attrs.get("class", "").split())
    if tag == "div" and "verse" in classes:
        return "l"
    if tag == "div" and "stanza" in classes:
        return "lg"
    if tag == "div" and "footnote" in classes:
        return "note"
    if tag == "span" and "pagenum" in classes:
        return "pb"
    if tag in {"div", "header", "footer", "blockquote", "h1", "h2", "h3", "h4", "table", "figure"}:
        return "div"
    values = {"p": "p", "ul": "list", "li": "item", "tbody": "table", "tr": "row",
              "td": "cell", "hr": "milestone", "a": "ref" if node.attrs.get("href") else "seg",
              "img": "graphic", "br": "lb", "span": "seg", "i": "hi", "b": "hi", "strong": "hi"}
    if tag not in values:
        raise ValueError(f"unmapped source tag {tag}")
    return values[tag]


def _carrier_id(node: Node) -> str:
    return node.attrs.get("id") or f"src-{node.ordinal:05d}"


def check(source_manifest: SourceManifest, tei_bytes: bytes, account_bytes: bytes) -> dict[str, int]:
    reader, members = _source(source_manifest)
    profile = json.loads(source_manifest.authority_path("reconstruction-profile").read_bytes())
    policy = json.loads(source_manifest.authority_path("validation-policy").read_bytes())
    own, tails = _source_text_fields(reader)
    expected = [{"carrier": f"src-{node.ordinal:05d}",
                 "parent": f"src-{node.parent.ordinal:05d}" if node.parent and node.parent.ordinal else "body",
                 "tag": node.tag, "attributes": dict(sorted(node.attrs.items())),
                 "own_text_sha256": _sha(own[node.ordinal].encode("utf-8")),
                 "tail_sha256": _sha(tails[node.ordinal].encode("utf-8"))}
                for node in reader.nodes]
    if profile.get("carriers") != expected or profile.get("carrier_count") != len(reader.nodes):
        raise ValueError("independent HTML token carrier inventory differs from profile")
    if profile.get("archive_members") != members or profile.get("body_comments") != reader.body_comments:
        raise ValueError("source archive, image, or comment inventory differs from profile")
    account = json.loads(account_bytes)
    if account.get("contract") != "ocd-lutheran-hymnbook-pg76498-accountability-v1" or account.get("archive_members") != members or account.get("source_archive_sha256") != ARCHIVE_SHA or account.get("source_profile_sha256") != _sha(source_manifest.authority_path("reconstruction-profile").read_bytes()) or account.get("tei_sha256") != _sha(tei_bytes):
        raise ValueError("source accountability binding differs")
    if any(account.get(key) != value for key, value in policy["accountability"].items()):
        raise ValueError("source accountability policy differs")
    tree = etree.fromstring(tei_bytes, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    if tree.tag != f"{{{TEI}}}TEI" or tree.get(XML_ID) != "lutheran-hymnbook-pg76498-candidate":
        raise ValueError("TEI root identity differs")
    ids = [node.get(XML_ID) for node in tree.iter() if isinstance(node.tag, str) and node.get(XML_ID)]
    counts = Counter(ids)
    if len(ids) != len(reader.nodes) + 1 or any(count != 1 for count in counts.values()):
        raise ValueError("TEI source carrier omission, invention, or duplicate ID")
    source_ids = {node.attrs["id"]: node for node in reader.nodes if node.attrs.get("id")}
    if len(source_ids) != 1286 or any(value.startswith("src-") or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", value)
                                       for value in source_ids):
        raise ValueError("source ID set differs or collides with generated carriers")
    source_refs = [node.attrs["href"][1:] for node in reader.nodes if node.tag == "a" and node.attrs.get("href", "").startswith("#")]
    if len(source_refs) != 1445 or any(value not in source_ids for value in source_refs):
        raise ValueError("source internal fragment target absent")
    actual_refs = [node.get("target")[1:] for node in tree.iter()
                   if isinstance(node.tag, str) and etree.QName(node).localname == "ref" and node.get("target", "").startswith("#")]
    elements = {node.get(XML_ID): node for node in tree.iter() if isinstance(node.tag, str) and node.get(XML_ID)}
    for target in actual_refs:
        if counts.get(target) != 1:
            raise ValueError("unresolved or nonunique TEI internal link target")
        intended = source_ids.get(target)
        if intended is None:
            raise ValueError("TEI fragment target has no source ID")
        actual = elements[target]
        if etree.QName(actual).localname != _carrier_tag(intended):
            raise ValueError("TEI fragment target resolves to wrong source carrier")
        if actual.get("n") != (target if _carrier_tag(intended) != "pb" else re.search(r"\d+", intended.text()).group()):
            raise ValueError("TEI fragment target has wrong source-page or anchor identity")
    if actual_refs != source_refs:
        raise ValueError("TEI internal link sequence differs from source")
    actual_order = [value for value in ids if value != "lutheran-hymnbook-pg76498-candidate"]
    expected_order = [_carrier_id(node) for node in reader.nodes]
    if actual_order != expected_order:
        raise ValueError("TEI source carrier order differs")
    source_keys = set(expected_order)
    for node in reader.nodes:
        carrier = elements[_carrier_id(node)]
        if etree.QName(carrier).localname != _carrier_tag(node):
            raise ValueError(f"source carrier tag differs: {_carrier_id(node)}")
        parent = carrier.getparent()
        while parent is not None and parent.get(XML_ID) not in source_keys:
            parent = parent.getparent()
        expected_parent = _carrier_id(node.parent) if node.parent and node.parent.ordinal else None
        if (parent.get(XML_ID) if parent is not None else None) != expected_parent:
            raise ValueError(f"source carrier parent attachment differs: {_carrier_id(node)}")
        if _norm("".join(carrier.itertext())) != _norm(node.text(omit_page_labels=True)):
            raise ValueError(f"source carrier wording differs: {_carrier_id(node)}")
        classes = node.attrs.get("class", "").split()
        if any(f"class:{name}" not in carrier.get("rend", "").split() for name in classes):
            raise ValueError(f"source class/rendition differs: {_carrier_id(node)}")
        if node.attrs.get("id") and _carrier_tag(node) != "pb" and carrier.get("n") != node.attrs["id"]:
            raise ValueError(f"source anchor ID differs: {_carrier_id(node)}")
        if node.tag == "span" and "pagenum" in classes:
            label = node.text()
            match = re.fullmatch(r"\[(\d+)\]", label)
            if match is None or carrier.get("n") != match.group(1) or f"source-label:{label}" not in carrier.get("rend", ""):
                raise ValueError(f"source page label differs: {_carrier_id(node)}")
        if node.tag == "div" and "stanza" in classes and carrier.get("type") != "stanza":
            raise ValueError("stanza grouping differs")
        if node.tag in {"h1", "h2", "h3", "h4"}:
            if carrier.get("type") != "source-heading" or carrier.get("subtype") != f"html-heading-level-{node.tag[1:]}" or carrier.find(f"{{{TEI}}}head") is None:
                raise ValueError("source heading level or ownership differs")
        if node.tag == "a" and node.attrs.get("href") and carrier.get("target") != node.attrs["href"]:
            raise ValueError("source href differs")
        if node.tag == "img" and carrier.get("url") != node.attrs.get("src"):
            raise ValueError("source image reference differs")
    source_hymns = [node for node in reader.nodes if re.fullmatch(r"hymn_\d+", node.attrs.get("id", ""))]
    if [int(node.attrs["id"].split("_")[1]) for node in source_hymns] != list(range(1, 595)):
        raise ValueError("source hymn number sequence differs")
    actual_hymns = tree.xpath(".//tei:div[@type='hymn']", namespaces={"tei": TEI})
    if [node.get("n") for node in actual_hymns] != [str(i) for i in range(1, 595)]:
        raise ValueError("TEI hymn numbering or grouping differs")
    for number, source_node in enumerate(source_hymns, 1):
        carrier = elements[_carrier_id(source_node)]
        owners = [item for item in carrier.iterancestors() if item.get("type") == "hymn"]
        if len(owners) != 1 or owners[0].get("n") != str(number):
            raise ValueError("source hymn heading assigned to wrong hymn")
    if len(tree.findall(f".//{{{TEI}}}lg")) != 3270 or len(tree.findall(f".//{{{TEI}}}l")) != 17412 or len(tree.findall(f".//{{{TEI}}}pb")) != 592:
        raise ValueError("stanza, verse, or page milestone inventory differs")
    if len(tree.findall(f".//{{{TEI}}}note")) != 4 or len(tree.findall(f".//{{{TEI}}}table")) != 1 or len(tree.findall(f".//{{{TEI}}}graphic")) != 1:
        raise ValueError("note, contents table, or concordia figure inventory differs")
    if len(tree.xpath(".//tei:div[@type='source-section']", namespaces={"tei": TEI})) != 53:
        raise ValueError("source section boundary count differs")
    assert reader.body is not None
    content = tree.xpath(".//tei:div[@type='source-html-body']", namespaces={"tei": TEI})
    if len(content) != 1 or _norm("".join(content[0].itertext())) != _norm(reader.body.text(omit_page_labels=True)):
        raise ValueError("complete source-body wording differs")
    return {"html_carriers": len(reader.nodes), "hymns": len(source_hymns),
            "stanzas": 3270, "verse_lines": 17412, "pages": 592,
            "source_ids": len(source_ids), "internal_refs": len(source_refs),
            "distinct_internal_targets": len(set(source_refs))}


def import_closure_sha256(root: Path) -> str:
    return _sha(_json([{"path": name, "sha256": _sha((root / name).read_bytes())} for name in CLOSURE]))


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    checks = check(source_manifest, candidate.member_bytes("content.tei.xml"), candidate.member_bytes("source-accountability.json"))
    if candidate.manifest.get("status") != "nonaccepted" or candidate.manifest.get("source_id") != source_manifest.record["source_id"]:
        raise ValueError("candidate status or source identity differs")
    schema = etree.XMLSchema(etree.parse(str(source_manifest.authority_path("tei-p5-xsd"))))
    tree = etree.fromstring(candidate.member_bytes("content.tei.xml"), etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    if not schema.validate(tree):
        raise ValueError(f"TEI P5 XSD failure: {schema.error_log.last_error}")
    policy = json.loads(source_manifest.authority_path("validation-policy").read_bytes())
    if candidate.member_bytes("README.source.md") != source_manifest.authority_path("source-local-attribution-readme").read_bytes():
        raise ValueError("source README attribution bytes differ")
    if candidate.member_bytes("provenance.json") != _json(policy["provenance"]):
        raise ValueError("candidate provenance differs from policy")
    if candidate.member_bytes("unresolved.jsonl") != b"".join(_json(row) for row in policy["unresolved"]):
        raise ValueError("candidate unresolved ledger differs from policy")
    bindings = {item["role"]: item for item in source_manifest.record["authorities"]}
    result: dict[str, object] = {
        "status": "pass", "oracle_id": ORACLE_ID, "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": import_closure_sha256(source_manifest.repository_root),
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source_manifest.sha256, "candidate_sha256": candidate.sha256,
        "profile_sha256": bindings["complete-source-feature-profile"]["sha256"],
        "package_schema_sha256": bindings["candidate-package-schema"]["sha256"],
        "source_sha256": bindings["primary-source"]["sha256"],
        "xsd_sha256": bindings["tei-validation-schema"]["sha256"],
        "policy_sha256": bindings["independent-validation-policy"]["sha256"],
        "findings": [],
    }
    result["result_sha256"] = _sha(_json(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
