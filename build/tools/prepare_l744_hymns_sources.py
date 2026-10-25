"""Prepare distinct L744 source profiles and manifests from already-retained PG archives."""
from __future__ import annotations
import hashlib, importlib.util, json, re
from pathlib import Path, PurePosixPath
from zipfile import ZipFile
import html5lib
from lxml import html as lxml_html
from ocd_kernel.lib.storage_topology import repository_relative_path, resolve_repo_path

ROOT=Path(__file__).resolve().parents[2]
XSD="ocd_kernel/tei/vendor/xsd/tei_all.xsd"
PACKAGE_SCHEMA="ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json"
WORKS={
 "33128":{"work_id":"l744-pg33128-gospel-hymns","edition_id":"pg33128-second-edition-1899","source_id":"pg33128-gospel-hymns-ojibway-english","title":"A Collection of Gospel Hymns in Ojibway and English","edition":"Second edition","year":"1899","title_page_id":"home"},
 "33105":{"work_id":"l744-pg33105-chinook-hymns","edition_id":"pg33105-second-edition-1889-revised-enlarged","source_id":"pg33105-hymns-chinook-jargon-language","title":"Hymns in the Chinook Jargon Language","edition":"Second edition. Revised and Enlarged.","year":"1889","title_page_id":"home"}
}
def sha(data): return hashlib.sha256(data).hexdigest()
def canon(value): return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode("utf-8")
def norm(text): return " ".join(text.split())
def words(text): return set(re.findall(r"[a-z0-9]+",text.casefold()))
def html_ledger(body):
 rows=[];ordinals={body:0};stack=[(body,None,0)]
 while stack:
  el,parent,pos=stack.pop()
  if el is not body:
   tag=el.tag if isinstance(el.tag,str) else "#comment"
   ordinal=len(ordinals);ordinals[el]=ordinal
   rows.append({"ordinal":ordinal,"parent_ordinal":parent,"position":pos,"tag":tag,
    "attributes":dict(sorted(el.attrib.items())),
    "text_sha256":sha((el.text or "").encode("utf-8")),
    "tail_sha256":sha((el.tail or "").encode("utf-8"))})
  for childpos,ch in reversed(list(enumerate(list(el),1))): stack.append((ch,ordinals[el],childpos))
 return rows,ordinals
def tree_signature(body):
 rows=[];stack=[(body,0,0)]
 children=list(body);terminal=children[-1] if children else None
 while stack:
  el,parent,pos=stack.pop()
  tail="" if el is body or el is terminal else (el.tail or "").replace("\r\n","\n").replace("\r","\n")
  rows.append({"parent":parent,"position":pos,
   "tag":el.tag if isinstance(el.tag,str) else "#comment",
   "attributes":dict(sorted(el.attrib.items())) if isinstance(el.tag,str) else {},
   "text":(el.text or "").replace("\r\n","\n").replace("\r","\n"),
   "tail":tail})
  for childpos,ch in reversed(list(enumerate(list(el),1))): stack.append((ch,len(rows)-1,childpos))
 return rows
def members_in(z):
 return [{"path":i.filename,"bytes":i.file_size,"crc32":f"{i.CRC:08x}","sha256":sha(z.read(i))}
  for i in z.infolist() if not i.is_dir()]
def auth(name,path,role):
 b=path.read_bytes()
 return {"name":name,"path":repository_relative_path(ROOT,path.resolve()),"role":role,"bytes":len(b),"sha256":sha(b)}
def oracle_closure():
 path=ROOT/"build/tei/l744_hymns_oracle.py"
 spec=importlib.util.spec_from_file_location("_l744_oracle_binding",path)
 if spec is None or spec.loader is None: raise RuntimeError("cannot load L744 oracle closure")
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 return module._closure()
def candidate_home():
 reports=resolve_repo_path(ROOT,"reports").resolve(strict=True)
 target=reports.parent.resolve(strict=True)/"candidate-reviews"
 if not target.is_dir(): raise FileNotFoundError(f"candidate-review home is absent: {target}")
 return target.resolve(strict=True)
def source_semantics(eid,body,ordinals):
 def ordinal(n): return ordinals.get(n)
 top=[{"ordinal":ordinal(x),"tag":x.tag if isinstance(x.tag,str) else "#comment",
  "id":x.get("id"),"class":x.get("class"),"child_count":len(x),
  "text_sha256":sha("".join(x.itertext()).encode("utf-8"))} for x in body]
 pages=[{"ordinal":ordinal(x),"id":x.get("id"),"class":x.get("class"),"text":norm("".join(x.itertext()))}
  for x in body.iter("div") if set((x.get("class") or "").split()) & {"page_break","pb"}]
 out={"top_level_carriers":top,"page_markers":pages}
 if eid=="33128":
  heads=[{"ordinal":ordinal(x),"text":norm("".join(x.itertext()))} for x in body.iter("h3")]
  expected=[label for i in range(1,39) for label in (f"Hymn {i}.",f"Nuhguhmoowin {i}.")]
  if [x["text"] for x in heads]!=expected: raise ValueError("PG33128 lacks all 38 paired hymn headings in sequence")
  sections={}
  for key in ("titlepg","h","index_e","index_o","phonics"):
   n=next((x for x in body.iter() if x.get("id")==key),None)
   if n is None: raise ValueError(f"PG33128 section #{key} is absent")
   sections[key]={"ordinal":ordinal(n),"tag":n.tag,"text_sha256":sha("".join(n.itertext()).encode("utf-8"))}
  verses=[x for x in body.iter("div") if "verse" in (x.get("class") or "").split()]
  if len(verses)!=390: raise ValueError(f"PG33128 verse divisions: {len(verses)}")
  out.update({"hymn_headings":heads,"numbered_hymn_pairs":[
   {"number":i,"english_heading":heads[(i-1)*2]["ordinal"],"ojibway_heading":heads[(i-1)*2+1]["ordinal"]}
   for i in range(1,39)],"section_boundaries":sections,"verse_division_count":len(verses),
   "title_page_duplicate_carriers":[{"id":x.get("id"),"class":x.get("class"),
    "text_sha256":sha("".join(x.itertext()).encode("utf-8"))}
    for x in body.iter("div") if "titlepg" in (x.get("class") or "").split()]})
 else:
  numbered=[{"ordinal":ordinal(x),"text":norm("".join(x.itertext()))} for x in body.iter("h3")
   if re.fullmatch(r"No\. \d+\.",norm("".join(x.itertext())))]
  if [x["text"] for x in numbered]!=[f"No. {i}." for i in range(1,21)]:
   raise ValueError("PG33105 lacks hymns 1 through 20 in sequence")
  translations=[x for x in body.iter("h4") if norm("".join(x.itertext())).casefold()=="translation."]
  if len(translations)!=20: raise ValueError(f"PG33105 translation headings: {len(translations)}")
  tables=[]
  for i,t in enumerate(body.iter("table"),1):
   rows=list(t.iter("tr"));cells=[[c for c in r if c.tag in {"td","th"}] for r in rows]
   if t.get("class")!="interlinear" or len(rows)!=2 or [len(x) for x in cells]!=[1,1]:
    raise ValueError(f"PG33105 table {i} is not an intact two-row pair")
   tables.append({"index":i,"ordinal":ordinal(t),"class":t.get("class"),
    "rows":[{"ordinal":ordinal(r),"cell_ordinals":[ordinal(c) for c in cr],
     "text_sha256":sha("".join(r.itertext()).encode("utf-8"))} for r,cr in zip(rows,cells)]})
  if len(tables)!=142: raise ValueError(f"PG33105 interlinear table count: {len(tables)}")
  heading_text=[norm("".join(x.itertext())).casefold() for x in body.iter()
   if isinstance(x.tag,str) and x.tag in {"h3","h4"}]
  closers=[x for x in heading_text if "lord" in x or "blessing before meals" in x]
  if len(closers)!=2 or not any("lord" in x for x in closers) or not any("blessing before meals" in x for x in closers):
   raise ValueError("PG33105 closing prayer/blessing boundary is absent")
  out.update({"numbered_hymns":numbered,"translation_heading_count":len(translations),
   "interlinear_table_count":len(tables),"interlinear_tables":tables,"closing_headings":closers,
   "verse_division_count":sum(1 for x in body.iter("div") if "verse" in (x.get("class") or "").split()),
   "page_marker_count":sum(1 for x in body.iter("div") if "pb" in (x.get("class") or "").split())})
 return out
def prepare(eid):
 c=WORKS[eid]; rawroot=ROOT/"raw/gutenberg"/eid
 archive=rawroot/f"pg{eid}-h.zip"; receipt_path=rawroot/"acquisition-receipt.json"
 inventory_path=rawroot/"member-inventory.tsv"
 receipt_bytes=receipt_path.read_bytes();receipt=json.loads(receipt_bytes.decode("utf-8"))
 archive_bytes=archive.read_bytes()
 if receipt.get("schema")!="ocd-acquisition-source-receipt-v1" or receipt.get("ebook_id")!=eid or receipt.get("manifest_rows")!=["L744"] or receipt.get("status")!="retained-source-only":
  raise ValueError(f"PG{eid} receipt is not the exact L744 source-only receipt")
 if receipt["package"]!={"path":archive.relative_to(ROOT).as_posix(),"bytes":len(archive_bytes),"sha256":sha(archive_bytes)}:
  raise ValueError(f"PG{eid} archive bytes/path differ from receipt")
 with ZipFile(archive) as z:
  if z.testzip() is not None: raise ValueError(f"PG{eid} CRC failure")
  archive_members=members_in(z)
  seen=set()
  for m in archive_members:
   p=PurePosixPath(m["path"])
   if not m["path"] or "\\" in m["path"] or p.is_absolute() or ":" in m["path"] or any(x in {"",".",".."} for x in p.parts) or m["path"] in seen:
    raise ValueError(f"PG{eid} unsafe/duplicate member: {m['path']}")
   seen.add(m["path"])
  htmls=[m for m in archive_members if m["path"].endswith(".html")]
  if len(archive_members)!=2 or len(htmls)!=1: raise ValueError(f"PG{eid} archive member set differs from source receipt")
  html_member=htmls[0]["path"];raw=z.read(html_member)
 if html_member!=receipt["verification"]["primary_html"]: raise ValueError(f"PG{eid} receipt primary HTML differs")
 if receipt["html"]!={"path":f"raw/gutenberg/{eid}/html/{html_member}","bytes":len(raw),"sha256":sha(raw)}:
  raise ValueError(f"PG{eid} HTML source differs from receipt")
 extracted=rawroot/"html";files={x.relative_to(extracted).as_posix():x for x in extracted.rglob("*") if x.is_file()}
 if set(files)!={m["path"] for m in archive_members}: raise ValueError(f"PG{eid} extracted member set differs")
 with ZipFile(archive) as z:
  for m in archive_members:
   if files[m["path"]].read_bytes()!=z.read(m["path"]): raise ValueError(f"PG{eid} extracted member mismatch: {m['path']}")
 invbytes=inventory_path.read_bytes(); invlines=invbytes.decode("utf-8",errors="strict").splitlines()
 rows=[x.rstrip("\r\n") for x in invlines]
 inv_headerless=("\n".join(rows)+"\n").encode("utf-8")
 if sha(inv_headerless)!=receipt["verification"]["member_hash_inventory"]["sha256"] or len(rows)!=len(archive_members):
  raise ValueError(f"PG{eid} inventory digest differs from receipt")
 expected_rows=[f"{m['path']}\t{m['bytes']}\t{m['crc32']}\t{m['sha256']}" for m in archive_members]
 if rows!=expected_rows: raise ValueError(f"PG{eid} inventory rows differ from archive members")
 raw.decode("utf-8",errors="strict")
 parser=html5lib.HTMLParser(tree=html5lib.getTreeBuilder("etree"),namespaceHTMLElements=False)
 doc=parser.parse(raw);body=doc.find(".//body");head=doc.find(".//head")
 if body is None or head is None: raise ValueError(f"PG{eid} head/body missing")
 htmltitle=head.findtext("title") or ""
 if htmltitle!=c["title"]: raise ValueError(f"PG{eid} HTML provider title differs: {htmltitle!r}")
 titlepage=next((x for x in body.iter("div") if x.get("id")==c["title_page_id"]),None)
 if titlepage is None: raise ValueError(f"PG{eid} printed title page carrier absent")
 titletext=norm("".join(titlepage.itertext())); titlewords=words(titletext)
 if not words(c["title"])<=titlewords: raise ValueError(f"PG{eid} printed title page title wording differs")
 if c["year"] not in titletext: raise ValueError(f"PG{eid} printed title page year missing")
 if not words(c["edition"])<=words(titletext): raise ValueError(f"PG{eid} printed title page edition statement differs")
 diagnostics=[str(x) for x in parser.errors]
 if diagnostics: raise ValueError(f"PG{eid} html5lib parser diagnostics: {len(diagnostics)}")
 ledger,ordinals=html_ledger(body)
 children=list(body)
 parts=[body.text or ""]
 for index,child in enumerate(children):
  parts.extend(child.itertext())
  if index<len(children)-1:parts.append(child.tail or "")
 text="".join(parts)
 sem=source_semantics(eid,body,ordinals)
 lroot=lxml_html.fromstring(raw);lbody=lroot.find(".//body")
 if lbody is None: raise ValueError(f"PG{eid} lxml body missing")
 lxml_sig=tree_signature(lbody); html5_sig=tree_signature(body)
 cross={"producer_parser":"lxml.html","oracle_parser":"html5lib.etree",
  "producer_node_count_including_body":len(lxml_sig),"oracle_node_count_including_body":len(html5_sig),
  "producer_direct_child_count":len(lbody),"oracle_direct_child_count":len(body),
  "normalized_structure_text_attributes_equal":lxml_sig==html5_sig,
  "CRLF_to_LF_normalization_for_parser_comparison":True}
 if not cross["normalized_structure_text_attributes_equal"]: raise ValueError(f"PG{eid} lxml/html5lib crosscheck differs")
 slug=f"l744-pg{eid}-{'gospel-hymns' if eid=='33128' else 'chinook-hymns'}"
 srcdir=ROOT/"sources/manifest-acquisitions"/slug
 if srcdir.exists():
  allowed={"profile.json","policy.json","README.source.md","source-manifest.json"}
  entries={x.name for x in srcdir.iterdir()}
  if not entries<=allowed: raise FileExistsError(f"unexpected files in source dossier {srcdir}")
  prior=srcdir/"profile.json"
  if prior.exists() and json.loads(prior.read_bytes()).get("source_id")!=c["source_id"]:
   raise FileExistsError(f"source dossier belongs to a different authority: {srcdir}")
 else:
  srcdir.mkdir(parents=True,exist_ok=False)
 profile={"contract":"ocd-l744-retained-pg-source-profile-v1","ticket_id":"L744",
  "source_id":c["source_id"],"work_id":c["work_id"],"edition_id":c["edition_id"],
  "ebook_id":eid,"title":c["title"],"edition":c["edition"],"year":c["year"],
  "identity_basis":"The exact provider HTML title matches the printed title-page wording and edition/year. Receipt and member/archive digests bind bytes but do not establish identity alone.",
  "source_url":receipt["source_url"],"package_url":receipt["package_url"],
  "archive_path":archive.relative_to(ROOT).as_posix(),"archive_bytes":len(archive_bytes),
  "archive_sha256":sha(archive_bytes),"archive_members":archive_members,"html_member":html_member,
  "html_path":receipt["html"]["path"],"html_bytes":len(raw),"html_sha256":sha(raw),
  "receipt_path":receipt_path.relative_to(ROOT).as_posix(),"receipt_bytes":len(receipt_bytes),
  "receipt_sha256":sha(receipt_bytes),"receipt_status":receipt["status"],
  "member_inventory_path":inventory_path.relative_to(ROOT).as_posix(),
  "member_inventory_bytes":len(invbytes),"member_inventory_sha256":sha(invbytes),
  "member_inventory_headerless_sha256":sha(inv_headerless),"member_inventory_rows":rows,
  "html_title":htmltitle,"title_page_id":c["title_page_id"],"title_page_text":titletext,
  "title_page_text_sha256":sha(titletext.encode("utf-8")),
  "body_direct_child_count":len(body),"body_element_count":sum(1 for x in body.iter() if isinstance(x.tag,str)),
  "body_node_count_including_comments":len(ledger),"body_text_sha256":sha(text.encode("utf-8")),
  "body_text_characters":len(text),"node_ledger":ledger,
  "html_head_members":[{"tag":x.tag if isinstance(x.tag,str) else "#comment",
   "attributes":dict(sorted(x.attrib.items())) if isinstance(x.tag,str) else {},
   "text_sha256":sha((x.text or "").encode("utf-8"))} for x in head],
  "html5lib_parse_diagnostics":diagnostics,"parser_crosscheck":cross,
  "source_semantics":sem,"completeness":"Complete declared HTML member for this printed title/edition; all two archived members are extracted and hash-accounted. No page-image collation is claimed.",
  "unresolved_print_collation":True}
 profile_path=srcdir/"profile.json";profile_path.write_bytes(canon(profile))
 unresolved=[
  {"id":"print-collation","status":"open","question":"The retained Project Gutenberg HTML has not been collated against the printed edition or page images."},
  {"id":"human-acceptance","status":"open","question":"Technical validation does not record human acceptance."},
  {"id":"rights-clearance","status":"open","question":"The item-level Project Gutenberg terms are retained; no independent rights clearance is recorded."},
  {"id":"visual-review","status":"open","question":"No human or CVW visual comparison has been performed."},
  {"id":"publication","status":"open","question":"Publication has not been authorized."}]
 specific_checks=(
  ["PG33128's 38 English/Ojibway hymn pairs, title/index/key boundaries, and 390 verse divisions"]
  if eid=="33128" else
  ["PG33105's hymns 1-20, 142 intact two-row interlinear tables, and closing prayer/blessing"])
 policy={"contract":"ocd-l744-source-to-tei-policy-v1","source_id":c["source_id"],
  "work_id":c["work_id"],"edition_id":c["edition_id"],"ticket_id":"L744",
  "scope":"Each complete top-level titled work produces exactly one direct-TEI nonaccepted candidate. Each work has its own source identity, edition identity, profile, manifest, TEI, and unresolved ledger.",
  "identity":"Establish identity from the provider title and printed title-page wording/edition/year. Do not infer identity from CLEAN-READY or hashes alone. PG33128's title page does not name an author; omit one. PG33105 names Rev. M. Eells as compiler; do not expand the initials.",
  "mapping":"Preserve all body text and whitespace, source order, IDs/classes/links, page markers, heading levels, tables, table rows/cells, provider header/footer, and Gutenberg license matter in the HTML body. The duplicate home/title-page carriers in PG33128 remain distinct. Head CSS/provider metadata stay in the profile. The unreferenced cover image is support only.",
  "excluded_or_support":"No page scans exist in the declared archive, so print collation remains unresolved. The PG33128 WorkCatalog entry is limited to the source-attested title and edition; no author or language code is asserted. Cover art remains byte-bound archive support.",
  "independence":{"producer":"Unique L744 converter parses retained HTML with lxml.html.","oracle":"Unique L744 oracle independently parses retained bytes with html5lib/etree, rebuilds source-led carriers, and checks actual TEI text, order, attributes, and work-specific boundaries. It does not import or call the converter.","shared_assumptions":"Both routes use the same retained bytes, P5 schema, and mapping vocabulary. The profile records lxml/html5lib structure and exact content agreement after line-ending normalization; the oracle independently recomputes source-led expectations."},
  "checks":["receipt/archive/extraction/member identity and digests","complete source element/attribute/parent-position ledger and HTML head envelope","exact text and whitespace with XML line-ending normalization only","one direct TEI root and P5 XSD validation","title-page edition identity",*specific_checks,"focused source-text and work-boundary mutations","fresh-process candidate reproduction"],
  "provenance":{"contract":"ocd-l744-source-provenance-v1","identity_status":"source-grounded edition-bounded WorkCatalog entry; authorship and language coding remain unspecified","canonical_work_catalog":c["work_id"],
   "source_id":c["source_id"],"work_id":c["work_id"],"edition_id":c["edition_id"],
   "acquisition_id":f"pg{eid}-l744-retained-source-only","ebook_id":eid,
   "source_url":receipt["source_url"],"archive_sha256":profile["archive_sha256"],
   "html_sha256":profile["html_sha256"],"receipt_sha256":profile["receipt_sha256"],
   "member_inventory_sha256":profile["member_inventory_sha256"],"title":c["title"],
   "edition":c["edition"],"year":c["year"],
   "method":"Complete retained HTML-body-to-TEI reconstruction with source-specific independent html5lib oracle and complete archive/member accounting.",
   "rights":"Project Gutenberg item-level notice retained. No independent jurisdictional or worldwide rights clearance is recorded.",
   "human_acceptance":"not recorded","publication":"not authorized"},
  "unresolved":unresolved}
 policy_path=srcdir/"policy.json";policy_path.write_bytes(canon(policy))
 readme=(f"# {c['title']}\n\n**Printed edition:** {c['edition']}, {c['year']}.\n\n"
  f"**Edition identity evidence:** Project Gutenberg eBook {eid} has the exact provider HTML title. Printed title-page carrier {c['title_page_id']} contains: “{titletext}”\n\n"
  f"**Retained source:** {archive.relative_to(ROOT).as_posix()} (SHA-256 {profile['archive_sha256']}); HTML member {html_member} (SHA-256 {profile['html_sha256']}). Source-only receipt: {receipt_path.relative_to(ROOT).as_posix()} (SHA-256 {profile['receipt_sha256']}).\n\n"
  "**Scope:** The complete declared Project Gutenberg HTML member is represented in one nonaccepted TEI candidate. The unreferenced cover member remains hash-accounted support. Print collation is unresolved.\n\n"
  f"**WorkCatalog link:** `{c['work_id']}`. The entry is limited to the exact provider title and printed title-page edition/year; no author or language code is asserted.\n\n"
  "**Review state:** Human acceptance, rights clearance, visual review, and publication authorization remain separate and unrecorded.\n")
 readme_path=srcdir/"README.source.md";readme_path.write_text(readme,encoding="utf-8",newline="\n")
 authorities=[
  auth("retained-archive",archive.resolve(strict=True),"primary-source"),
  auth("extracted-html",(extracted/html_member).resolve(strict=True),"source-extraction"),
  auth("acquisition-receipt",receipt_path.resolve(strict=True),"source-acquisition-receipt"),
  auth("member-inventory",inventory_path.resolve(strict=True),"source-acquisition-record"),
  auth("profile",profile_path,"complete-source-feature-profile"),
  auth("policy",policy_path,"independent-validation-policy"),
  auth("readme",readme_path,"source-attribution-readme"),
  auth("tei-validation-schema",ROOT/XSD,"tei-validation-schema"),
  auth("candidate-package-schema",ROOT/PACKAGE_SCHEMA,"candidate-package-schema")]
 producer=ROOT/"build/tei/l744_hymns.py";oracle=ROOT/"build/tei/l744_hymns_oracle.py"
 manifest={"contract":"ocd-source-manifest-v1","ticket_id":"L744","work_id":c["work_id"],
  "edition_id":c["edition_id"],"source_id":c["source_id"],
  "external_library_root":str(candidate_home().parent),"authorities":authorities,
  "source_members":[{"name":m["path"],"path":archive.relative_to(ROOT).as_posix(),
   "bytes":m["bytes"],"sha256":m["sha256"],"role":"retained-archive-member"} for m in archive_members],
  "converter":{"id":"ocd-l744-two-edition-hymn-collections-to-tei","version":"1",
   "callable":"_convert","implementation_path":producer.relative_to(ROOT).as_posix(),
   "implementation_sha256":sha(producer.read_bytes())},
  "validator":{"id":"ocd-independent-l744-hymns-html5lib-oracle","version":"1",
   "callable":"_oracle","implementation_path":oracle.relative_to(ROOT).as_posix(),
   "implementation_sha256":sha(oracle.read_bytes()),"import_closure_sha256":oracle_closure()},
  "package_schema":{"path":PACKAGE_SCHEMA,"sha256":sha((ROOT/PACKAGE_SCHEMA).read_bytes())}}
 manifest_path=srcdir/"source-manifest.json";manifest_path.write_bytes(canon(manifest))
 return {"ebook_id":eid,"source_id":c["source_id"],"work_id":c["work_id"],
  "edition_id":c["edition_id"],"archive_sha256":profile["archive_sha256"],
  "html_sha256":profile["html_sha256"],"receipt_sha256":profile["receipt_sha256"],
  "member_count":len(archive_members),"body_element_count":profile["body_element_count"],
  "profile_sha256":sha(profile_path.read_bytes()),"manifest_sha256":sha(manifest_path.read_bytes()),
  "candidate_home":str(candidate_home())}
if __name__=="__main__":
 import sys
 requested=sys.argv[1:] or list(WORKS)
 if set(requested)-set(WORKS): raise SystemExit(f"unknown PG IDs: {sorted(set(requested)-set(WORKS))}")
 print(json.dumps([prepare(x) for x in requested],ensure_ascii=False,sort_keys=True,separators=(",",":")))
