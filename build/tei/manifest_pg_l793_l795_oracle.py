"""Independent source and candidate oracle for retained PG L793-L795 witnesses."""

from __future__ import annotations

import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
from zipfile import ZipFile

from lxml import etree, html

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts
from ocd_kernel.tei.validate import compiled_schema


TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
ORACLE_ID = "ocd-manifest-pg-l793-l795-independent-oracle"
ORACLE_VERSION = "1"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _closure(root: Path) -> str:
    paths = (
        "build/tei/manifest_pg_l793_l795_oracle.py",
        "ocd_kernel/reconstruction/contract.py",
        "ocd_kernel/reconstruction/verifier.py",
        "ocd_kernel/tei/validate.py",
    )
    return _sha(_canonical([{"path": name, "sha256": _sha((root / name).read_bytes())} for name in paths]))


class _BodyText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_body = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "body":
            self.in_body = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "body":
            self.in_body = False

    def handle_data(self, data: str) -> None:
        if self.in_body:
            self.parts.append(data)


def _source(manifest: SourceManifest, profile: dict[str, object]) -> tuple[etree._Element, list[dict[str, object]], str]:
    archive_path = manifest.authority_path("retained-archive")
    receipt = json.loads(manifest.authority_path("acquisition-receipt").read_text(encoding="utf-8"))
    if _sha(archive_path.read_bytes()) != profile["archive_sha256"] or receipt["package"]["sha256"] != profile["archive_sha256"]:
        raise ValueError("source archive/receipt identity failure")
    with ZipFile(archive_path) as archive:
        if archive.testzip() is not None:
            raise ValueError("source archive CRC failure")
        members = [
            {"path": item.filename, "bytes": item.file_size, "crc32": f"{item.CRC:08x}", "sha256": _sha(archive.read(item))}
            for item in archive.infolist() if not item.is_dir()
        ]
        if members != profile["archive_members"]:
            raise ValueError("source archive member inventory mismatch")
        data = archive.read(str(profile["html_member"]))
    if _sha(data) != profile["html_sha256"] or receipt["html"]["sha256"] != profile["html_sha256"]:
        raise ValueError("HTML member/receipt identity failure")
    if data != manifest.authority_path("extracted-html").read_bytes():
        raise ValueError("extracted HTML source mismatch")
    text = data.decode("utf-8", errors="strict")
    alternate = _BodyText()
    alternate.feed(text)
    body = html.fromstring(text).find(".//body")
    if body is None or len(body) != profile["body_direct_children"]:
        raise ValueError("source body child count mismatch")
    body_text = "".join(body.itertext())
    if "".join(alternate.parts) != body_text or _sha(body_text.encode("utf-8")) != profile["body_text_sha256"]:
        raise ValueError("independent HTML text reader disagrees with source profile")
    return body, members, body_text


def _tag_name(node: etree._Element) -> str:
    return etree.QName(node).localname


def _compare_sequence(
    sources: list[etree._Element],
    targets: list[etree._Element],
    paths: list[str],
    *,
    strict: bool,
) -> int:
    position = 0
    for source, path in zip(sources, paths, strict=True):
        tag = source.tag.lower() if isinstance(source.tag, str) else ""
        if tag in {"tbody", "thead", "tfoot", "colgroup", "col"}:
            if position >= len(targets):
                raise ValueError(f"source table wrapper omitted at {path}")
            opening = targets[position]
            if (
                _tag_name(opening) != "milestone"
                or opening.get("unit") != f"source-{tag}-start"
                or opening.get("n") != path
                or opening.get(XML_ID) != (source.get("id") or f"source-node-{path}")
                or opening.tail != source.text
            ):
                raise ValueError(f"source table wrapper start mutation at {path}")
            position += 1
            children = list(source)
            consumed = _compare_sequence(
                children,
                targets[position:],
                [f"{path}.{index}" for index in range(1, len(children) + 1)],
                strict=False,
            )
            position += consumed
            if position >= len(targets):
                raise ValueError(f"source table wrapper end omitted at {path}")
            closing = targets[position]
            if (
                _tag_name(closing) != "milestone"
                or closing.get("unit") != f"source-{tag}-end"
                or closing.get("n") != f"{path}.end"
                or closing.tail != source.tail
            ):
                raise ValueError(f"source table wrapper end mutation at {path}")
            position += 1
        else:
            if position >= len(targets):
                raise ValueError(f"source carrier omitted at {path}")
            _compare_node(source, targets[position], path, top=False)
            position += 1
    if strict and position != len(targets):
        raise ValueError("source child count/invention mutation")
    return position


def _compare_node(source: etree._Element, target: etree._Element, path: str, *, top: bool) -> None:
    if target.get("n") != path or target.tail != source.tail:
        raise ValueError(f"source carrier order/tail mutation at {path}")
    if not isinstance(source.tag, str):
        if _tag_name(target) != "milestone" or target.get("unit") != "source-comment" or target.get("rend") != "comment-sha256:" + _sha((source.text or "").encode("utf-8")):
            raise ValueError(f"source comment mutation at {path}")
        return
    if target.text != source.text:
        raise ValueError(f"source carrier text mutation at {path}")
    tag = source.tag.lower()
    expected = (
        tag if tag in {"table", "figure"} else "row" if tag == "tr" else
        "cell" if tag in {"td", "th"} else
        "ab" if top else
        "ref" if tag == "a" else "graphic" if tag == "img" else
        "lb" if tag == "br" else "milestone" if tag == "hr" else
        "hi" if tag in {"i", "em", "strong", "b", "small", "sup", "sub"} else
        "title" if tag == "cite" else "add" if tag == "ins" else "seg"
    )
    if _tag_name(target) != expected:
        raise ValueError(f"source carrier role mutation at {path}: {tag}")
    if expected in {"ab", "seg"} and target.get("type") != f"source-{tag}":
        raise ValueError(f"source structural role mutation at {path}: {tag}")
    if tag == "th" and target.get("role") != "label":
        raise ValueError(f"source table heading role mutation at {path}")
    if tag in {"td", "th"} and target.get("cols") != source.get("colspan"):
        raise ValueError(f"source table span mutation at {path}")
    if target.get(XML_ID) != (source.get("id") or f"source-node-{path}"):
        raise ValueError(f"source ID mutation at {path}")
    if target.get(XML_LANG) != source.get("lang"):
        raise ValueError(f"source language mutation at {path}")
    if tag == "a" and target.get("target") != (source.get("href") or None):
        raise ValueError(f"source link target mutation at {path}")
    if tag == "img" and target.get("url") != source.get("src"):
        raise ValueError(f"source image target mutation at {path}")
    render = target.get("rend") or ""
    for key, prefix in (("class", "source-class:"), ("style", "source-style:"), ("alt", "source-alt:"), ("title", "source-title:")):
        value = source.get(key)
        if value and prefix + value not in render:
            raise ValueError(f"source {key} mutation at {path}")
    if tag == "a" and source.get("href") == "" and "source-href-empty" not in render:
        raise ValueError(f"source empty href mutation at {path}")
    children = list(source)
    _compare_sequence(
        children,
        list(target),
        [f"{path}.{index}" for index in range(1, len(children) + 1)],
        strict=True,
    )


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> dict[str, object]:
    root = source_manifest.repository_root
    profile_bytes = source_manifest.authority_path("profile").read_bytes()
    profile = json.loads(profile_bytes)
    policy_bytes = source_manifest.authority_path("policy").read_bytes()
    policy = json.loads(policy_bytes)
    body, members, body_text = _source(source_manifest, profile)
    xml = candidate.member_bytes("content.tei.xml")
    tree = etree.fromstring(xml, parser=etree.XMLParser(resolve_entities=False, no_network=True))
    schema = compiled_schema()
    if not schema.validate(tree):
        raise ValueError("candidate is not valid TEI P5: " + str(schema.error_log[:1]))
    if _tag_name(tree) != "teiCorpus" or tree.get(XML_ID) != f"pg{profile['ebook_id']}-complete-edition":
        raise ValueError("candidate volume identity mismatch")
    units = profile["units"]
    for header in [tree.find(f"{{{TEI}}}teiHeader"), *[item.find(f"{{{TEI}}}teiHeader") for item in tree.findall(f"{{{TEI}}}TEI")]]:
        if header is None:
            raise ValueError("candidate header missing")
        title_stmt = header.find(f"{{{TEI}}}fileDesc/{{{TEI}}}titleStmt")
        if title_stmt is None or [(etree.QName(e).localname, e.text) if etree.QName(e).localname != "respStmt" else (e.findtext(f"{{{TEI}}}resp"), e.findtext(f"{{{TEI}}}name")) for e in title_stmt if etree.QName(e).localname != "title"] != [(e["role"],e["name"]) for e in profile["contributors"]]:
            raise ValueError("candidate contributor role mismatch")
    if not units or units[0]["start"] != 0 or units[-1]["end"] != len(body) - 1 or any(a["end"] + 1 != b["start"] for a, b in zip(units, units[1:])):
        raise ValueError("source unit coverage gap/overlap")
    documents = tree.findall(f"{{{TEI}}}TEI")
    if len(documents) != len(units):
        raise ValueError("candidate independent work count mismatch")
    combined: list[str] = []
    for document, unit in zip(documents, units, strict=True):
        if document.get(XML_ID) != unit["id"]:
            raise ValueError("candidate unit identity/order mismatch")
        title = document.find(f".//{{{TEI}}}teiHeader/{{{TEI}}}fileDesc/{{{TEI}}}titleStmt/{{{TEI}}}title")
        if title is None or title.text != unit["title"]:
            raise ValueError("candidate unit title mismatch")
        unit_body = document.find(f"{{{TEI}}}text/{{{TEI}}}body")
        if unit_body is None or len(unit_body) != unit["end"] - unit["start"] + 1:
            raise ValueError("candidate unit carrier count mismatch")
        if unit["start"] == 0 and unit_body.text != body.text:
            raise ValueError("source body opening text mismatch")
        for index, target in zip(range(unit["start"], unit["end"] + 1), unit_body, strict=True):
            _compare_node(body[index], target, str(index + 1), top=True)
        combined.append("".join(unit_body.itertext()))
    if "".join(combined) != body_text:
        raise ValueError("source body text omissions, duplication, or invention")
    ids = [element.get(XML_ID) for element in tree.iter() if element.get(XML_ID)]
    if len(ids) != len(set(ids)):
        raise ValueError("candidate duplicate XML IDs")
    source_ids = {element.get("id") for element in body.iter() if element.get("id")}
    for reference in tree.iter(f"{{{TEI}}}ref"):
        target = reference.get("target")
        if target and target.startswith("#") and (target[1:] not in ids or target[1:] not in source_ids):
            raise ValueError("candidate local link closure/identity failure")
    member_paths = {item["path"] for item in members}
    for graphic in tree.iter(f"{{{TEI}}}graphic"):
        if graphic.get("url") not in member_paths:
            raise ValueError("candidate image target absent from retained ZIP")
    account = json.loads(candidate.member_bytes("source-accountability.json"))
    if account != {"contract":"ocd-manifest-pg-l793-l795-source-accounting-v1","ebook_id":profile["ebook_id"],"archive_sha256":profile["archive_sha256"],"html_sha256":profile["html_sha256"],"archive_members":members,"body_direct_children":len(body),"body_text_sha256":_sha(body_text.encode("utf-8")),"units":units,"tei_sha256":_sha(xml),"mapping":account.get("mapping"),"source_tag_counts":profile["source_tag_counts"],"source_attribute_counts":profile["source_attribute_counts"],"body_element_count":sum(1 for e in body.iter() if isinstance(e.tag,str)),"image_references":[e.get("src") for e in body.iter("img")],"link_references":[e.get("href") for e in body.iter("a") if e.get("href")]} or not account["mapping"].startswith("Every retained HTML body"):
        raise ValueError("candidate source accounting mismatch")
    if candidate.member_bytes("README.source.md") != source_manifest.authority_path("readme").read_bytes() or json.loads(candidate.member_bytes("provenance.json")) != policy["provenance"]:
        raise ValueError("candidate source notice or provenance mismatch")
    if candidate.member_bytes("unresolved.jsonl") != b"".join(_canonical(item) for item in policy["unresolved"]):
        raise ValueError("candidate unresolved status mismatch")
    closure = _closure(root)
    if closure != source_manifest.record["validator"]["import_closure_sha256"]:
        raise ValueError("oracle import closure drifted")
    facts = MechanicalFacts(
        validator_implementation_sha256=_sha(Path(__file__).read_bytes()),
        validator_import_closure_sha256=closure,
        source_sha256=_sha(source_manifest.authority_path("retained-archive").read_bytes()),
        profile_sha256=_sha(profile_bytes),
        package_schema_sha256=_sha(source_manifest.authority_path("candidate-package-schema").read_bytes()),
        xsd_sha256=_sha(source_manifest.authority_path("tei-p5-xsd").read_bytes()),
        policy_sha256=_sha(policy_bytes),
        findings=(),
    )
    return verify_mechanical_facts(source_manifest, candidate, facts).as_record()


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
