"""Independent source and candidate oracle for retained PG L772 and L790 witnesses."""

from __future__ import annotations

import base64
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
ORACLE_ID = "ocd-guyon-pg24989-complete-envelope-oracle"
ORACLE_VERSION = "16"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _closure(root: Path) -> str:
    paths = (
        "build/tei/guyon_short_method_24989_v16_oracle.py",
        "build/tei/guyon_short_method_24989_v16.py",
        "build/tei/manifest_pg_l772_l790.py",
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


def _tei_text_with_encoded_table_tails(node: etree._Element) -> str:
    parts: list[str] = []

    def visit(current: etree._Element) -> None:
        if current.text:
            parts.append(current.text)
        rend = current.get("rend") or ""
        prefix = "source-tail-utf8-base64:"
        if _tag_name(current) == "milestone" and rend.startswith(prefix):
            parts.append(base64.b64decode(rend[len(prefix):], validate=True).decode("utf-8", errors="strict"))
        for child in current:
            visit(child)
        if current.tail:
            parts.append(current.tail)

    visit(node)
    return "".join(parts)


def _compare_sequence(
    sources: list[etree._Element],
    targets: list[etree._Element],
    paths: list[str],
    *,
    strict: bool,
    top: bool = False,
    block: bool = False,
) -> int:
    if block:
        targets = _flatten_sections(targets)
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
                or closing.tail is not None
                or closing.get("rend") != (
                    "source-tail-utf8-base64:" + base64.b64encode(source.tail.encode("utf-8")).decode("ascii")
                    if source.tail is not None else None
                )
            ):
                raise ValueError(f"source table wrapper end mutation at {path}")
            position += 1
        else:
            if position >= len(targets):
                raise ValueError(f"source carrier omitted at {path}")
            _compare_node(source, targets[position], path, top=top, check_tail=not (block and source.tail is not None))
            position += 1
            if block and source.tail is not None:
                tail = targets[position] if position < len(targets) else None
                if tail is None or _tag_name(tail) != "div" or tail.get("type") != "source-tail" or tail.get("n") != f"{path}.tail" or tail.get(XML_ID) != f"source-tail-{path}":
                    raise ValueError(f"source nonwhite tail carrier omitted at {path}")
                text = tail.find(f"{{{TEI}}}ab")
                if text is None or text.get("type") != "source-tail-text" or text.get("n") != f"{path}.tail" or text.get(XML_ID) != f"source-tail-text-{path}" or text.text != source.tail:
                    raise ValueError(f"source nonwhite tail text mutation at {path}")
                position += 1
    if strict and position != len(targets):
        raise ValueError("source child count/invention mutation")
    return position


def _compare_node(source: etree._Element, target: etree._Element, path: str, *, top: bool, check_tail: bool = True) -> None:
    if target.get("n") != path or (check_tail and target.tail != source.tail) or (not check_tail and target.tail is not None):
        raise ValueError(f"source carrier order/tail mutation at {path}")
    if not isinstance(source.tag, str):
        if _tag_name(target) != "milestone" or target.get("unit") != "source-comment" or target.get("rend") != "comment-sha256:" + _sha((source.text or "").encode("utf-8")):
            raise ValueError(f"source comment mutation at {path}")
        return
    tag = source.tag.lower()
    cell_context = source.getparent() is not None and (
        source.getparent().tag.lower() in {"td", "th"}
        or any(isinstance(parent.tag, str) and parent.tag.lower() in {"td", "th"} for parent in source.iterancestors())
    )
    if tag in {"h1", "h2", "h3", "h4"} and not cell_context:
        if _tag_name(target) != "div" or target.get("type") != "source-section" or target.get("subtype") != tag:
            raise ValueError(f"source heading hierarchy mutation at {path}")
        if target.get(XML_ID) != (source.get("id") or f"source-node-{path}") or target.get(XML_LANG) != source.get("lang"):
            raise ValueError(f"source heading identity mutation at {path}")
        render = target.get("rend") or ""
        for key, prefix in (("class", "source-class:"), ("style", "source-style:")):
            value = source.get(key)
            if value and prefix + value not in render:
                raise ValueError(f"source heading {key} mutation at {path}")
        head = target.find(f"{{{TEI}}}head")
        if head is None or head.text != source.text or len(target) == 0 or target[0] is not head:
            raise ValueError(f"source heading text/order mutation at {path}")
        children = list(source)
        _compare_sequence(children, list(head), [f"{path}.{index}" for index in range(1, len(children) + 1)], strict=True)
        return
    expected = (
        tag if tag in {"table", "figure"} else "row" if tag == "tr" else
        "cell" if tag in {"td", "th"} else
        ("seg" if cell_context else "div") if tag == "div" else "p" if tag == "p" else
        "div" if tag in {"header", "footer", "blockquote"} else
        "list" if tag in {"ul", "ol"} else "item" if tag == "li" else
        "ab" if top else
        "ref" if tag == "a" else "graphic" if tag == "img" else
        "lb" if tag == "br" else "milestone" if tag == "hr" else
        "hi" if tag in {"i", "em", "strong", "b", "small", "sup", "sub"} else
        "title" if tag == "cite" else "add" if tag == "ins" else "seg"
    )
    if _tag_name(target) != expected:
        raise ValueError(f"source carrier role mutation at {path}: {tag}")
    if tag in {"ul", "ol"} and target.get("type") != ("unordered" if tag == "ul" else "ordered"):
        raise ValueError(f"source list ordering mutation at {path}")
    if tag in {"div", "header", "footer", "blockquote"} and not cell_context and source.text and source.text.strip():
        leading = target.find(f"{{{TEI}}}ab")
        if target.text is not None or leading is None or leading.get("type") != "source-div-leading-text" or leading.get("n") != f"{path}.text" or leading.get(XML_ID) != f"source-div-leading-text-{path}" or leading.text != source.text:
            raise ValueError(f"source division leading text mutation at {path}")
        target_children = list(target)[1:]
    else:
        if target.text != source.text:
            raise ValueError(f"source carrier text mutation at {path}")
        target_children = list(target)
    if expected in {"ab", "seg", "div"} and target.get("type") != f"source-{tag}":
        raise ValueError(f"source structural role mutation at {path}: {tag}")
    if tag == "th" and target.get("role") != "label":
        raise ValueError(f"source table heading role mutation at {path}")
    if tag in {"td", "th"} and target.get("cols") != source.get("colspan"):
        raise ValueError(f"source table span mutation at {path}")
    if target.get(XML_ID) != (source.get("id") or f"source-node-{path}"):
        raise ValueError(f"source ID mutation at {path}")
    if target.get(XML_LANG) != source.get("lang"):
        raise ValueError(f"source language mutation at {path}")
    if tag == "a" and target.get("target") != source.get("href"):
        raise ValueError(f"source link target mutation at {path}")
    if tag == "img" and target.get("url") != source.get("src"):
        raise ValueError(f"source image target mutation at {path}")
    render = target.get("rend") or ""
    for key, prefix in (("class", "source-class:"), ("style", "source-style:"), ("alt", "source-alt:")):
        value = source.get(key)
        if value and prefix + value not in render:
            raise ValueError(f"source {key} mutation at {path}")
    children = list(source)
    _compare_sequence(children, target_children, [f"{path}.{index}" for index in range(1, len(children) + 1)], strict=True, block=tag in {"div", "header", "footer", "blockquote"} and not cell_context)


def _flatten_sections(targets: list[etree._Element]) -> list[etree._Element]:
    """Flatten only the added section containers, retaining source order for comparison."""
    flattened: list[etree._Element] = []
    for target in targets:
        if _tag_name(target) == "div" and target.get("type") == "source-carrier":
            children = list(target)
            if not children or target.get("n") is None or target.get(XML_ID) != f"source-carrier-{target.get('n')}":
                raise ValueError("source carrier wrapper mutation")
            if len(children) == 1 and _tag_name(children[0]) == "ab" and children[0].get("type") == "source-inline-carrier":
                inline = children[0]
                if inline.get("n") != target.get("n") or inline.get(XML_ID) != f"source-inline-carrier-{target.get('n')}":
                    raise ValueError("source inline carrier wrapper mutation")
                flattened.extend(list(inline))
            else:
                flattened.extend(children)
            continue
        flattened.append(target)
        if _tag_name(target) == "div" and target.get("type") == "source-section":
            flattened.extend(_flatten_sections(list(target)[1:]))
    return flattened


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
    if _tag_name(tree) != "TEI" or tree.get(XML_ID) != f"pg{profile['ebook_id']}-complete-edition":
        raise ValueError("candidate volume identity mismatch")
    units = profile["units"]
    if len(units) != 1 or units[0]["start"] != 0 or units[0]["end"] != len(body) - 1:
        raise ValueError("source unit coverage gap/overlap")
    header = tree.find(f"{{{TEI}}}teiHeader")
    if header is None:
        raise ValueError("candidate header missing")
    title_stmt = header.find(f"{{{TEI}}}fileDesc/{{{TEI}}}titleStmt")
    if title_stmt is None or title_stmt.findtext(f"{{{TEI}}}title") != profile["volume_title"] or [(etree.QName(e).localname, e.text) if etree.QName(e).localname != "respStmt" else (e.findtext(f"{{{TEI}}}resp"), e.findtext(f"{{{TEI}}}name")) for e in title_stmt if etree.QName(e).localname != "title"] != [(e["role"],e["name"]) for e in profile["contributors"]]:
        raise ValueError("candidate title/contributor role mismatch")
    unit_body = tree.find(f"{{{TEI}}}text/{{{TEI}}}body")
    if unit_body is None or len(unit_body) != 1 or unit_body[0].tag != f"{{{TEI}}}div" or unit_body[0].get("type") != "source-body" or unit_body[0].get(XML_ID) != "source-body":
        raise ValueError("candidate body division boundary mismatch")
    source_body = unit_body[0]
    if body.text and body.text.strip():
        leading = source_body.find(f"{{{TEI}}}ab")
        if source_body.text is not None or leading is None or leading.get("type") != "source-body-leading-text" or leading.get("n") != "body.text" or leading.get(XML_ID) != "source-body-leading-text" or leading.text != body.text:
            raise ValueError("source body leading text mutation")
        body_targets = list(source_body)[1:]
    else:
        if source_body.text != body.text:
            raise ValueError("candidate body opening text mismatch")
        body_targets = list(source_body)
    _compare_sequence(list(body), body_targets, [str(index) for index in range(1, len(body) + 1)], strict=True, top=True, block=True)
    if _tei_text_with_encoded_table_tails(unit_body) != body_text:
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
    empty_title_nodes = [(element.tag, element.get('id'), element.get('title')) for element in body.iter() if element.get('title') is not None]
    if empty_title_nodes != [('h2', 'pg-header-heading', '')]:
        raise ValueError('Guyon source title attribute disposition no longer fits retained evidence')
    if policy['empty_html_attribute_dispositions'] != [{'source_member': 'pg24989-images.html', 'source_selector': '/html/body/header/h2[@id="pg-header-heading"]', 'source_path': '1.1', 'attribute': 'title', 'value': '', 'disposition': 'Present-empty HTML title attribute: no tooltip text to transcribe; exact empty attribute remains in retained HTML. Explicitly excluded from derived heading attributes.', 'tei_locator': 'text/body//div[@type="source-section" and @n="1.1" and @xml:id="pg-header-heading"]'}]:
        raise ValueError('Guyon present-empty title attribute disposition differs')
    account = json.loads(candidate.member_bytes("source-accountability.json"))
    if account != {"contract":"ocd-manifest-pg-l772-l790-source-accounting-v2","ebook_id":profile["ebook_id"],"archive_sha256":profile["archive_sha256"],"html_sha256":profile["html_sha256"],"archive_members":members,"body_direct_children":len(body),"body_text_sha256":_sha(body_text.encode("utf-8")),"units":units,"tei_sha256":_sha(xml),"mapping":policy["account_mapping"],"empty_html_attribute_dispositions":policy["empty_html_attribute_dispositions"],"head_envelope":account.get("head_envelope"),"source_tag_counts":profile["source_tag_counts"],"source_attribute_counts":profile["source_attribute_counts"],"body_element_count":sum(1 for e in body.iter() if isinstance(e.tag,str)),"image_references":[e.get("src") for e in body.iter("img")],"link_references":[e.get("href") for e in body.iter("a") if e.get("href")]} or not account["mapping"].startswith("One top-level titled work"):
        raise ValueError("candidate source accounting mismatch")
    if candidate.member_bytes("README.source.md") != source_manifest.authority_path("readme").read_bytes() or json.loads(candidate.member_bytes("provenance.json")) != policy["provenance"]:
        raise ValueError("candidate source notice or provenance mismatch")
    if candidate.member_bytes("unresolved.jsonl") != b"".join(_canonical(item) for item in policy["unresolved"]):
        raise ValueError("candidate unresolved status mismatch")
    _check_constructed_header(tree, profile, policy)
    _check_head(source_manifest, candidate, tree)
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


class _HeadReader(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.inside = False
        self.rows = []
        self.active = None
    def handle_starttag(self, tag, attrs):
        if tag == 'head':
            self.inside = True
        elif self.inside:
            if tag not in {'meta', 'link', 'style', 'title'}:
                raise ValueError('Unexpected Guyon head child')
            row = {'position': len(self.rows) + 1, 'tag': tag, 'attributes': [(key, value or '') for key, value in attrs], 'text': ''}
            self.rows.append(row)
            self.active = row if tag in {'style', 'title'} else None
    def handle_data(self, data):
        if self.inside and self.active is not None:
            self.active['text'] += data
        elif self.inside and data.strip():
            raise ValueError('Unaccounted Guyon head text')
    def handle_endtag(self, tag):
        if tag == 'head':
            self.inside = False
        elif tag in {'style', 'title'}:
            self.active = None

def _check_head(manifest, candidate, tree):
    with ZipFile(manifest.authority_path('retained-archive')) as archive:
        parser = _HeadReader()
        parser.feed(archive.read('pg24989-images.html').decode('utf-8', errors='strict'))
        parser.close()
        support = archive.read('24989-cover.png')
    if len(parser.rows) != 21 or sum(row['tag'] == 'style' for row in parser.rows) != 2:
        raise ValueError('Independent Guyon HTML head envelope changed')
    account = json.loads(candidate.member_bytes('source-accountability.json')).get('head_envelope')
    if not isinstance(account, dict):
        raise ValueError('Guyon head envelope accounting missing')
    if set(account) != {'contract', 'children', 'support'}:
        raise ValueError('Guyon head accounting fields omitted or invented')
    if account.get('contract') != 'ocd-guyon-head-accountability-v1' or len(account.get('children', [])) != 21:
        raise ValueError('Guyon head accounting contract/count differs')
    ns = {'t': TEI}
    description = tree.find('{' + TEI + '}teiHeader/{' + TEI + '}fileDesc/{' + TEI + '}sourceDesc')
    profile = json.loads(manifest.authority_path('profile').read_bytes())
    policy = json.loads(manifest.authority_path('policy').read_bytes())
    opening = f"Project Gutenberg {profile['ebook_id']}, retained archive SHA-256 {profile['archive_sha256']}. Scope: {policy['provenance']['scope']}."
    if description is None or description.attrib or description.text or len(description) != 21:
        raise ValueError('Guyon complete source description carrier set differs')
    first = description[0]
    if first.tag != '{' + TEI + '}p' or first.attrib or len(first) or first.text != opening or first.tail:
        raise ValueError('Guyon original source description opening differs')
    for paragraph in list(description)[1:20]:
        if paragraph.tag != '{' + TEI + '}p' or paragraph.attrib or paragraph.text or paragraph.tail or len(paragraph) != 1 or paragraph[0].get('type') != 'source-head-metadata' or paragraph[0].tail:
            raise ValueError('Guyon readable metadata paragraph envelope differs')
    if description[-1].tag != '{' + TEI + '}p' or len(description[-1]) != 1 or description[-1][0].get('type') != 'source-support-observation' or description[-1].attrib or description[-1].text or description[-1].tail:
        raise ValueError('Guyon cover observation position differs')
    entries = tree.xpath('./t:teiHeader/t:fileDesc/t:sourceDesc/t:p/t:seg[@type="source-head-metadata"]', namespaces=ns)
    if len(entries) != 19:
        raise ValueError('Guyon readable head metadata count differs')
    mapped = iter(entries)
    for source, recorded in zip(parser.rows, account['children'], strict=True):
        expected = {**source, 'attributes': [list(pair) for pair in source['attributes']]}
        if any(recorded.get(key) != value for key, value in expected.items()):
            raise ValueError('Guyon head ledger source identity/attributes/text differs')
        expected_keys = set(expected) | {'disposition'} | (set() if source['tag'] == 'style' else {'tei_locator'})
        if set(recorded) != expected_keys:
            raise ValueError('Guyon head ledger fields omitted or invented')
        if source['tag'] == 'style':
            if recorded.get('disposition') != 'presentation-only stylesheet; complete original retained in bound HTML/ZIP; no visual equivalence claimed' or 'tei_locator' in recorded:
                raise ValueError('Guyon stylesheet disposition differs')
            continue
        target = next(mapped)
        if target.attrib != {'type': 'source-head-metadata', 'n': str(source['position'])} or (target.text or '').strip():
            raise ValueError('Guyon head metadata destination identity/order differs')
        children = list(target)
        if not children or children[0].tag != '{' + TEI + '}seg' or children[0].attrib != {'type': 'source-head-element'} or children[0].text != source['tag'] or children[0].tail != ': ' or len(children[0]):
            raise ValueError('Guyon head source element differs')
        expected_children = 1 + len(source['attributes']) + bool(source['text'])
        if len(children) != expected_children:
            raise ValueError('Guyon head metadata fields omitted or invented')
        for target_field, (key, value) in zip(children[1:1+len(source['attributes'])], source['attributes'], strict=True):
            if target_field.tag != '{' + TEI + '}seg' or target_field.attrib != {'type': 'source-head-attribute', 'n': key} or target_field.tail != '; ':
                raise ValueError('Guyon head attribute identity/order differs')
            if ''.join(target_field.itertext()) != key + '=' + value:
                raise ValueError('Guyon head attribute readable value differs')
            links = list(target_field)
            if value.startswith(('http://', 'https://')):
                if len(links) != 1 or links[0].tag != '{' + TEI + '}ref' or links[0].attrib != {'target': value} or links[0].text != value or links[0].tail:
                    raise ValueError('Guyon source metadata URI target differs')
            elif links:
                raise ValueError('Guyon head attribute invented a link')
        if source['text']:
            last = children[-1]
            if last.tag != '{' + TEI + '}seg' or last.attrib != {'type': 'source-head-text'} or last.text != source['text'] or len(last) or last.tail:
                raise ValueError('Guyon head title text differs')
        locator = 'teiHeader/fileDesc/sourceDesc/p/seg[@type="source-head-metadata" and @n="' + str(source['position']) + '"]'
        if recorded.get('disposition') != 'readable sourceDesc paragraph' or recorded.get('tei_locator') != locator:
            raise ValueError('Guyon head metadata disposition/destination differs')
    expected_support = {'source_member': '24989-cover.png', 'source_container': 'retained-archive', 'sha256': _sha(support), 'bytes': len(support), 'role': 'unreferenced binary support retained in bound ZIP; not a candidate payload; no invented body placement or remote image equivalence'}
    observation_bytes = manifest.authority_path('cover-visual-observation').read_bytes()
    observation = json.loads(observation_bytes)
    if observation['source']['sha256'] != _sha(support) or observation['source']['bytes'] != len(support):
        raise ValueError('Guyon cover visual observation source binding differs')
    expected_support['visual_observation'] = {
        'authority': 'cover-visual-observation',
        'receipt_sha256': _sha(observation_bytes),
        'method': observation['method'],
        'visible_source_text': observation['visible_source_text'],
        'boundary_observation': observation['boundary_observation'],
        'tei_locator': 'teiHeader/fileDesc/sourceDesc/p/seg[@type="source-support-observation"]',
    }
    observations = tree.xpath('./t:teiHeader/t:fileDesc/t:sourceDesc/t:p/t:seg[@type="source-support-observation"]', namespaces=ns)
    if len(observations) != 1:
        raise ValueError('Guyon readable cover observation omitted or duplicated')
    paragraph = observations[0]
    if paragraph.attrib != {'type': 'source-support-observation'} or paragraph.text != 'Independent visual observation of retained ZIP cover 24989-cover.png: ' or len(paragraph) != len(observation['visible_source_text']) or paragraph.tail:
        raise ValueError('Guyon readable cover observation envelope differs')
    for position, (target, item) in enumerate(zip(paragraph, observation['visible_source_text'], strict=True), 1):
        if target.tag != '{' + TEI + '}seg' or target.attrib != {'type': 'source-cover-text', 'n': str(position)} or target.text != item['role'] + ': ' + item['text'] or target.tail != '; ' or len(target):
            raise ValueError('Guyon readable cover observation text/order differs')
    if account.get('support') != expected_support:
        raise ValueError('Guyon retained binary support omitted or changed')


def _check_constructed_header(tree, profile, policy):
    """Independently build only declared editorial metadata from bound policy/profile."""
    tag = lambda name: '{' + TEI + '}' + name
    if tree.attrib != {XML_ID: f"pg{profile['ebook_id']}-complete-edition"} or tree.text or tree.tail or [child.tag for child in tree] != [tag('teiHeader'), tag('text')]:
        raise ValueError('Guyon document envelope invented or altered')
    header = tree[0]
    if header.attrib or header.text or header.tail or len(header) != 1 or header[0].tag != tag('fileDesc'):
        raise ValueError('Guyon header envelope invented or altered')
    description = header[0]
    if description.attrib or description.text or description.tail or [child.tag for child in description] != [tag('titleStmt'), tag('publicationStmt'), tag('sourceDesc')]:
        raise ValueError('Guyon header description invented or altered')
    expected_title = etree.Element(tag('titleStmt'))
    etree.SubElement(expected_title, tag('title')).text = profile['volume_title']
    for contributor in profile['contributors']:
        role, name = contributor['role'], contributor['name']
        if role in {'author', 'editor'}:
            etree.SubElement(expected_title, tag(role)).text = name
        else:
            responsibility = etree.SubElement(expected_title, tag('respStmt'))
            etree.SubElement(responsibility, tag('resp')).text = role
            etree.SubElement(responsibility, tag('name')).text = name
    expected_publication = etree.Element(tag('publicationStmt'))
    etree.SubElement(expected_publication, tag('p')).text = policy['publication_notice']
    def record(node):
        return (node.tag, sorted(node.attrib.items()), node.text, node.tail, [record(child) for child in node])
    if record(description[0]) != record(expected_title):
        raise ValueError('Guyon complete title/contributor metadata invented or altered')
    if record(description[1]) != record(expected_publication):
        raise ValueError('Guyon candidate publication status invented or altered')
