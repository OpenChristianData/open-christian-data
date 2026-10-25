"""Work-local repair of the two retained L635 biography components.

The dated TEIs remain immutable lineage. Their lossy representation is repaired
from their already retained HTML, not presented as an additive byte inverse.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import quote
from zipfile import ZipFile

import html5lib
from lxml import etree
from build.tei.tyerman_whitefield_runtime import guard

TEI = "http://www.tei-c.org/ns/1.0"
XML = "{http://www.w3.org/XML/1998/namespace}"
ANA = "urn:ocd:l635:source:"
WORK = "tyerman-life-george-whitefield"
TITLE = "The Life of the Rev. George Whitefield, B.A."
VOLUMES = ("44280", "62023")
HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
CONTAINERS = {"div", "header", "footer", "blockquote"}
INLINE = {"a", "span", "i", "em", "strong", "small", "sup", "sub", "abbr", "cite", "br", "img"}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def enc(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def node(parent, name, **attrs):
    return etree.SubElement(parent, f"{{{TEI}}}{name}", **attrs)


def annotation(source, **extra):
    return ANA + quote(enc({"tag": source.tag, "attributes": dict(source.attrib), **extra}).decode().rstrip("\n"), safe="")


def sid(eid, value):
    return f"v{eid}-{value}"


def common(source, target, eid, **extra):
    target.set("ana", annotation(source, **extra))
    if source.get("id"):
        target.set(XML + "id", sid(eid, source.get("id")))
    if source.get("lang") is not None:
        target.set(XML + "lang", source.get("lang"))
    if source.get("style") is not None:
        target.set("style", source.get("style"))
    if source.get("role") is not None:
        target.set("subtype", "source-role-" + source.get("role"))
    if source.get("aria-labelledby") is not None:
        target.set("corresp", " ".join("#" + sid(eid, x) for x in source.get("aria-labelledby").split()))
    if source.tag in HEADINGS and source.get("title") is not None:
        target.set("n", source.get("title"))
    target.tail = source.tail


def inline(source, eid, assets):
    tag = source.tag
    if tag == "a":
        href = source.get("href")
        out = etree.Element(f"{{{TEI}}}{'ref' if href else 'seg'}")
        out.set("rend", "source-a")
        if href:
            out.set("target", "#" + sid(eid, href[1:]) if href.startswith("#") else href)
    elif tag == "br":
        out = etree.Element(f"{{{TEI}}}lb")
    elif tag == "img":
        data = assets[source.get("src")]
        media = "image/png" if source.get("src").endswith(".png") else "image/jpeg"
        out = etree.Element(f"{{{TEI}}}graphic", url="data:" + media + ";base64," + base64.b64encode(data).decode(), corresp=f"urn:ocd:retained:pg{eid}:{source.get('src')}")
        if source.get("alt") is not None:
            out.set("n", source.get("alt"))
        for key in ("width", "height"):
            if source.get(key):
                out.set(key, source.get(key) + "px")
        if source.get('src') == 'images/brace_lt.png':
            if source.get('style') != 'height: 2em;':
                raise ValueError('Source brace image style differs')
            out.set('height', '2em')
    elif tag == "abbr":
        out = etree.Element(f"{{{TEI}}}choice")
        abbr = node(out, "abbr")
        abbr.text = source.text
        for child in source:
            abbr.append(inline(child, eid, assets))
        node(out, "expan").text = source.get("title")
        common(source, out, eid)
        return out
    elif tag in INLINE:
        out = etree.Element(f"{{{TEI}}}hi", rend="source-" + tag + (" " + source.get("class") if source.get("class") else ""))
    elif tag in {"p", "div"} | HEADINGS:
        # HTML block containers in table cells are losslessly nested phrase
        # carriers. Their paragraph/heading roles are explicit, not flattened.
        out = etree.Element(f"{{{TEI}}}seg", type="source-" + tag)
    else:
        raise ValueError(f"Unsupported source inline {tag}")
    common(source, out, eid)
    out.text = source.text
    for child in source:
        out.append(inline(child, eid, assets))
    if tag == "span" and "pagenum" in source.get("class", "").split():
        match = re.search(r"(?:\[(?:Pg\s*)?|\{)([^\]}]+)(?:\]|\})", "".join(source.itertext()))
        node(out, "pb", **({"n": match.group(1)} if match else {}))
    if tag == "span" and source.get("title") is not None:
        node(out, "note", type="source-tooltip").text = source.get("title")
    return out


def block(source, eid, assets):
    tag = source.tag
    if tag in CONTAINERS:
        out = etree.Element(f"{{{TEI}}}div", type="source-" + tag)
        common(source, out, eid)
        if source.text is not None:
            node(out, "p", rend="source-leading-text").text = source.text
        for child in source:
            slot = node(out, "div", type="source-child-carrier")
            slot.append(block(child, eid, assets))
        return out
    if tag == "table":
        out = etree.Element(f"{{{TEI}}}table")
        sections = []
        for section in source:
            if section.tag != "tbody" or any(x.tag != "tr" for x in section):
                raise ValueError("Unexpected retained table section")
            sections.append({"tag": section.tag, "attributes": dict(section.attrib), "direct_text": section.text, "tail_text": section.tail, "rows": len(section)})
        common(source, out, eid, sections=sections)
        out.text = source.text
        if source.get("data-summary") is not None:
            node(out, "head", type="source-table-summary").text = source.get("data-summary")
        for section in source:
            for row in section:
                tr = node(out, "row")
                common(row, tr, eid)
                tr.text = row.text
                for cell in row:
                    if cell.tag not in {"td", "th"}:
                        raise ValueError("Unexpected retained table child")
                    tc = node(tr, "cell", **({"role": "label"} if cell.tag == "th" else {}))
                    common(cell, tc, eid)
                    if cell.get("colspan"):
                        tc.set("cols", cell.get("colspan"))
                    tc.text = cell.text
                    for child in cell:
                        tc.append(inline(child, eid, assets))
        return out
    if tag == "ul":
        out = etree.Element(f"{{{TEI}}}list", type="source-ul")
        common(source, out, eid)
        out.text = source.text
        for child in source:
            if child.tag != "li":
                raise ValueError("Unexpected retained list child")
            item = node(out, "item")
            common(child, item, eid)
            item.text = child.text
            for sub in child:
                item.append(inline(sub, eid, assets))
        return out
    if tag == "hr":
        out = etree.Element(f"{{{TEI}}}milestone", unit="source-hr")
        common(source, out, eid)
        out.text = source.text
        if len(source):
            raise ValueError("Unexpected rule contents")
        return out
    if tag == "p" or tag in HEADINGS:
        out = etree.Element(f"{{{TEI}}}{'head' if tag in HEADINGS else 'p'}", rend="source-" + tag)
        common(source, out, eid)
        out.text = source.text
        for child in source:
            out.append(inline(child, eid, assets))
        return out
    if tag in INLINE:
        out = etree.Element(f"{{{TEI}}}p", rend="source-standalone-inline")
        out.append(inline(source, eid, assets))
        return out
    raise ValueError(f"Unsupported retained block {tag}")


def fields(root):
    rows = []
    def visit(e, path):
        rows.append({"selector": path, "tag": e.tag, "attributes": dict(e.attrib), "direct_text": e.text, "tail_text": e.tail, "children": len(e)})
        for i, child in enumerate(e, 1):
            visit(child, f"{path}/{child.tag}[{i}]")
    visit(root, "/" + root.tag)
    return rows


def load_sources(manifest):
    result = []
    for eid in VOLUMES:
        archive_path = manifest.authority_path("archive-" + eid)
        with ZipFile(archive_path) as archive:
            if archive.testzip() is not None:
                raise ValueError("Retained archive CRC failure")
            raw = archive.read(f"pg{eid}-images.html")
            assets = {x.filename: archive.read(x) for x in archive.infolist() if not x.is_dir() and x.filename.startswith("images/")}
        parser = html5lib.HTMLParser(namespaceHTMLElements=False)
        source = parser.parse(raw)
        if parser.errors or any(not isinstance(x.tag, str) for x in source.iter()):
            raise ValueError("Unexpected parser recovery or comment: revise explicit mapping")
        old = manifest.authority_path("legacy-tei-" + eid).read_bytes()
        old_root = etree.fromstring(old, etree.XMLParser(resolve_entities=False, no_network=True))
        old_text = old_root.find(f"{{{TEI}}}text")
        if " ".join("".join(old_text.itertext()).split()) != " ".join("".join(source.find('body').itertext()).split()):
            raise ValueError("Recovered component normalized body correspondence differs")
        result.append((eid, raw, source, assets, old_root))
    return result


def envelope(raw, source, old_root):
    decoded = raw.decode("utf-8", errors="strict")
    start = decoded.index("<html")
    end = decoded.rindex("</html>") + len("</html>")
    html_body = source.find("body")
    return {"raw_document_prefix": decoded[:start], "raw_document_suffix": decoded[end:], "html": {"tag": source.tag, "attributes": dict(source.attrib), "direct_text": source.text, "tail_text": source.tail}, "head": fields(source.find('head')), "body": {"tag": html_body.tag, "attributes": dict(html_body.attrib), "direct_text": html_body.text, "tail_text": html_body.tail}, "legacy_header": etree.tostring(old_root.find(f"{{{TEI}}}teiHeader"), encoding="unicode"), "legacy_scope_qualification": "The historical per-volume candidate and distinct-work claim are superseded for current scope only. Both volumes constitute this one authored biography; historical records remain unchanged."}


def header(root, manifest, loaded):
    hd = node(root, "teiHeader")
    fd = node(hd, "fileDesc")
    ts = node(fd, "titleStmt")
    node(ts, "title").text = TITLE
    node(ts, "author").text = "L. Tyerman"
    pub = node(fd, "publicationStmt")
    node(pub, "p").text = "Nonaccepted complete-work reconstruction candidate. Technical validation, human acceptance, rights clearance, and publication are separate."
    sd = node(fd, "sourceDesc")
    for position, (eid, raw, source, assets, old_root) in enumerate(loaded, 1):
        b = node(sd, "bibl", n=str(position))
        node(b, "title").text = TITLE + (" Vol. I" if position == 1 else " Vol. II")
        node(b, "author").text = "L. Tyerman"
        node(b, "pubPlace").text = "London"
        node(b, "publisher").text = "Hodder and Stoughton"
        node(b, "date", when="1876" if position == 1 else "1877").text = "MDCCCLXXVI" if position == 1 else "MDCCCLXXVII"
        node(b, "ref", target=f"https://www.gutenberg.org/ebooks/{eid}").text = f"Retained Project Gutenberg eBook {eid}"
        node(b, 'note', type='retained-acquisition').text = enc(json.loads(manifest.authority_path('acquisition-'+eid).read_bytes())).decode().rstrip('\n')
        notes = node(b, "note", type="source-envelope")
        notes.text = enc(envelope(raw, source, old_root)).decode().rstrip("\n")
        support = node(b, "note", type="retained-archive-support")
        support.text = enc({"archive_members": json.loads(manifest.authority_path('profile').read_bytes())["volumes"][position - 1]["archive_members"], "qualification": "All original archive members are retained and hash-bound. Body-referenced images are embedded as exact pixels; the Volume I cover is head-linked support, not invented body illustration. CSS and electronic head/prolog fields are source annotations, not authored prose. No print collation or rights clearance is claimed."}).decode().rstrip("\n")
    return hd


def _build(manifest):
    if manifest.record["work_id"] != WORK or manifest.record["source_id"] != "gutenberg-44280-62023-retained-biography":
        raise ValueError("Work-local source fence differs")
    loaded = load_sources(manifest)
    root = etree.Element(f"{{{TEI}}}TEI", nsmap={None: TEI})
    root.set(XML + "lang", "en")
    header(root, manifest, loaded)
    group = node(node(root, "text"), "group")
    for position, (eid, raw, source, assets, old_root) in enumerate(loaded, 1):
        body = source.find("body")
        url = next(x.get("content") for x in source.find('head') if x.get("property") == "og:url")
        text = node(group, "text", n="I" if position == 1 else "II", ana=annotation(body))
        text.set(XML + "id", "volume-" + eid)
        text.set(XML + "lang", source.get("lang"))
        text.set(XML + "base", url)
        regions = {name: node(text, name) for name in ("front", "body", "back")}
        for name in regions:
            regions[name] = node(regions[name], "div", type="source-" + name + "-envelope")
        if body.text is not None:
            node(regions['front'], "p", rend="source-body-leading-text").text = body.text
        for i, child in enumerate(body, 1):
            region = 'front' if child.tag == 'header' else 'back' if child.tag == 'footer' else 'body'
            slot = node(regions[region], "div", type="source-body-carrier", n=str(i))
            slot.append(block(child, eid, assets))
    xml = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
    profile = json.loads(manifest.authority_path('profile').read_bytes())
    policy = json.loads(manifest.authority_path('policy').read_bytes())
    account = {"contract": "ocd-l635-complete-biography-accountability-v1", "work_id": WORK, "scope": "One complete authored biography, two ordered complete electronic source-volume envelopes", "tei_sha256": sha(xml), "source_inventory": profile, "representation": "Source-backed repaired representation of exact retained legacy TEI components. No whole-body additive byte inverse is claimed. Actual native source fields invert to the complete bound HTML5 source DOM; table tbody wrappers alone use explicit nontextual wrapper accounting.", "legacy_component_normalized_body_correspondence": True}
    return {"content.tei.xml": xml, "source-accountability.json": enc(account), "provenance.json": enc(policy['provenance']), "unresolved.jsonl": b''.join(enc(x) for x in policy['unresolved']), "README.source.md": manifest.authority_path('readme').read_bytes()}


def _convert(manifest):
    if manifest.record['converter']['callable']!='_convert' or manifest.record['validator']['callable']!='_oracle':
        raise ValueError('Final guarded source callable fence differs')
    guard(manifest,'before-conversion')
    result=_build(manifest)
    guard(manifest,'after-conversion')
    return result


_convert.converter_id = "ocd-l635-retained-complete-whitefield-biography"
_convert.converter_version = "1"
_convert.implementation_path = Path(__file__).resolve()
_build.converter_id = _convert.converter_id
_build.converter_version = _convert.converter_version
_build.implementation_path = Path(__file__).resolve()
