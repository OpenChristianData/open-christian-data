"""Independent HTML5 source accounting and structural checker for Tyerman PG batch."""
from __future__ import annotations

import hashlib, json, platform, re, sys
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET

import html5lib, html5lib._inputstream, html5lib._tokenizer, html5lib.html5parser, html5lib.treebuilders.etree
from lxml import etree
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest

TEI="http://www.tei-c.org/ns/1.0"; XML_ID="{http://www.w3.org/XML/1998/namespace}id"
WORKS={"tyerman-life-times-john-wesley-vol-1-1872":"69582","tyerman-life-times-john-wesley-vol-2-1872":"71130","tyerman-life-times-john-wesley-vol-3-1872":"76882","tyerman-life-george-whitefield-vol-1-1876":"44280","tyerman-life-george-whitefield-vol-2-1877":"62023","tyerman-oxford-methodists-1873":"70497","tyerman-life-times-samuel-wesley-1866":"67980"}
HEADINGS={"h1","h2","h3","h4","h5","h6"}; PAGE=re.compile(r"(?:\[(?:Pg\s*)?|\{)([^\]}]+)(?:\]|\})")
ORACLE_ID="ocd-l634-637-independent-html5lib-structural-reader"

def sha(b: bytes)->str: return hashlib.sha256(b).hexdigest()
def enc(v: object)->bytes: return (json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode()
def norm(s: str)->str: return " ".join(s.split())
def st(e: ET.Element)->str: return norm("".join(e.itertext()))
def tt(e: etree._Element)->str: return norm("".join(e.itertext()))
def closure_digest()->str:
    paths=[Path(__file__).resolve(),Path(html5lib._inputstream.__file__).resolve(),Path(html5lib._tokenizer.__file__).resolve(),Path(html5lib.html5parser.__file__).resolve(),Path(html5lib.treebuilders.etree.__file__).resolve()]
    return sha(enc([{"path":p.name,"sha256":sha(p.read_bytes())} for p in paths]))

def _oracle(manifest: SourceManifest, candidate: CandidatePackage):
    findings=[]; ebook=WORKS[manifest.record["work_id"]]
    profile=json.loads(manifest.authority_path("profile").read_text(encoding="utf-8")); policy=json.loads(manifest.authority_path("policy").read_text(encoding="utf-8"))
    zpath=manifest.authority_path("retained-archive"); zbytes=zpath.read_bytes()
    if sha(zbytes)!=profile["archive_sha256"]: findings.append("retained ZIP digest differs")
    with ZipFile(zpath) as z:
        if z.testzip() is not None: findings.append("ZIP CRC failure")
        members=[{"path":x.filename,"bytes":x.file_size,"compressed_bytes":x.compress_size,"crc32":f"{x.CRC:08x}","sha256":sha(z.read(x))} for x in z.infolist() if not x.is_dir()]
        if members!=profile["archive_members"]: findings.append("archive member set/order/CRC/content differs")
        raw=z.read(profile["html_member"])
    if sha(raw)!=profile["html_sha256"]: findings.append("HTML member digest differs")
    src=html5lib.parse(raw,treebuilder="etree",namespaceHTMLElements=False); head=src.find(".//head"); body=src.find(".//body")
    if head is None or body is None: raise ValueError("complete source HTML head/body absent")
    carrier=[{"position":i,"tag":x.tag,"id":x.get("id"),"class":x.get("class"),"text_sha256":sha(st(x).encode())} for i,x in enumerate(body,1) if isinstance(x.tag,str)]
    if carrier!=profile["body_carriers"]: findings.append("ordered source body carrier inventory differs")
    if [{"tag":x.tag,"attributes":dict(sorted(x.attrib.items())),"text_sha256":sha((x.text or "").encode())} for x in head if isinstance(x.tag,str)]!=profile["head_carriers"]: findings.append("HTML head member inventory differs")
    tei=etree.fromstring(candidate.member_bytes("content.tei.xml"),etree.XMLParser(resolve_entities=False,no_network=True)); text=tei.find(f"{{{TEI}}}text")
    if text is None: raise ValueError("TEI text is missing")
    if st(body)!=tt(text): findings.append("complete normalized source body text differs from TEI")
    regions={x.tag.split("}")[-1]:x for x in text}
    if not all(x in regions for x in ("front","body","back")): findings.append("front/body/back regions missing")
    else:
        if not list(regions["body"]) or not tt(regions["body"]): findings.append("book body is empty")
        if not any(x.get(XML_ID)=="pg-header" for x in regions["front"].iter()): findings.append("provider header not preserved in front")
        if not any(x.get(XML_ID)=="pg-footer" for x in regions["back"].iter()): findings.append("provider footer not preserved in back")
    content_elements=[x for x in body.iter() if isinstance(x.tag,str) and x.tag!="footer" and not any(a.tag=="footer" for a in [])]
    footer_nodes=list(body.iter("footer")); footer_desc={id(y) for f in footer_nodes for y in f.iter() if y is not f}
    content_elements=[x for x in content_elements if id(x) not in footer_desc]
    sh=[(x.tag,st(x)) for x in content_elements if x.tag in HEADINGS]
    th=[((x.get("rend") or "").removeprefix("source-"),tt(x)) for x in text.iter(f"{{{TEI}}}head") if (x.get("rend") or "").startswith("source-h")]
    if sh!=th: findings.append("heading level/order/wording differs")
    sp=[(x.get("id"),st(x)) for x in content_elements if x.tag=="p"]
    tp=[(x.get(XML_ID),tt(x)) for x in text.iter(f"{{{TEI}}}p") if (x.get("rend") or "").split()[:1]==["source-p"]]
    if sp!=tp: findings.append("source paragraph order, identity, or text differs")
    si=[(x.tag,x.get("class") or "",st(x)) for x in content_elements if (x.tag in {"i","em","b","strong","small","abbr","cite","sup","sub","ins"} or (x.tag=="span" and "pagenum" not in (x.get("class") or "").split()))]
    ti=[(((x.get("rend") or "").split()[0]," ".join((x.get("rend") or "").split()[1:]),tt(x))) for x in text.iter(f"{{{TEI}}}hi")]
    if si!=ti: findings.append("inline emphasis/semantic markup order or wording differs")
    sl=[st(x) for x in content_elements if x.tag=="li"]; tl=[tt(x) for x in text.iter(f"{{{TEI}}}item") if (x.get("rend") or "").split()[:1]==["source-li"]]
    if sl!=tl: findings.append("list item occurrence order/text differs")
    sr=[[(st(c),c.get("colspan"),c.tag) for row in table.iter("tr") for c in row if c.tag in {"td","th"}] for table in content_elements if table.tag=="table"]
    tr=[[(tt(c),c.get("cols"),"th" if c.get("role")=="label" else "td") for row in table.iter(f"{{{TEI}}}row") for c in row if c.tag==f"{{{TEI}}}cell"] for table in text.iter(f"{{{TEI}}}table")]
    if sr!=tr: findings.append("table order, cell text, header role, or span differs")
    slinks=[(a.get("href"),st(a)) for a in content_elements if a.tag=="a" and a.get("href")]
    tlinks=[(a.get("target"),tt(a)) for a in text.iter(f"{{{TEI}}}ref") if a.get("target")]
    if slinks!=tlinks: findings.append("link target/order/label differs")
    sids=[x.get("id") for x in content_elements if x.get("id")] + [f.get("id") for f in footer_nodes if f.get("id")]
    tids=[x.get(XML_ID) for x in text.iter() if x.get(XML_ID)]
    if sids!=tids: findings.append("HTML IDs/order differ from TEI xml:id")
    spages=[(m.group(1) if m else None) for x in content_elements if "pagenum" in (x.get("class") or "").split() for m in [PAGE.search("".join(x.itertext()))]]
    tpages=[x.get("n") for x in text.iter(f"{{{TEI}}}pb")]
    if spages!=tpages: findings.append("page label order/content differs")
    schema=etree.XMLSchema(etree.parse(str(manifest.authority_path("tei-validation-schema"))))
    if not schema.validate(tei): findings.append(f"TEI P5 XSD failure: {schema.error_log.last_error}")
    account=json.loads(candidate.member_bytes("source-accountability.json"))
    if account.get("archive_sha256")!=sha(zbytes) or account.get("html_sha256")!=sha(raw) or account.get("tei_sha256")!=sha(candidate.member_bytes("content.tei.xml")) or account.get("archive_members")!=members: findings.append("source accountability binding differs")
    if candidate.member_bytes("README.source.md")!=manifest.authority_path("readme").read_bytes(): findings.append("source README differs")
    if json.loads(candidate.member_bytes("provenance.json"))!=policy["provenance"]: findings.append("provenance differs from policy")
    if candidate.member_bytes("unresolved.jsonl")!=b"".join(enc(x) for x in policy["unresolved"]): findings.append("unresolved ledger differs from policy")
    roles={a["role"]:a for a in manifest.record["authorities"]}
    result={"status":"pass" if not findings else "fail","oracle_id":ORACLE_ID,"oracle_version":"1","implementation_sha256":sha(Path(__file__).read_bytes()),"import_closure_sha256":closure_digest(),"runtime":f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})","source_manifest_sha256":manifest.sha256,"candidate_sha256":candidate.sha256,"source_sha256":roles["primary-source"]["sha256"],"profile_sha256":roles["complete-source-feature-profile"]["sha256"],"policy_sha256":roles["independent-validation-policy"]["sha256"],"xsd_sha256":roles["tei-validation-schema"]["sha256"],"package_schema_sha256":roles["candidate-package-schema"]["sha256"],"findings":findings}
    result["result_sha256"]=sha(enc(result)); return result

_oracle.oracle_id=ORACLE_ID; _oracle.oracle_version="1"; _oracle.implementation_path=Path(__file__).resolve()
