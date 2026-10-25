"""Work-local structural repair grammar, derived from the frozen Tyerman mapper.

The three retained TEIs remain the starting components. The unchanged grammar
first checks their mapped trees, then located source-backed repairs are patched
into those components. No acquisition or unrelated Tyerman work is processed.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from zipfile import ZipFile
from copy import deepcopy
from urllib.parse import quote
import base64

MODE=False
MAPPED={}
RECORDS={}
PREFIX="urn:ocd:tyerman-wesley:source-fields:"

def mark(source,target):
    MAPPED[id(source)]=target


import html5lib
from lxml import etree
from ocd_kernel.reconstruction.contract import SourceManifest

TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
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
    mark(source,target)
    if source.get("id"):
        target.set(XML_ID, source.get("id"))


def page_identity(source: etree._Element, target: etree._Element) -> None:
    mark(source,target)
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
        if MODE and source.text and not source.text.strip(): item.text=source.text
        if source.text and source.text.strip(): node(item,"head",rend="source-leading-text").text=source.text
        for child in source: block(child,item)
        return
    elif tag == "li": name,rend="item","source-li"
    elif tag == "table":
        item=node(parent,"table"); source_id(source,item)
        if MODE: item.text=source.text
        for child in source: block(child,item)
        return
    elif tag in {"tbody","thead","tfoot","colgroup"}:
        if MODE and source.text:
            if len(parent): parent[-1].tail=(parent[-1].tail or "")+source.text
            else: parent.text=(parent.text or "")+source.text
        for child in source: block(child,parent)
        return
    elif tag == "col":
        item=node(parent,"milestone",unit="source-column"); mark(source,item)
        if source.get("span"): item.set("n",source.get("span"))
        if source.get("class"): item.set("rend",source.get("class"))
        return
    elif tag == "tr":
        item=node(parent,"row"); source_id(source,item)
        if MODE: item.text=source.text
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
        item=node(parent,"p",rend="source-standalone-break"); mark(source,node(item,"lb")); return
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


def fields(tree):
    return [(n.tag,dict(n.attrib),n.text,n.tail,len(n)) for n in tree.iter()]


def source_records(body):
    """All source fields; character ranges are over actual visible source text."""
    records=[];offset=0
    def walk(n,path,parent,position):
        nonlocal offset
        comment=not isinstance(n.tag,str)
        r=dict(path=path,parent=parent,position=position,tag='!comment' if comment else n.tag,
               attributes=dict(n.attrib),text_range=None,tail_range=None,comment=n.text if comment else None)
        records.append((n,r))
        if not comment and n.text is not None:
            r['text_range']=[offset,len(n.text)];offset+=len(n.text)
        for i,c in enumerate(n):walk(c,path+'/'+str(i),path,i)
        if n.tail is not None:
            r['tail_range']=[offset,len(n.tail)];offset+=len(n.tail)
    walk(body,'body',None,0)
    return records,offset


def visible_text(tree):
    def walk(n):
        if isinstance(n.tag,str):
            yield n.text or ''
            for c in n:
                yield from walk(c)
                yield c.tail or ''
    return ''.join(walk(tree))


def mapped_text(body,repair=False):
    global MODE,MAPPED
    MODE=repair;MAPPED={}
    text=etree.Element('{'+TEI+'}text')
    front=node(text,'front');main=node(text,'body');back=node(text,'back')
    fw=node(front,'div',type='source-provider-header');mw=node(main,'div',type='source-book-content');bw=node(back,'div',type='source-provider-footer')
    MAPPED[id(body)]=text
    for child in body:
        if not isinstance(child.tag,str):
            if repair and child.tail:
                owner=mw[-1] if len(mw) else fw[-1]
                owner.tail=(owner.tail or '')+child.tail
            continue
        if child.tag=='header':block(child,fw)
        elif child.tag=='footer':
            if repair:block(child,bw)
            else:
                license_div=node(bw,'div',type='source-provider-license');source_id(child,license_div)
                node(license_div,'ab',type='source-license-wrapper').text=''.join(child.itertext())
        else:
            carrier=node(mw,'div',type='source-body-carrier');block(child,carrier)
    if repair and body.text:fw.text=body.text
    return text,dict(MAPPED)


def patch_existing(old,new):
    """Patch the retained component in place and record every changed field."""
    patches=[]
    def visit(a,b,path):
        if a.tag!=b.tag or len(a)!=len(b) or [c.tag for c in a]!=[c.tag for c in b]:
            patches.append(dict(path=path,kind='subtree',after_sha256=sha(enc(fields(b)))))
            a.tag=b.tag;a.attrib.clear();a.attrib.update(b.attrib);a.text=b.text;a.tail=b.tail
            for c in list(a):a.remove(c)
            for c in b:a.append(deepcopy(c))
            return
        for key in ['attributes','text','tail']:
            av=dict(a.attrib) if key=='attributes' else getattr(a,key)
            bv=dict(b.attrib) if key=='attributes' else getattr(b,key)
            if av!=bv:
                patches.append(dict(path=path,kind=key,after_sha256=sha(enc(bv))))
                if key=='attributes':a.attrib.clear();a.attrib.update(b.attrib)
                else:setattr(a,key,bv)
        for i,(x,y) in enumerate(zip(a,b,strict=True)):visit(x,y,path+[i])
    visit(old,new,[])
    if fields(old)!=fields(new):raise ValueError('Retained component patch is incomplete')
    return old,patches


def repair_component(old_root,body,archive,volume):
    baseline,_=mapped_text(body)
    baseline=etree.fromstring(etree.tostring(baseline))
    retained=old_root.find('{'+TEI+'}text')
    if fields(baseline)!=fields(retained):raise ValueError('Frozen component differs from its declared source mapping')
    new,mapping=mapped_text(body,True)
    records,length=source_records(body)
    if visible_text(new)!=visible_text(body):raise ValueError('Direct source text and tail joins differ before repairs')
    owned={}
    parents={id(c):n for n in body.iter() for c in n}
    for source,record in records:
        owner=source
        while id(owner) not in mapping:owner=parents[id(owner)]
        target=mapping[id(owner)];owned.setdefault(target,[]).append(record)
        if source is owner:
            attrs=source.attrib
            if attrs.get('lang'):target.set('{http://www.w3.org/XML/1998/namespace}lang',attrs['lang'])
            if attrs.get('rowspan'):target.set('rows',attrs['rowspan'])
            if source.tag in HEADING and 'title' in attrs:
                target.set('n',attrs['title'])
            # Classes/styles/titles remain literal in the source field annotation.
            # Abbreviation titles are source-attested alternative expansions.
            if source.tag=='abbr' and 'title' in attrs:
                parent=target.getparent();index=parent.index(target);tail=target.tail;target.tail=None
                target.tag='{'+TEI+'}abbr'
                choice=etree.Element('{'+TEI+'}choice');choice.tail=tail;parent.remove(target);parent.insert(index,choice);choice.append(target)
                node(choice,'expan').text=attrs['title']
            if source.tag=='img':
                member=attrs['src'];pixels=archive.read(member)
                target.set('url','data:image/jpeg;base64,'+base64.b64encode(pixels).decode('ascii'))
                target.set('corresp','urn:ocd:retained-archive-member:sha256:'+sha(Path(archive.filename).read_bytes())+':'+quote(member,safe=''))
                target.set('n',attrs.get('alt',''))
    for target,rows in owned.items():
        if target.get('ana') is not None:raise ValueError('Existing annotation collision')
        target.set('ana',PREFIX+quote(json.dumps(rows,ensure_ascii=False,sort_keys=True,separators=(',',':')),safe=''))
    ids={n.get(XML_ID) for n in new.iter() if n.get(XML_ID)}
    for n in new.iter():
        if n.get(XML_ID):n.set(XML_ID,'v'+str(volume)+'--'+n.get(XML_ID))
        if n.tag=='{'+TEI+'}ref' and n.get('target','').startswith('#'):
            if n.get('target')[1:] not in ids:raise ValueError('Unresolved source fragment target')
            n.set('target','#v'+str(volume)+'--'+n.get('target')[1:])
    new.set('{http://www.w3.org/XML/1998/namespace}id','wesley-volume-'+str(volume))
    new.set('{http://www.w3.org/XML/1998/namespace}lang','en')
    # XML serialization has no distinct empty versus absent character slot.
    # Compare exact parsed fields on both sides, retaining source distinctions
    # separately in the independently checked source field annotations.
    new=etree.fromstring(etree.tostring(new))
    repaired,patches=patch_existing(deepcopy(retained),new)
    return repaired,patches,[r for _,r in records]


