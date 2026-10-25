"""Reconstruct the seven exact L634-L637 Tyerman Project Gutenberg editions."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from zipfile import ZipFile

import html5lib
from lxml import etree
from ocd_kernel.reconstruction.contract import SourceManifest

TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
WORKS = {
    "tyerman-life-times-john-wesley-vol-1-1872": ("69582", "The Life and Times of the Rev. John Wesley, M.A., Founder of the Methodists. Vol. I"),
    "tyerman-life-times-john-wesley-vol-2-1872": ("71130", "The Life and Times of the Rev. John Wesley, M.A., Founder of the Methodists. Vol. II"),
    "tyerman-life-times-john-wesley-vol-3-1872": ("76882", "The Life and Times of the Rev. John Wesley, M.A., Founder of the Methodists. Vol. III"),
    "tyerman-life-george-whitefield-vol-1-1876": ("44280", "The Life of the Rev. George Whitefield, B.A. Vol. I"),
    "tyerman-life-george-whitefield-vol-2-1877": ("62023", "The Life of the Rev. George Whitefield, B.A. Vol. II"),
    "tyerman-oxford-methodists-1873": ("70497", "The Oxford Methodists"),
    "tyerman-life-times-samuel-wesley-1866": ("67980", "The Life and Times of the Rev. Samuel Wesley, M.A."),
}
INLINE = {"a", "span", "i", "em", "b", "strong", "small", "sup", "sub", "abbr", "cite", "ins"}
HEADING = {"h1", "h2", "h3", "h4", "h5", "h6"}
PAGE = re.compile(r"(?:\[(?:Pg\s*)?|\{)([^\]}]+)(?:\]|\})")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def enc(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def node(parent: etree._Element, tag: str, **attrs: str) -> etree._Element:
    return etree.SubElement(parent, f"{{{TEI}}}{tag}", **attrs)


def source_id(source: etree._Element, target: etree._Element) -> None:
    if source.get("id"):
        target.set(XML_ID, source.get("id"))


def page_identity(source: etree._Element, target: etree._Element) -> None:
    anchors=[x.get("id") for x in source.iter("a") if x.get("id")]
    own=source.get("id")
    if own and anchors: raise ValueError("page marker has separate span and anchor ids")
    value=own or (anchors[0] if anchors else None)
    if value: target.set(XML_ID,value)


def inline(source: etree._Element, target: etree._Element) -> None:
    target.text = source.text
    for child in source:
        if not isinstance(child.tag, str):
            if child.tail:
                if len(target): target[-1].tail = (target[-1].tail or "") + child.tail
                else: target.text = (target.text or "") + child.tail
            continue
        tag = child.tag
        if tag == "br": item = node(target, "lb")
        elif tag == "hr": item = node(target, "milestone", unit="source-rule")
        elif tag == "img":
            if not child.get("src"): raise ValueError("source image without src")
            item = node(target, "graphic", url=child.get("src"))
            if child.get("alt"): item.set("n", child.get("alt"))
        elif tag == "a":
            item = node(target, "ref", target=child.get("href")) if child.get("href") else node(target, "seg", rend="source-anchor")
            inline(child, item)
        elif tag == "span" and "pagenum" in (child.get("class") or "").split():
            label = "".join(child.itertext()); match = PAGE.search(label)
            item = node(target, "pb", **({"n":match.group(1)} if match else {})); page_identity(child, item)
            node(target, "seg", rend="source-page-label").text = label
            target[-1].tail = (target[-1].tail or "") + (child.tail or "")
        elif tag in INLINE:
            item = node(target, "hi", rend=" ".join(x for x in (tag, child.get("class") or "") if x)); source_id(child, item); inline(child, item)
        else: raise ValueError(f"unaccounted inline element {tag!r}")
        if not (tag == "span" and "pagenum" in (child.get("class") or "").split()): source_id(child, item)
        if not (tag == "span" and "pagenum" in (child.get("class") or "").split()):
            target[-1].tail = (target[-1].tail or "") + (child.tail or "")


def _block_body(source: etree._Element, parent: etree._Element) -> None:
    if not isinstance(source.tag, str): return
    tag = source.tag; classes = set((source.get("class") or "").split())
    if tag in HEADING: name, rend = "head", "source-" + tag
    elif tag == "p": name, rend = "p", "source-p"
    elif tag == "pre": name, rend = "ab", "source-pre"
    elif tag in {"div","span"} and "pagenum" in classes:
        label = "".join(source.itertext()); match = PAGE.search(label)
        p = node(parent, "p", rend="source-page-label"); pb=node(p,"pb",**({"n":match.group(1)} if match else {})); page_identity(source,pb)
        node(p,"seg").text=label; return
    elif tag in {"div", "figure", "figcaption", "header", "footer"}:
        if parent.tag == f"{{{TEI}}}cell":
            item=node(parent,"milestone",unit="source-container")
            source_id(source,item)
            if source.get("class"): item.set("rend",source.get("class"))
            if source.text: node(parent,"p",rend="source-leading-text").text=source.text
            for child in source: block(child,parent)
            return
        item = node(parent, "div", type="source-" + tag)
        source_id(source,item)
        if source.get("class"): item.set("rend", source.get("class"))
        if source.text: node(item,"p",rend="source-leading-text").text=source.text
        for child in source:
            slot=node(item,"div",type="source-child-carrier")
            block(child,slot)
        return
    elif tag == "blockquote":
        item=node(parent,"div",type="source-blockquote"); source_id(source,item)
        if source.text: node(item,"p",rend="source-leading-text").text=source.text
        for child in source:
            slot=node(item,"div",type="source-child-carrier")
            block(child,slot)
        return
    elif tag in {"ul","ol"}:
        item=node(parent,"list",type=tag); source_id(source,item)
        if source.text and source.text.strip(): node(item,"head",rend="source-leading-text").text=source.text
        for child in source: block(child,item)
        return
    elif tag == "li": name,rend="item","source-li"
    elif tag == "table":
        item=node(parent,"table"); source_id(source,item)
        for child in source: block(child,item)
        return
    elif tag in {"tbody","thead","tfoot","colgroup"}:
        for child in source: block(child,parent)
        return
    elif tag == "col":
        item=node(parent,"milestone",unit="source-column")
        if source.get("span"): item.set("n",source.get("span"))
        if source.get("class"): item.set("rend",source.get("class"))
        return
    elif tag == "tr":
        item=node(parent,"row"); source_id(source,item)
        for child in source: block(child,item)
        return
    elif tag in {"td","th"}:
        name,rend="cell",""
    elif tag == "hr":
        item=node(parent,"milestone",unit="source-rule"); source_id(source,item)
        if source.get("class"): item.set("rend",source.get("class"))
        return
    elif tag == "img":
        if not source.get("src"): raise ValueError("source image without src")
        figure=node(parent,"figure",type="source-image")
        item=node(figure,"graphic",url=source.get("src"))
        if source.get("alt"): item.set("n",source.get("alt"))
        source_id(source,item)
        return
    elif tag == "br":
        item=node(parent,"p",rend="source-standalone-break"); node(item,"lb"); return
    elif tag == "a":
        item=node(parent,"p",rend="source-standalone-inline")
        ref=node(item,"ref",target=source.get("href")) if source.get("href") else node(item,"seg",rend="source-anchor")
        source_id(source,ref); inline(source,ref)
        return
    elif tag in INLINE:
        item=node(parent,"p",rend="source-standalone-inline")
        hi=node(item,"hi",rend=" ".join(x for x in (tag,source.get("class") or "") if x))
        source_id(source,hi); inline(source,hi)
        return
    else: raise ValueError(f"unaccounted block element {tag!r}")
    item=node(parent,name)
    if rend: item.set("rend",rend)
    source_id(source,item)
    if tag == "th": item.set("role","label")
    if source.get("colspan"): item.set("cols",source.get("colspan"))
    if tag in {"td","th"} and any(isinstance(c.tag,str) and c.tag not in INLINE | {"br","img","hr"} for c in source):
        if source.text: node(item,"p",rend="source-leading-text").text=source.text
        for child in source: block(child,item)
    else:
        inline(source,item)


def block(source: etree._Element, parent: etree._Element) -> None:
    _block_body(source, parent)
    if source.tail:
        if source.tail.strip():
            node(parent,"p",rend="source-interstitial-text").text=source.tail
        elif len(parent): parent[-1].tail = (parent[-1].tail or "") + source.tail
        elif parent.text is None: parent.text = source.tail
        else: parent.text += source.tail


def split_late_heads(parent: etree._Element) -> None:
    pos=0
    while pos < len(parent):
        child=parent[pos]
        if child.tag == f"{{{TEI}}}div":
            seen_content=False; split_at=None
            for idx,item in enumerate(child):
                if item.tag == f"{{{TEI}}}head" and seen_content:
                    split_at=idx; break
                if item.tag not in {f"{{{TEI}}}head",f"{{{TEI}}}milestone"}: seen_content=True
            if split_at is not None:
                sibling=etree.Element(f"{{{TEI}}}div",type="source-heading-segment")
                parent.insert(pos+1,sibling)
                for item in list(child)[split_at:]: sibling.append(item)
            split_late_heads(child)
        pos+=1


def _convert(manifest: SourceManifest) -> dict[str, bytes]:
    ebook,title=WORKS[manifest.record["work_id"]]
    profile=json.loads(manifest.authority_path("profile").read_text(encoding="utf-8"))
    archive_path=manifest.authority_path("retained-archive"); archive_bytes=archive_path.read_bytes()
    if sha(archive_bytes)!=profile["archive_sha256"]: raise ValueError("archive digest differs from source profile")
    with ZipFile(archive_path) as archive:
        if archive.testzip() is not None: raise ValueError("archive CRC failure")
        members=[{"path":x.filename,"bytes":x.file_size,"compressed_bytes":x.compress_size,"crc32":f"{x.CRC:08x}","sha256":sha(archive.read(x))} for x in archive.infolist() if not x.is_dir()]
        if members!=profile["archive_members"]: raise ValueError("archive envelope differs from source profile")
        html_name=profile["html_member"]; raw=archive.read(html_name)
    raw.decode("utf-8",errors="strict")
    source=html5lib.parse(raw,treebuilder="etree",namespaceHTMLElements=False); head=source.find(".//head"); body=source.find(".//body")
    if head is None or body is None: raise ValueError("source HTML lacks complete head/body")
    root=etree.Element(f"{{{TEI}}}TEI",nsmap={None:TEI}); root.set("{http://www.w3.org/XML/1998/namespace}lang","en")
    fd=node(node(node(root,"teiHeader"),"fileDesc"),"titleStmt"); node(fd,"title").text=title
    pub=node(root.find(f"{{{TEI}}}teiHeader/{{{TEI}}}fileDesc"),"publicationStmt"); node(pub,"p").text="Nonaccepted source reconstruction candidate; rights and publication remain separate."
    sd=node(root.find(f"{{{TEI}}}teiHeader/{{{TEI}}}fileDesc"),"sourceDesc"); node(sd,"p").text=f"Project Gutenberg eBook {ebook}; exact retained HTML archive is bound in the source manifest."
    text=node(root,"text"); front=node(text,"front"); main=node(text,"body"); back=node(text,"back")
    front_wrapper=node(front,"div",type="source-provider-header")
    main_wrapper=node(main,"div",type="source-book-content")
    back_wrapper=node(back,"div",type="source-provider-footer")
    for child in body:
        if not isinstance(child.tag,str): continue
        if child.tag=="header": block(child,front_wrapper)
        elif child.tag=="footer":
            license_div=node(back_wrapper,"div",type="source-provider-license")
            source_id(child,license_div)
            node(license_div,"ab",type="source-license-wrapper").text="".join(child.itertext())
        else:
            carrier=node(main_wrapper,"div",type="source-body-carrier")
            block(child,carrier)
    xml=etree.tostring(root,encoding="UTF-8",xml_declaration=True)
    account={"contract":"ocd-tyerman-gutenberg-html-source-accountability-v1","work_id":manifest.record["work_id"],"ebook_id":ebook,"archive_sha256":sha(archive_bytes),"archive_members":members,"html_member":profile["html_member"],"html_sha256":sha(raw),"html_body_carriers":len([x for x in body if isinstance(x.tag,str)]),"html_body_text_sha256":sha(" ".join("".join(body.itertext()).split()).encode()),"tei_sha256":sha(xml),"scope":"Complete single Gutenberg HTML edition. For multi-volume works, this candidate covers only the explicitly named volume; the companion volumes remain distinct candidates.","mapping":"All source body children are represented in order in readable TEI; provider header/footer are front/back; tables, lists, illustrations, links, emphasis, IDs, page labels, and textual units are preserved structurally.","html_head":"Metadata, styles, and wrapper remain hash-accounted in retained archive/profile; not part of the book text."}
    policy=json.loads(manifest.authority_path("policy").read_text(encoding="utf-8"))
    return {"README.source.md":manifest.authority_path("readme").read_bytes(),"content.tei.xml":xml,"source-accountability.json":enc(account),"provenance.json":enc(policy["provenance"]),"unresolved.jsonl":b"".join(enc(x) for x in policy["unresolved"])}


_convert.converter_id="ocd-l634-637-seven-tyerman-html-to-tei"
_convert.converter_version="1"
_convert.implementation_path=Path(__file__).resolve()
