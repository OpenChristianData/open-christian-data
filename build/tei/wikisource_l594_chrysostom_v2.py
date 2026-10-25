"""Source-bound v2 Wikisource export reconstruction for L594."""
from __future__ import annotations
import hashlib,json,re
from pathlib import Path
from typing import Mapping
from html import unescape
from lxml import etree
from ocd_kernel.reconstruction.contract import SourceManifest

TEI="http://www.tei-c.org/ns/1.0"; XML="http://www.w3.org/XML/1998/namespace"; MW="http://www.mediawiki.org/xml/export-0.11/"
T="{"+TEI+"}"; X="{"+XML+"}"; M="{"+MW+"}"
CONVERTER_ID="ocd-wikisource-l594-chrysostom-export-to-p5"; CONVERTER_VERSION="3"
def _sha(b:bytes)->str:return hashlib.sha256(b).hexdigest()
def _json(v:object)->bytes:return (json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode("utf-8")
def _split_args(s:str)->list[str]:
    out=[];start=0;depth=0;i=0
    while i<len(s):
        if s.startswith("{{",i):depth+=1;i+=2;continue
        if s.startswith("}}",i) and depth:depth-=1;i+=2;continue
        if s[i]=="|" and depth==0:out.append(s[start:i]);start=i+1
        i+=1
    out.append(s[start:]);return out
def _template_end(s:str,start:int)->int:
    depth=0;i=start
    while i<len(s)-1:
        if s.startswith("{{",i):depth+=1;i+=2;continue
        if s.startswith("}}",i):
            depth-=1;i+=2
            if depth==0:return i
            continue
        i+=1
    raise ValueError("unterminated retained page template")
def _plain(s:str)->str:
    s=re.sub(r"<noinclude>.*?</noinclude>","",s,flags=re.I|re.S);out=[];i=0
    while i<len(s):
        if s.startswith("{{",i):
            end=_template_end(s,i);parts=_split_args(s[i+2:end-2]);name=parts[0].strip().lower().replace("_"," ");args=parts[1:]
            if name in {"dhr","rule"}: value="\n"
            elif not args:value=""
            else:value=_plain(args[-1] if name=="fs" else args[0] if name in {"sp","sm","fine","smaller","x-smaller","xx-larger","x-larger","xx-larger","blackletter","c","center","border2"} else args[-1])
            out.append(value);i=end;continue
        if s.startswith("<br",i):
            end=s.find(">",i);out.append("\n");i=len(s) if end<0 else end+1;continue
        if s[i]=="<":
            end=s.find(">",i);i=len(s) if end<0 else end+1;continue
        out.append(s[i]);i+=1
    return unescape("".join(out))
def _page(x:etree._Element,title:str)->tuple[etree._Element,etree._Element,str]:
    p=next((p for p in x.findall(M+"page") if p.findtext(M+"title")==title),None)
    if p is None:raise ValueError("required retained export page missing: "+title)
    rev=p.find(M+"revision");node=rev.find(M+"text") if rev is not None else None
    if rev is None or node is None:raise ValueError("incomplete export revision: "+title)
    return p,rev,node.text or ""
def _indexed_scan_position_count(pagelist: str) -> int:
    entries = [
        (int(start), int(end) if end else int(start))
        for start, end in re.findall(r"(?m)^\s*(\d+)(?:\s*to\s*(\d+))?\s*=", pagelist)
    ]
    if not entries or entries[0][0] != 1:
        raise ValueError("Index pagelist does not begin at scan position 1")
    previous_end = 0
    for start, end in entries:
        if start <= previous_end or end < start:
            raise ValueError("Index pagelist has overlapping or reversed scan ranges")
        previous_end = end
    return previous_end


def _retained_scan_positions(transclusion: Mapping[str, object]) -> list[int]:
    titles = transclusion["included_page_titles"]
    positions = []
    for title in titles:
        match = re.fullmatch(r"Page:.*/(\d+)", title)
        if match is None:
            raise ValueError("retained Page title has no numeric scan position")
        positions.append(int(match.group(1)))
    expected = list(range(int(transclusion["from_page"]), int(transclusion["to_page"]) + 1))
    if positions != expected:
        raise ValueError("retained Page titles differ from the declared scan interval")
    return positions


def _untranscribed_ranges(scan_count: int, retained: list[int]) -> list[tuple[int, int]]:
    if scan_count < 1 or retained != sorted(set(retained)) or any(p < 1 or p > scan_count for p in retained):
        raise ValueError("retained scan positions are invalid")
    ranges = []
    next_position = 1
    for position in retained:
        if next_position < position:
            ranges.append((next_position, position - 1))
        next_position = position + 1
    if next_position <= scan_count:
        ranges.append((next_position, scan_count))
    return ranges


def _add_scan_gap(parent: etree._Element, first: int, last: int) -> None:
    etree.SubElement(
        parent,
        T + "gap",
        reason="not-transcribed",
        n=f"{first}-{last}",
        quantity=str(last - first + 1),
        unit="scan-position",
    )


def _convert(manifest:SourceManifest)->Mapping[str,bytes]:
    raw=manifest.authority_path("official-source-member").read_bytes();receipt=json.loads(manifest.authority_path("acquisition-receipt").read_bytes());profile=json.loads(manifest.authority_path("profile").read_bytes());policy=json.loads(manifest.authority_path("policy").read_bytes())
    if _sha(raw)!=receipt["member"]["sha256"] or _sha(raw)!=profile["source_sha256"]:raise ValueError("L594 export identity drift")
    parser=etree.XMLParser(resolve_entities=False,no_network=True,huge_tree=True);source=etree.fromstring(raw,parser);records=source.findall(M+"page")
    if len(records)!=81 or len(records)!=profile["export_record_count"]:raise ValueError("L594 export record count differs")
    indexed={r["title"]:r for r in profile["records"]}; observed=[]
    for p in records:
        title=p.findtext(M+"title");rev=p.find(M+"revision");node=rev.find(M+"text") if rev is not None else None
        if not title or rev is None or node is None:raise ValueError("incomplete export record")
        text=node.text or ""; rev_id=rev.findtext(M+"id") or ""; data=text.encode("utf-8")
        item=indexed.get(title)
        if item is None or item["revision_id"]!=rev_id or item["text_sha256"]!=_sha(data) or item["text_bytes"]!=int(node.get("bytes",len(data))):raise ValueError("source page/revision/text inventory drift: "+title)
        observed.append(title)
    if observed!=[r["title"] for r in profile["records"]]:raise ValueError("source page order differs")
    root_title=receipt["work"];page_title=profile["transclusion"]["included_page_titles"][0];index_title=profile["transclusion"]["index_page_title"]
    _,root_rev,root_text=_page(source,root_title);_,page_rev,page_text=_page(source,page_title);_,index_rev,index_text=_page(source,index_title)
    sel=profile["transclusion"]["source_selector"]
    if sel not in root_text or profile["transclusion"]["index_pagelist_raw"] not in index_text or "|Transclusion=yes" not in index_text:raise ValueError("root transclusion or index scope differs")
    scan_count=_indexed_scan_position_count(profile["transclusion"]["index_pagelist_raw"])
    retained_positions=_retained_scan_positions(profile["transclusion"])
    page_gaps=_untranscribed_ranges(scan_count,retained_positions)
    out=etree.Element(T+"TEI",nsmap={None:TEI});out.set(X+"id",profile["work_id"])
    header=etree.SubElement(out,T+"teiHeader");fd=etree.SubElement(header,T+"fileDesc");ts=etree.SubElement(fd,T+"titleStmt");etree.SubElement(ts,T+"title",type="main").text=root_title
    author=etree.SubElement(ts,T+"author",role="attributed");author.text="John Chrysostom";etree.SubElement(author,T+"note").text="Attribution as stated in the Wikisource root and Index records."
    resp=etree.SubElement(ts,T+"respStmt");etree.SubElement(resp,T+"resp").text="Translator";etree.SubElement(resp,T+"name").text="Anonymous"
    pub=etree.SubElement(fd,T+"publicationStmt");etree.SubElement(pub,T+"p").text="Nonaccepted candidate reconstructing the retained Wikisource export; contributor attribution and licensing conditions are described in README.source.md. Publication is not authorized."
    sd=etree.SubElement(fd,T+"sourceDesc");bibl=etree.SubElement(sd,T+"biblStruct");mon=etree.SubElement(bibl,T+"monogr");etree.SubElement(mon,T+"title",type="main").text=root_title;etree.SubElement(mon,T+"author",role="attributed").text="John Chrysostom";etree.SubElement(mon,T+"editor").text="Anonymous translator";im=etree.SubElement(mon,T+"imprint");etree.SubElement(im,T+"pubPlace").text="London";etree.SubElement(im,T+"publisher").text="Joseph Masters";etree.SubElement(im,T+"date",when="1866").text="1866";etree.SubElement(bibl,T+"note",type="source-index-page").text="Wikisource index page: "+index_title
    ed=etree.SubElement(header,T+"encodingDesc");etree.SubElement(etree.SubElement(ed,T+"projectDesc"),T+"p").text="The retained member is a MediaWiki XML export. Only its title page, source wikitext, export revision inventory, and explicit missing transclusions are represented; no remote template execution or absent print text is inferred."
    prof=etree.SubElement(header,T+"profileDesc");lang=etree.SubElement(etree.SubElement(prof,T+"langUsage"),T+"language",ident="en");lang.text="English"
    text=etree.SubElement(out,T+"text");front=etree.SubElement(text,T+"front")
    for first,last in page_gaps:
        if last < retained_positions[0]: _add_scan_gap(front,first,last)
    tp=etree.SubElement(front,T+"titlePage",n=str(retained_positions[0]));readable=_plain(page_text)
    title_block=etree.SubElement(tp,T+"docTitle")
    for i,line in enumerate(part.strip() for part in readable.splitlines() if part.strip()):
        if i<5: etree.SubElement(title_block,T+"titlePart",type="source-line").text=line
        elif i==5: etree.SubElement(title_block,T+"titlePart",type="decoration").text=line
        elif i==6: etree.SubElement(tp,T+"byline").text=line
        elif i==7: etree.SubElement(tp,T+"docImprint").append(etree.Element(T+"pubPlace")); tp[-1][-1].text=line
        elif i in (8,9):
            imprint=tp.find(T+"docImprint")
            if imprint is None: imprint=etree.SubElement(tp,T+"docImprint")
            etree.SubElement(imprint,T+"publisher").text=line
        else:
            imprint=tp.find(T+"docImprint")
            if imprint is None: imprint=etree.SubElement(tp,T+"docImprint")
            etree.SubElement(imprint,T+"docDate",when="1866").text=line
    body=etree.SubElement(text,T+"body")
    for first,last in page_gaps:
        if first > retained_positions[-1]: _add_scan_gap(body,first,last)
    d=etree.SubElement(body,T+"div",type="wikisource-root-work-page");etree.SubElement(d,T+"head").text=root_title;etree.SubElement(d,T+"p").text=f"The retained root page transcludes only PDF page {retained_positions[0]} (the title page) from the named Index. Its two linked subordinate pages are not in this export."
    refs=etree.SubElement(d,T+"list",type="linked-subpages")
    base="https://en.wikisource.org/wiki/"+root_title.replace(" ","_")
    for link in profile["transclusion"]["linked_subpages"]:
        item=etree.SubElement(refs,T+"item");target=base+link.replace(" ","_");etree.SubElement(item,T+"ref",target=target).text=link;etree.SubElement(item,T+"gap",reason="source-not-retained",extent="unknown")
    etree.SubElement(d,T+"p").text=f"The Index pagelist identifies {scan_count} print scan positions; this export contains {len(retained_positions)} Page: transcription only."
    back=etree.SubElement(text,T+"back");idx=etree.SubElement(back,T+"div",type="source-index-page");etree.SubElement(idx,T+"head").text=index_title;etree.SubElement(idx,T+"ab",type="wikisource-index-wikitext",attrib={X+"space":"preserve"}).text=index_text
    # Keep exact root and included-page wikitext as a readable source witness in the back matter.
    src=etree.SubElement(back,T+"div",type="wikisource-source-records");etree.SubElement(src,T+"head").text="Exact retained root and Page 7 source wikitext";etree.SubElement(src,T+"ab",type="root-wikitext",attrib={X+"space":"preserve"}).text=root_text;etree.SubElement(src,T+"ab",type="page-7-wikitext",attrib={X+"space":"preserve"}).text=page_text
    content=etree.tostring(out,encoding="UTF-8",xml_declaration=True,pretty_print=True)
    scan_position_accounting={"index_page_title":index_title,"indexed_positions":{"first":1,"last":scan_count,"count":scan_count},"retained_positions":[{"page_title":title,"position":position} for title,position in zip(profile["transclusion"]["included_page_titles"],retained_positions)],"untranscribed_ranges":[{"first":first,"last":last,"count":last-first+1} for first,last in page_gaps],"untranscribed_count":sum(last-first+1 for first,last in page_gaps)}
    account={"contract":"ocd-wikisource-export-accountability-v1","source_id":receipt["source_id"],"work_id":profile["work_id"],"textual_form_id":profile["textual_form_id"],"edition_id":profile["edition_id"],"acquisition_id":profile["acquisition_id"],"work_catalog_link":profile["work_catalog_link"],"source_sha256":_sha(raw),"source_member_count":1,"export_record_count":len(profile["records"]),"export_records":profile["records"],"source_root":{"title":root_title,"revision_id":root_rev.findtext(M+"id"),"text_sha256":_sha(root_text.encode("utf-8"))},"transclusion":profile["transclusion"],"scan_position_accounting":scan_position_accounting,"tei_sha256":_sha(content),"tei_bytes":len(content),"record_disposition":{"work":1,"proofread-page":1,"index":1,"support":sum(r["role"]=="support" for r in profile["records"])}}
    return {"README.source.md":manifest.authority_path("readme").read_bytes(),"content.tei.xml":content,"provenance.json":_json(policy["provenance"]),"source-accountability.json":_json(account),"unresolved.jsonl":b"".join(_json(x) for x in policy["unresolved"])}
_convert.converter_id=CONVERTER_ID;_convert.converter_version=CONVERTER_VERSION;_convert.implementation_path=Path(__file__).resolve()
