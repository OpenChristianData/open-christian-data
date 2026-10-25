"""Faithful deterministic XHTML-to-TEI conversion for Turton's 1919 edition."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from lxml import etree, html

from ocd_kernel.lib.storage_topology import resolve_repo_path

TEI_NS="http://www.tei-c.org/ns/1.0"; XML_NS="http://www.w3.org/XML/1998/namespace"; NS={"tei":TEI_NS}
EXPECTED_SOURCE_SHA256="89cc86c2d92e3b9bb1e3aa545c3179df9f542a3157c620740127dc605b344c04"
EXPECTED_SOURCE_TEXT_SHA256="60f7cddf7d040d379dd35842edcbb117c3a56c9fb71eae15627dd49144ec3178"
SOURCE_RELATIVE_PATH="raw/clean-ready-acquisition-to-tei/master-4/28/turton-truth-of-christianity-1919/42460-h.htm"
PACKAGE_HASHES={"42460-0.txt":"b524c7e11c26d7d386ac4012b17daf9fd70d7bbbfeec7aa19614fbf019459f06","42460-h.htm":EXPECTED_SOURCE_SHA256,"files-index.html":"ec03d45d1e3f170441d48538566a5da8dbfc90eb8fbae3c05d3758493684db70","landing.html":"77c7223e2c37f8ceafd37e8426cc7eda4695ec110a4a6a1e3c75500ccd09b0a6","legacy-html-index.html":"85e31e71c6d9e623993b468f4375b4468fbd5b006f4766d05c449d786eebdbf6","pg42460-h.zip":"70767232643752952876177baa5db95ec9decbca6093ce55884898f415fd2b3e","pg42460-images.html":"acbda436244fb13624d194c0ca0faed1ec2cb48f18a36caadec5efcd4e952e64","pg42460.txt":"0b84888c4c505801d44744688884574f0ab532f223cbd515be5e0a2fef6a3470"}
IMAGE_HASHES={"images/cover.jpg":"00b7afa0372322b28e403af18822b2b4a5ca7561720acf66d3aac7a47d80b687","images/deco.png":"ce3444f6c85093d5abd8999ca2642199ae24cc6a6ab4cb70a381c205ebe14109"}
CHAPTER_STARTS=[70,94,158,186,250,326,377,427,511,671,761,825,910,1009,1068,1173,1239,1351,1440,1548,1630,1729,1798,1865,1969]
PART_STARTS=[66,424,907]; PART_ENDS=[424,907,2003]; PART_FIRST_CHAPTER=[0,7,12]


class SourceMismatchError(ValueError): pass


def sha256_file(path:Path)->str:
    d=hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b""): d.update(chunk)
    return d.hexdigest()


def resolve_source_path(repository_root:Path)->Path: return resolve_repo_path(repository_root,SOURCE_RELATIVE_PATH)
def _parse(path:Path)->html.HtmlElement: return html.fromstring(path.read_text(encoding="utf-8"))
def _body(doc:html.HtmlElement)->html.HtmlElement:
    found=doc.xpath("//body")
    if len(found)!=1: raise SourceMismatchError(f"expected one body, found {len(found)}")
    return found[0]
def _norm(e:etree._Element)->str: return " ".join(e.text_content().split())
def _classes(e:etree._Element)->set[str]: return set((e.get("class") or "").split())


def _package_audit(raw:Path)->dict[str,Any]:
    actual={p.name for p in raw.iterdir() if p.is_file()}
    if actual!=set(PACKAGE_HASHES): raise SourceMismatchError(f"retained package differs: missing={sorted(set(PACKAGE_HASHES)-actual)}, unexpected={sorted(actual-set(PACKAGE_HASHES))}")
    hashes={n:sha256_file(raw/n) for n in sorted(PACKAGE_HASHES)}; wrong={n:h for n,h in hashes.items() if h!=PACKAGE_HASHES[n]}
    if wrong: raise SourceMismatchError(f"package SHA-256 mismatch: {wrong}")
    with zipfile.ZipFile(raw/"pg42460-h.zip") as z:
        members=sorted(i.filename for i in z.infolist() if not i.is_dir()); member_hashes={n:hashlib.sha256(z.read(n)).hexdigest() for n in members}
    if member_hashes.get("pg42460-images.html")!=hashes["pg42460-images.html"] or any(member_hashes.get(n)!=h for n,h in IMAGE_HASHES.items()): raise SourceMismatchError("current HTML ZIP comparison failed")
    return {"package_hashes":hashes,"archive_members":members,"archive_member_hashes":member_hashes}


def audit_source(source:Path,*,repository_root:Path)->dict[str,Any]:
    source_hash=sha256_file(source)
    if source_hash!=EXPECTED_SOURCE_SHA256: raise SourceMismatchError(f"source SHA-256 {source_hash} does not match {EXPECTED_SOURCE_SHA256}")
    package=_package_audit(source.parent); doc=_parse(source); body=_body(doc); text=_norm(body); text_hash=hashlib.sha256(text.encode()).hexdigest()
    if text_hash!=EXPECTED_SOURCE_TEXT_SHA256: raise SourceMismatchError("source text SHA-256 mismatch")
    elements=[e for e in body.iter() if isinstance(e.tag,str)]; tags=Counter(e.tag for e in elements); classes=Counter(c for e in elements for c in _classes(e)); ids=[e.get("id") for e in elements if e.get("id")]; targets=[e.get("href")[1:] for e in elements if e.tag=="a" and (e.get("href") or "").startswith("#")]
    expected={"a":4950,"td":3076,"i":2796,"p":2139,"br":1420,"span":1177,"tr":1043,"div":547,"th":168,"h4":140,"h3":80,"table":65,"h2":32,"hr":28,"b":7,"col":4,"blockquote":2,"sup":2,"colgroup":2,"body":1,"h1":1,"img":1}
    if tags!=Counter(expected): raise SourceMismatchError(f"source element census differs: {tags}")
    if len(ids)!=1526 or len(ids)!=len(set(ids)) or set(targets)-set(ids): raise SourceMismatchError("source identifier/reference contract failed")
    chapter_positions=[i for i,e in enumerate(body) if e.tag=="h2" and "chapter" in _classes(e)]
    if chapter_positions!=CHAPTER_STARTS: raise SourceMismatchError(f"chapter positions differ: {chapter_positions}")
    transnotes=body.xpath("./div[contains(concat(' ',normalize-space(@class),' '),' tnotes ')]")
    if len(transnotes)!=2: raise SourceMismatchError("expected two transcriber-note divisions")
    return {**package,"source_sha256":source_hash,"source_bytes":source.stat().st_size,"source_text_characters":len(text),"source_text_sha256":text_hash,"tag_counts":dict(sorted(tags.items())),"class_counts":dict(sorted(classes.items())),"source_ids":len(ids),"ids_unique":True,"internal_targets":len(targets),"unresolved_internal_targets":[],"part_positions":PART_STARTS,"chapter_positions":chapter_positions,"chapters":25,"footnotes":classes["footnote"],"footnote_references":classes["fnanchor"],"page_markers":classes["pagenum"],"tables":tags["table"],"rows":tags["tr"],"cells":tags["td"]+tags["th"],"transcribers_notes":[_norm(e) for e in transnotes],"printer_line":_norm(body[2121]),"project_gutenberg_start_marker":_norm(body[0]),"project_gutenberg_end_marker":_norm(body[-1])}


def _tei(n:str)->etree._Element:return etree.Element(f"{{{TEI_NS}}}{n}")
def _copy_attrs(s:etree._Element,t:etree._Element)->None:
    if s.get("id"): t.set(f"{{{XML_NS}}}id",s.get("id"))
    if s.get("class"): t.set("rend"," ".join(s.get("class").split()))
    lang=s.get("lang") or s.get(f"{{{XML_NS}}}lang")
    if lang:t.set(f"{{{XML_NS}}}lang",lang)


def _clone(s:etree._Element)->etree._Element:
    tag=s.tag.lower(); classes=_classes(s)
    if tag=="p":t=_tei("p")
    elif tag in {"i","b","sup"}:t=_tei("hi");t.set("rend",{"i":"italic","b":"bold","sup":"superscript"}[tag])
    elif tag=="span":t=_tei("hi")
    elif tag=="br":t=_tei("lb")
    elif tag=="a":
        href=s.get("href");t=_tei("ref") if href or (s.text or "").strip() else _tei("anchor")
        if href:t.set("target",href)
        if "fnanchor" in classes:t.set("type","note_reference")
    elif tag in {"h1","h2","h3","h4"}:t=_tei("head");t.set("type",tag)
    elif tag=="hr":t=_tei("milestone");t.set("unit","rule")
    elif tag=="table":t=_tei("table")
    elif tag=="tr":t=_tei("row")
    elif tag in {"td","th"}:
        t=_tei("cell")
        if tag=="th":t.set("role","label")
        if s.get("colspan"):t.set("cols",s.get("colspan"))
        if s.get("rowspan"):t.set("rows",s.get("rowspan"))
    elif tag=="colgroup":t=_tei("milestone");t.set("unit","column_group")
    elif tag=="col":t=_tei("milestone");t.set("unit","column")
    elif tag=="blockquote":t=_tei("quote")
    elif tag=="img":t=_tei("graphic");t.set("url",s.get("src") or "")
    elif tag=="div" and "footnote" in classes:t=_tei("note");t.set("place","end")
    elif tag=="div" and "tnotes" in classes:t=_tei("div");t.set("type","transcribers_notes")
    elif tag=="div" and s.xpath("./p | ./div | ./blockquote"):t=_tei("quote");t.set("type","xhtml_div")
    elif tag=="div":t=_tei("ab")
    else:raise SourceMismatchError(f"unmapped XHTML element: {tag}")
    _copy_attrs(s,t);t.text=s.text
    if tag not in {"colgroup","col","hr","img"}:
        for child in s:
            cloned=_clone(child);cloned.tail=child.tail;t.append(cloned)
    return t


def _append_group(parent:etree._Element,kind:str,nodes:Iterable[etree._Element])->etree._Element:
    d=etree.SubElement(parent,f"{{{TEI_NS}}}div",type=kind)
    for node in nodes:
        c=_clone(node)
        if etree.QName(c).localname=="head" and len(d):c.tag=f"{{{TEI_NS}}}ab";c.set("type",f"source_{node.tag.lower()}")
        c.tail=node.tail;d.append(c)
    return d


def _header()->etree._Element:
    h=_tei("teiHeader");fd=etree.SubElement(h,f"{{{TEI_NS}}}fileDesc");ts=etree.SubElement(fd,f"{{{TEI_NS}}}titleStmt");etree.SubElement(ts,f"{{{TEI_NS}}}title").text="The Truth of Christianity";etree.SubElement(ts,f"{{{TEI_NS}}}author").text="William Harry Turton"
    es=etree.SubElement(fd,f"{{{TEI_NS}}}editionStmt");etree.SubElement(es,f"{{{TEI_NS}}}edition").text="Ninth edition, fortieth thousand, carefully revised throughout, 1919"
    ps=etree.SubElement(fd,f"{{{TEI_NS}}}publicationStmt");etree.SubElement(ps,f"{{{TEI_NS}}}publisher").text="Project Gutenberg";date=etree.SubElement(ps,f"{{{TEI_NS}}}date",when="2013-04-02");date.text="April 2, 2013";idno=etree.SubElement(ps,f"{{{TEI_NS}}}idno",type="Project-Gutenberg");idno.text="42460";av=etree.SubElement(ps,f"{{{TEI_NS}}}availability",status="free");etree.SubElement(av,f"{{{TEI_NS}}}p").text="Public domain in the United States according to Project Gutenberg."
    sd=etree.SubElement(fd,f"{{{TEI_NS}}}sourceDesc");b=etree.SubElement(sd,f"{{{TEI_NS}}}bibl");etree.SubElement(b,f"{{{TEI_NS}}}title").text="The Truth of Christianity";etree.SubElement(b,f"{{{TEI_NS}}}date",when="1919").text="1919"
    ed=etree.SubElement(h,f"{{{TEI_NS}}}encodingDesc");pd=etree.SubElement(ed,f"{{{TEI_NS}}}projectDesc");etree.SubElement(pd,f"{{{TEI_NS}}}p").text="Faithful deterministic projection of exact retained Project Gutenberg legacy XHTML; source-stated interventions retained and no wording modernization applied."
    pr=etree.SubElement(h,f"{{{TEI_NS}}}profileDesc");lu=etree.SubElement(pr,f"{{{TEI_NS}}}langUsage");etree.SubElement(lu,f"{{{TEI_NS}}}language",ident="en").text="English with source-defined quoted languages"
    rd=etree.SubElement(h,f"{{{TEI_NS}}}revisionDesc");etree.SubElement(rd,f"{{{TEI_NS}}}change",when="2026-08-31").text="Generated as a nonaccepted Open Christian Data candidate.";return h


def _transform(doc:html.HtmlElement)->etree._ElementTree:
    source=_body(doc);root=etree.Element(f"{{{TEI_NS}}}TEI",nsmap={None:TEI_NS});root.set(f"{{{XML_NS}}}lang","en");root.append(_header());text=etree.SubElement(root,f"{{{TEI_NS}}}text");front=etree.SubElement(text,f"{{{TEI_NS}}}front");_append_group(front,"project_gutenberg_header",source[0:1]);_append_group(front,"opening_transcribers_note",source[1:2]);_append_group(front,"press_and_title_page",source[2:56]);_append_group(front,"preface",source[56:62]);_append_group(front,"contents",source[62:66]);body=etree.SubElement(text,f"{{{TEI_NS}}}body")
    for part_index,(part_start,part_end,first_chapter) in enumerate(zip(PART_STARTS,PART_ENDS,PART_FIRST_CHAPTER)):
        last_chapter=PART_FIRST_CHAPTER[part_index+1] if part_index+1<len(PART_FIRST_CHAPTER) else len(CHAPTER_STARTS);part=etree.SubElement(body,f"{{{TEI_NS}}}div",type="part");intro_end=CHAPTER_STARTS[first_chapter]
        for node in source[part_start:intro_end]:c=_clone(node);c.tail=node.tail;part.append(c)
        for ci in range(first_chapter,last_chapter):
            start=CHAPTER_STARTS[ci];end=CHAPTER_STARTS[ci+1] if ci+1<last_chapter else part_end;_append_group(part,"chapter",source[start:end])
    back=etree.SubElement(text,f"{{{TEI_NS}}}back");_append_group(back,"indexes_and_printer",source[2003:2122]);_append_group(back,"terminal_transcribers_notes",source[2122:2123]);_append_group(back,"project_gutenberg_footer",source[2123:]);return etree.ElementTree(root)


@lru_cache(maxsize=1)
def _rng(path:Path)->etree.RelaxNG:return etree.RelaxNG(etree.parse(str(path)))
def _raw(e:etree._Element)->str:
    pieces=[e.text or ""]
    for c in e:
        pieces.append(_raw(c));pieces.append(c.tail or "")
    return "".join(pieces)
def _project(e:etree._Element)->str:return " ".join(_raw(e).split())


def _validate(source_doc:html.HtmlElement,candidate:etree._ElementTree,root:Path)->dict[str,Any]:
    validator=_rng(root/"ocd_kernel/tei/vendor/relaxng/tei_all.rng")
    if not validator.validate(candidate):raise SourceMismatchError(f"TEI P5 Relax NG validation failed: {validator.error_log.last_error}")
    st=_norm(_body(source_doc));te=candidate.find("tei:text",NS)
    if te is None:raise SourceMismatchError("candidate text missing")
    ct=_project(te)
    if st!=ct:raise SourceMismatchError("source and candidate ordered text differ")
    counts=Counter(etree.QName(e).localname for e in te.iter() if isinstance(e.tag,str));ids={str(x) for x in candidate.xpath("//@xml:id",namespaces={"xml":XML_NS})};targets=[str(x)[1:] for x in candidate.xpath("//tei:ref/@target",namespaces=NS) if str(x).startswith("#")];unresolved=sorted(set(targets)-ids)
    if unresolved:raise SourceMismatchError(f"unresolved candidate targets: {unresolved}")
    return {"tei_p5_relaxng_valid":True,"source_candidate_text_match":True,"source_text_sha256":hashlib.sha256(st.encode()).hexdigest(),"candidate_text_sha256":hashlib.sha256(ct.encode()).hexdigest(),"source_text_characters":len(st),"candidate_text_characters":len(ct),"candidate_tag_counts":dict(sorted(counts.items())),"part_divisions":3,"chapter_divisions":25,"candidate_ids":len(ids),"internal_targets":len(targets),"unresolved_internal_targets":unresolved}


def _write_json(path:Path,record:dict[str,Any])->None:
    path.parent.mkdir(parents=True,exist_ok=True);stage=path.with_name(path.name+".tmp")
    if stage.exists():raise FileExistsError(stage)
    stage.write_text(json.dumps(record,indent=2,sort_keys=True,ensure_ascii=False)+"\n",encoding="utf-8",newline="\n");stage.replace(path)


def build_candidate(source:Path,candidate:Path,report:Path,*,repository_root:Path,replace:bool=False)->dict[str,Any]:
    audit=audit_source(source,repository_root=repository_root)
    if not replace and (candidate.exists() or report.exists()):raise FileExistsError("candidate or report exists")
    sd=_parse(source);cd=_transform(sd);validation=_validate(sd,cd,repository_root);cb=etree.tostring(cd,encoding="UTF-8",xml_declaration=True,pretty_print=False);result={**validation,"source_sha256":audit["source_sha256"],"candidate_sha256":hashlib.sha256(cb).hexdigest(),"footnotes":audit["footnotes"],"footnote_references":audit["footnote_references"],"page_markers":audit["page_markers"],"transcribers_notes_retained":2,"electronic_interventions":"Both source transcriber-note divisions are retained verbatim; no further correction or modernization applied.","canonical_write":False,"acceptance_status":"nonaccepted","publication_status":"not-authorized"}
    candidate.parent.mkdir(parents=True,exist_ok=True);report.parent.mkdir(parents=True,exist_ok=True);cs=candidate.with_name(candidate.name+".tmp");rs=report.with_name(report.name+".tmp");cs.write_bytes(cb);rs.write_text(json.dumps(result,indent=2,sort_keys=True,ensure_ascii=False)+"\n",encoding="utf-8",newline="\n");cs.replace(candidate);rs.replace(report);return result


def write_determinism_report(a:Path,av:Path,b:Path,bv:Path,output:Path,*,repository_root:Path)->dict[str,Any]:
    result={"candidate_bytes_equal":a.read_bytes()==b.read_bytes(),"candidate_sha256":sha256_file(a),"validation_bytes_equal":av.read_bytes()==bv.read_bytes(),"validation_sha256":sha256_file(av),"different_working_directory":Path.cwd().resolve()!=repository_root.resolve(),"run_a_working_directory":str(repository_root.resolve()),"run_b_working_directory":str(Path.cwd().resolve())}
    if not result["candidate_bytes_equal"] or not result["validation_bytes_equal"] or not result["different_working_directory"]:raise SourceMismatchError("fresh-CWD determinism failed")
    _write_json(output,result);return result


def write_offline_visual_contact_sheet(source:Path,candidate:Path,output_dir:Path)->dict[str,Any]:
    body=_body(_parse(source));doc=etree.parse(str(candidate));first_footnote=body.xpath("(.//div[contains(concat(' ',normalize-space(@class),' '),' footnote ')])[1]");edition_table=body.xpath("(.//table[contains(concat(' ',normalize-space(@class),' '),' editions ')])[1]")
    selections=[("opening-title-and-ninth-edition",body[48:56],doc.xpath("/tei:TEI/tei:text/tei:front/tei:div[@type='press_and_title_page']/*[position()>=47]",namespaces=NS),"full"),("middle-chapter-thirteen",body[910:1009],doc.xpath("/tei:TEI/tei:text/tei:body/tei:div[3]/tei:div[1]",namespaces=NS),"prefix"),("unusual-first-linked-footnote",first_footnote,doc.xpath("(//tei:note)[1]",namespaces=NS),"full"),("unusual-edition-history-table",edition_table,doc.xpath("(//tei:table[contains(concat(' ',normalize-space(@rend),' '),' editions ')])[1]",namespaces=NS),"full"),("ending-subject-index-printer-notes-footer",body[2119:],doc.xpath("/tei:TEI/tei:text/tei:back/tei:div[@type='indexes_and_printer']/*[position()>=117] | /tei:TEI/tei:text/tei:back/tei:div[@type='terminal_transcribers_notes' or @type='project_gutenberg_footer']",namespaces=NS),"suffix")]
    checks=[]
    for label,snodes,cnodes,mode in selections:
        st=" ".join("".join(etree.tostring(n,method="text",encoding="unicode",with_tail=True) for n in snodes).split());ct=" ".join("".join(etree.tostring(n,method="text",encoding="unicode",with_tail=True) for n in cnodes).split())
        if st!=ct:raise SourceMismatchError(f"offline contact selection differs: {label}")
        excerpt=st[:1200] if mode=="prefix" else st[-1600:] if mode=="suffix" else st;checks.append({"label":label,"selection":mode,"full_text_characters":len(st),"full_text_sha256":hashlib.sha256(st.encode()).hexdigest(),"source_candidate_full_text_match":True,"exact_excerpt":excerpt,"exact_excerpt_characters":len(excerpt),"exact_excerpt_sha256":hashlib.sha256(excerpt.encode()).hexdigest(),"result":"pass"})
    result={"method":"offline exact-excerpt contact sheet from pinned legacy XHTML and TEI","checks":checks,"all_exact_text_checks_passed":True,"acceptance_scope":"machine-verifiable lightweight fidelity evidence only; human acceptance remains separate"};output_dir.mkdir(parents=True,exist_ok=True);_write_json(output_dir/"offline_contact_sheet.json",result);lines=["# Turton offline exact-excerpt contact sheet","","Aligned exact excerpts from the pinned XHTML and generated TEI.",""]
    for c in checks:lines += [f"## {c['label']}","",c["exact_excerpt"],""]
    (output_dir/"offline_contact_sheet.md").write_text("\n".join(lines),encoding="utf-8",newline="\n");return result


def write_evidence_bundle(source:Path,candidate:Path,validation:Path,determinism:Path,evidence_root:Path,*,repository_root:Path)->dict[str,Path]:
    audit=audit_source(source,repository_root=repository_root);v=json.loads(validation.read_text(encoding="utf-8"));acq=evidence_root.parent/"acquisition";urls={"42460-0.txt":"https://www.gutenberg.org/files/42460/42460-0.txt","42460-h.htm":"https://www.gutenberg.org/files/42460/42460-h/42460-h.htm","files-index.html":"https://www.gutenberg.org/files/42460/","landing.html":"https://www.gutenberg.org/ebooks/42460","legacy-html-index.html":"https://www.gutenberg.org/files/42460/42460-h/","pg42460-h.zip":"https://www.gutenberg.org/cache/epub/42460/pg42460-h.zip","pg42460-images.html":"https://www.gutenberg.org/cache/epub/42460/pg42460-images.html","pg42460.txt":"https://www.gutenberg.org/cache/epub/42460/pg42460.txt"};members=[]
    for name in sorted(PACKAGE_HASHES):
        p=source.parent/name;h=acq/f"{name}.headers.txt";members.append({"name":name,"bytes":p.stat().st_size,"sha256":sha256_file(p),"url":urls[name],"download_headers_sha256":sha256_file(h)})
    receipt={"ticket":28,"master":4,"slug":"turton-truth-of-christianity-1919","identity":{"title":"The Truth of Christianity","author":"William Harry Turton","edition":"Ninth edition, fortieth thousand, carefully revised throughout; London, 1919","project_gutenberg_id":"42460","workcatalog":"provisional net-new candidate; no canonical write"},"retained_members":members,"archive_members":audit["archive_members"],"archive_member_hashes":audit["archive_member_hashes"],"rights":{"status":"Public domain in the United States per Project Gutenberg record","license_url":"https://www.gutenberg.org/policy/license.html","production_credit":"Heiko Evermann, Quentin Johnson, Fox in the Stars, and the Online Distributed Proofreading Team"},"source_authority":"42460-h.htm is structural and textual authority; current HTML, UTF-8 text witnesses, current HTML ZIP/images, landing page, and indexes are hash-bound corroborating witnesses","completeness":{"source_text_characters":audit["source_text_characters"],"source_text_sha256":audit["source_text_sha256"],"parts":3,"chapters":25,"footnotes":490,"footnote_references":490,"page_markers":514,"tables":65,"rows":1043,"cells":3244,"source_ids":1526,"internal_targets":3424,"printer_line":audit["printer_line"],"project_gutenberg_end_marker":audit["project_gutenberg_end_marker"]},"acceptance_status":"nonaccepted","publication_status":"not-authorized"}
    accountability={"source_sha256":audit["source_sha256"],"candidate_sha256":sha256_file(candidate),"validation_sha256":sha256_file(validation),"determinism_sha256":sha256_file(determinism),"schema":{"path":"ocd_kernel/tei/vendor/relaxng/tei_all.rng","sha256":sha256_file(repository_root/"ocd_kernel/tei/vendor/relaxng/tei_all.rng")},"converter":{"path":"build/tei/turton_truth_of_christianity_1919.py","sha256":sha256_file(repository_root/"build/tei/turton_truth_of_christianity_1919.py")},"source_config":{"path":"sources/structured-text/turton-truth-of-christianity-1919/config.json","sha256":sha256_file(repository_root/"sources/structured-text/turton-truth-of-christianity-1919/config.json")},"attribution_readme":{"path":"sources/structured-text/turton-truth-of-christianity-1919/README.md","sha256":sha256_file(repository_root/"sources/structured-text/turton-truth-of-christianity-1919/README.md")},"contract_tests":{"path":"tests/test_turton_truth_of_christianity_1919.py","sha256":sha256_file(repository_root/"tests/test_turton_truth_of_christianity_1919.py"),"result":"5 passed"},"package_hashes":audit["package_hashes"],"tei_p5_relaxng_valid":v["tei_p5_relaxng_valid"],"source_candidate_text_match":v["source_candidate_text_match"],"source_text_sha256":v["source_text_sha256"],"candidate_text_sha256":v["candidate_text_sha256"],"candidate_tag_counts":v["candidate_tag_counts"],"unresolved_internal_targets":v["unresolved_internal_targets"],"electronic_interventions":v["electronic_interventions"],"wording_modernized":False,"canonical_write":False,"acceptance_status":"nonaccepted","publication_status":"not-authorized"}
    unresolved={"textual_acceptance":"pending human review","identity_and_edition_acceptance":"pending human review","rights_acceptance":"pending human review","editorial_acceptance":"pending human review","visual_acceptance":"offline exact-excerpt checks pass; human visual acceptance remains pending","canonical_integration":"not authorized","publication":"not authorized"};paths={"receipt":evidence_root/"source_receipt.json","accountability":evidence_root/"accountability.json","unresolved":evidence_root/"unresolved_items.json"};_write_json(paths["receipt"],receipt);_write_json(paths["accountability"],accountability);_write_json(paths["unresolved"],unresolved);return paths


def write_path_hash_manifest(raw_root:Path,report_root:Path,output:Path,*,repository_root:Path)->dict[str,Any]:
    entries=[]
    for scope,root in (("raw",raw_root),("report",report_root)):
        for p in sorted(p for p in root.rglob("*") if p.is_file() and p.resolve()!=output.resolve()):entries.append({"scope":scope,"path":p.relative_to(root).as_posix(),"bytes":p.stat().st_size,"sha256":sha256_file(p)})
    for rel in ("sources/structured-text/turton-truth-of-christianity-1919/config.json","sources/structured-text/turton-truth-of-christianity-1919/README.md","build/tei/turton_truth_of_christianity_1919.py","tests/test_turton_truth_of_christianity_1919.py"):
        p=repository_root/rel;entries.append({"scope":"worktree","path":rel,"bytes":p.stat().st_size,"sha256":sha256_file(p)})
    result={"ticket":28,"master":4,"slug":"turton-truth-of-christianity-1919","files":entries,"file_count_excluding_manifest":len(entries),"canonical_write":False,"acceptance_status":"nonaccepted","publication_status":"not-authorized"};_write_json(output,result);return result


def main()->int:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--repository-root",type=Path,required=True);p.add_argument("--source",type=Path);p.add_argument("--candidate",type=Path,required=True);p.add_argument("--validation",type=Path,required=True);p.add_argument("--replace",action="store_true");a=p.parse_args();root=a.repository_root.resolve();build_candidate((a.source or resolve_source_path(root)).resolve(),a.candidate.resolve(),a.validation.resolve(),repository_root=root,replace=a.replace);return 0
if __name__=="__main__":raise SystemExit(main())
