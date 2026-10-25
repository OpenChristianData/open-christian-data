"""Independent v2 MediaWiki XML export oracle for L594."""
from __future__ import annotations
import hashlib,json,platform,re,sys
from pathlib import Path
from typing import Mapping
from xml.etree import ElementTree as ET
from lxml import etree
from ocd_kernel.reconstruction.contract import CandidatePackage,SourceManifest
MW="{http://www.mediawiki.org/xml/export-0.11/}";T="{http://www.tei-c.org/ns/1.0}";X="{http://www.w3.org/XML/1998/namespace}"
ORACLE_ID="ocd-wikisource-l594-independent-export-oracle";ORACLE_VERSION="3"
def _sha(b:bytes)->str:return hashlib.sha256(b).hexdigest()
def _json(v:object)->bytes:return (json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode("utf-8")
def _page_text(page:ET.Element)->str:
    rev=page.find(MW+"revision");node=rev.find(MW+"text") if rev is not None else None
    return (node.text or "") if node is not None else ""
def _flat(s:str)->str:
    s=re.sub(r"<noinclude>.*?</noinclude>","",s,flags=re.I|re.S);s=re.sub(r"<br\s*/?>","\n",s,flags=re.I)
    pattern=re.compile(r"\{\{([^{}]*)\}\}")
    while "{{" in s:
        match=pattern.search(s)
        if not match:raise ValueError("unbalanced nested source templates")
        parts=match.group(1).split("|");name=parts[0].strip().lower();args=parts[1:]
        value="\n" if name in {"dhr","rule"} else (args[-1] if name=="fs" and args else args[0] if args else "")
        s=s[:match.start()]+value+s[match.end():]
    s=re.sub(r"<[^>]*>","",s);return "\n".join(line.strip() for line in s.splitlines() if line.strip())
def _indexed_scan_position_count(index_text: str, expected_pagelist: str) -> int:
    matches = re.findall(r"<pagelist\b[^>]*?/>", index_text, flags=re.I | re.S)
    normalize = lambda value: re.sub(r"\s+", " ", value).strip()
    if len(matches) != 1 or normalize(matches[0]) != normalize(expected_pagelist):
        raise ValueError("Index source pagelist differs from its bound profile")
    entries = [
        (int(start), int(end) if end else int(start))
        for start, end in re.findall(r"(?m)^\s*(\d+)(?:\s*to\s*(\d+))?\s*=", matches[0])
    ]
    if not entries or entries[0][0] != 1:
        raise ValueError("Index source pagelist does not begin at scan position 1")
    previous_end = 0
    for start, end in entries:
        if start <= previous_end or end < start:
            raise ValueError("Index source pagelist has overlapping or reversed scan ranges")
        previous_end = end
    return previous_end


def _retained_scan_positions(profile: Mapping[str, object]) -> list[int]:
    transclusion = profile["transclusion"]
    positions = []
    for title in transclusion["included_page_titles"]:
        match = re.fullmatch(r"Page:.*/(\d+)", title)
        if match is None:
            raise ValueError("profile Page title has no numeric scan position")
        positions.append(int(match.group(1)))
    expected = list(range(int(transclusion["from_page"]), int(transclusion["to_page"]) + 1))
    if positions != expected:
        raise ValueError("profile Page titles differ from the declared scan interval")
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


def _catalog_link_findings(profile: Mapping[str, object], account: Mapping[str, object], root: etree._Element) -> list[str]:
    findings: list[str] = []
    link = profile.get("work_catalog_link")
    if not isinstance(link, dict):
        return ["profile lacks canonical WorkCatalog linkage evidence"]
    identity = link.get("identity")
    expected = {"work_id":"chrysostom-divine-and-sacred-liturgy","textual_form_id":"chrysostom-divine-and-sacred-liturgy-wikisource-retained","edition_id":"chrysostom-divine-and-sacred-liturgy-wikisource-electronic","acquisition_id":"chrysostom-divine-and-sacred-liturgy-wikisource-acquired","title":"Service of the Divine and Sacred Liturgy of our Holy Father John Chrysostom"}
    if identity != expected:
        findings.append("WorkCatalog linkage identity differs from existing canonical L594 identity")
        return findings
    if root.get(X+"id") != identity["work_id"]:
        findings.append("TEI root xml:id does not match canonical WorkCatalog work_id")
    if account.get("work_id") != identity["work_id"] or account.get("textual_form_id") != identity["textual_form_id"] or account.get("edition_id") != identity["edition_id"] or account.get("acquisition_id") != identity["acquisition_id"] or account.get("work_catalog_link") != link:
        findings.append("candidate accountability does not bind the exact canonical WorkCatalog identity")
    workspace = Path(str(link.get("canonical_workspace_root", "")))
    rows = link.get("sidecars")
    if not isinstance(rows, list) or len(rows) != 3:
        return findings + ["WorkCatalog link must declare exactly work, state, and acquisition sidecars"]
    payloads: dict[str, dict[str, object]] = {}
    for row in rows:
        try:
            data = (workspace / str(row["path"])).read_bytes()
            if len(data) != row["bytes"] or _sha(data) != row["sha256"]:
                findings.append("WorkCatalog sidecar bytes or SHA-256 differ: " + str(row.get("role")))
                continue
            payloads[str(row["role"])] = json.loads(data)
        except (KeyError, OSError, json.JSONDecodeError, TypeError) as exc:
            findings.append("WorkCatalog sidecar cannot be verified: " + str(exc))
    work, state, acquisition = payloads.get("work", {}), payloads.get("state", {}), payloads.get("acquisition", {})
    if work.get("work_id") != identity["work_id"] or work.get("title") != identity["title"]:
        findings.append("canonical WorkCatalog work record differs from the L594 source title")
    forms = [item for item in work.get("textual_forms", []) if item.get("textual_form_id") == identity["textual_form_id"]]
    editions = [item for form in forms for item in form.get("editions", []) if item.get("edition_id") == identity["edition_id"]]
    if not editions or identity["acquisition_id"] not in editions[0].get("acquisition_ids", []):
        findings.append("canonical WorkCatalog form, edition, and acquisition relationship differs")
    targets = {(item.get("target_type"), item.get("target_id")) for item in state.get("targets", []) if isinstance(item, dict)}
    if state.get("work_id") != identity["work_id"] or ("edition", identity["edition_id"]) not in targets or ("acquisition", identity["acquisition_id"]) not in targets:
        findings.append("canonical WorkCatalog state does not target the linked edition and acquisition")
    source = link.get("source", {})
    if acquisition.get("acquisition_id") != identity["acquisition_id"] or acquisition.get("edition_id") != identity["edition_id"] or not any(item.get("path") == source.get("logical_path") and item.get("bytes") == source.get("bytes") and item.get("sha256") == source.get("sha256") for item in acquisition.get("retained_files", [])):
        findings.append("canonical WorkCatalog acquisition does not bind the exact retained L594 source")
    return findings


def _oracle(manifest:SourceManifest,candidate:CandidatePackage)->Mapping[str,object]:
    problems=[];raw=manifest.authority_path("official-source-member").read_bytes();profile=json.loads(manifest.authority_path("profile").read_bytes());policy=json.loads(manifest.authority_path("policy").read_bytes());receipt=json.loads(manifest.authority_path("acquisition-receipt").read_bytes());root=ET.fromstring(raw);source_pages=root.findall(MW+"page")
    observed=[]
    for p in source_pages:
        title=p.findtext(MW+"title");rev=p.find(MW+"revision");node=rev.find(MW+"text") if rev is not None else None;text=node.text or "" if node is not None else "";b=text.encode("utf-8")
        observed.append({"title":title,"namespace":int(p.findtext(MW+"ns") or 0),"page_id":p.findtext(MW+"id"),"revision_id":rev.findtext(MW+"id") if rev is not None else None,"timestamp":rev.findtext(MW+"timestamp") if rev is not None else None,"text_bytes":int(node.get("bytes",len(b))) if node is not None else 0,"text_sha256":_sha(b),"role":"work" if title==receipt["work"] else "proofread-page" if title.startswith("Page:") else "index" if title.startswith("Index:") else "support"})
    if len(source_pages)!=81 or observed!=profile.get("records"):problems.append("81-record page/revision/text inventory differs")
    by_title={p.findtext(MW+"title"):p for p in source_pages};main=by_title.get(receipt["work"]);index_title=profile["transclusion"]["index_page_title"];idx=by_title.get(index_title);page_title=profile["transclusion"]["included_page_titles"][0] if profile["transclusion"]["included_page_titles"] else "";page=by_title.get(page_title)
    main_text=_page_text(main) if main is not None else "";index_text=_page_text(idx) if idx is not None else "";page_text=_page_text(page) if page is not None else ""
    try:
        scan_count=_indexed_scan_position_count(index_text,profile["transclusion"]["index_pagelist_raw"])
        retained_positions=_retained_scan_positions(profile)
        page_gaps=_untranscribed_ranges(scan_count,retained_positions)
    except (KeyError,TypeError,ValueError) as exc:
        problems.append("indexed scan-position accounting is invalid: "+str(exc))
        scan_count=None;retained_positions=[];page_gaps=[]
    selector=profile["transclusion"]["source_selector"]
    if selector not in main_text or f'from={profile["transclusion"]["from_page"]} to={profile["transclusion"]["to_page"]}' not in selector:problems.append("root transclusion selector differs")
    if profile["transclusion"]["index_pagelist_raw"] not in index_text or "|Transclusion=yes" not in index_text:problems.append("Index pagelist/transclusion metadata differs")
    c=etree.fromstring(candidate.member_bytes("content.tei.xml"));txt=c.find(T+"text");heads=c.findall(T+"teiHeader/"+T+"fileDesc/"+T+"titleStmt/"+T+"title")
    if c.tag!=T+"TEI" or len([n for n in c.iter() if n.tag==T+"TEI"])!=1:problems.append("candidate must be one P5 TEI root")
    if len(heads)!=1 or (heads and (heads[0].text or "")!=receipt["work"]):problems.append("candidate title does not match root source page")
    if manifest.record.get("work_id") != profile.get("work_id") or manifest.record.get("textual_form_id") != profile.get("textual_form_id") or manifest.record.get("edition_id") != profile.get("edition_id") or manifest.record.get("acquisition_id") != profile.get("acquisition_id"):
        problems.append("source manifest identity differs from canonical source profile")
    front=txt.find(T+"front") if txt is not None else None;tp=front.find(T+"titlePage") if front is not None else None;lines=[n.text or "" for n in tp.findall(T+"ab")] if tp is not None else []
    expected_title=" ".join(_flat(page_text).split()); actual_title=" ".join(" ".join(tp.itertext()).split()) if tp is not None else ""
    if actual_title!=expected_title:problems.append("readable title page text/order differs from retained Page transcription")
    if tp is None or tp.get("n")!=(str(retained_positions[0]) if retained_positions else None):problems.append("title-page scan position differs from retained Page title")
    notes={n.get("type"):"".join(n.itertext()) for n in c.iter(T+"ab") if n.get("type")}
    if notes.get("root-wikitext")!=main_text:problems.append("root source wikitext differs")
    if notes.get("page-7-wikitext")!=page_text:problems.append("Page 7 source wikitext differs")
    if notes.get("wikisource-index-wikitext")!=index_text:problems.append("Index source wikitext differs")
    actual_refs=[n.text for n in c.iter(T+"ref") if n.text];expected_refs=profile["transclusion"]["linked_subpages"]
    if actual_refs!=expected_refs:problems.append("linked subpage titles/order differ")
    actual_page_gaps=[]
    for gap in c.iter(T+"gap"):
        if gap.get("reason")=="not-transcribed":
            parent=gap.getparent()
            actual_page_gaps.append({"container":parent.tag if parent is not None else None,"n":gap.get("n"),"quantity":gap.get("quantity"),"unit":gap.get("unit")})
    expected_page_gaps=[]
    if scan_count is not None and retained_positions:
        for first,last in page_gaps:
            container=T+"front" if last<retained_positions[0] else T+"body"
            expected_page_gaps.append({"container":container,"n":f"{first}-{last}","quantity":str(last-first+1),"unit":"scan-position"})
    if actual_page_gaps!=expected_page_gaps:problems.append("indexed page gap positions differ from the retained Index pagelist")
    account=json.loads(candidate.member_bytes("source-accountability.json"))
    if account.get("source_sha256")!=_sha(raw) or account.get("export_records")!=profile["records"] or account.get("transclusion")!=profile["transclusion"]:problems.append("source accountability differs from complete export profile")
    problems.extend(_catalog_link_findings(profile, account, c))
    expected_scan_accounting=None
    if scan_count is not None and retained_positions:
        expected_scan_accounting={"index_page_title":profile["transclusion"]["index_page_title"],"indexed_positions":{"first":1,"last":scan_count,"count":scan_count},"retained_positions":[{"page_title":title,"position":position} for title,position in zip(profile["transclusion"]["included_page_titles"],retained_positions)],"untranscribed_ranges":[{"first":first,"last":last,"count":last-first+1} for first,last in page_gaps],"untranscribed_count":sum(last-first+1 for first,last in page_gaps)}
    if account.get("scan_position_accounting")!=expected_scan_accounting:problems.append("source accountability scan-position inventory differs from the retained Index pagelist")
    if account.get("record_disposition")!={"work":1,"proofread-page":1,"index":1,"support":78}:problems.append("record disposition counts differ")
    if account.get("tei_sha256")!=_sha(candidate.member_bytes("content.tei.xml")) or account.get("tei_bytes")!=len(candidate.member_bytes("content.tei.xml")):problems.append("TEI byte accounting differs")
    if candidate.member_bytes("README.source.md")!=manifest.authority_path("readme").read_bytes():problems.append("source README differs")
    if json.loads(candidate.member_bytes("provenance.json"))!=policy["provenance"]:problems.append("provenance differs")
    if candidate.member_bytes("unresolved.jsonl")!=b"".join(_json(i) for i in policy["unresolved"]):problems.append("unresolved scope ledger differs")
    schema=etree.XMLSchema(etree.parse(str(manifest.authority_path("p5-schema")),etree.XMLParser(resolve_entities=False,no_network=True)))
    if not schema.validate(etree.fromstring(candidate.member_bytes("content.tei.xml"),etree.XMLParser(resolve_entities=False,no_network=True,huge_tree=True))):problems.append("P5 schema invalid: "+str(schema.error_log.last_error))
    oracle_path=Path(__file__).resolve();closure=_sha(_json([{"path":"build/tei/wikisource_l594_chrysostom_oracle_v2.py","sha256":_sha(oracle_path.read_bytes())},{"path":"ocd_kernel/reconstruction/contract.py","sha256":_sha((manifest.repository_root/"ocd_kernel/reconstruction/contract.py").read_bytes())}]))
    att={"status":"pass" if not problems else "fail","oracle_id":ORACLE_ID,"oracle_version":ORACLE_VERSION,"implementation_sha256":_sha(oracle_path.read_bytes()),"import_closure_sha256":closure,"runtime":f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})","source_manifest_sha256":manifest.sha256,"candidate_sha256":candidate.sha256,"profile_sha256":_sha(manifest.authority_path("profile").read_bytes()),"package_schema_sha256":manifest.record["package_schema"]["sha256"],"source_sha256":_sha(raw),"xsd_sha256":_sha(manifest.authority_path("p5-schema").read_bytes()),"policy_sha256":_sha(manifest.authority_path("policy").read_bytes()),"findings":problems}
    att["result_sha256"]=_sha(_json(att));return att
_oracle.oracle_id=ORACLE_ID;_oracle.oracle_version=ORACLE_VERSION;_oracle.implementation_path=Path(__file__).resolve()
