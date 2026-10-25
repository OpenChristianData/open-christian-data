"""Retained BCP1928 collects with source breaks, anchor and color preserved."""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re

from bs4 import BeautifulSoup, NavigableString, Tag
from lxml import etree

from build.parsers import bcp1928
from build.tei import bcp_1928_reconstruction as historical

CONVERTER_ID = "ocd-bcp1928-retained-collect-markup"
CONVERTER_VERSION = "2"
NS = "{http://www.tei-c.org/ns/1.0}"
XML = "{http://www.w3.org/XML/1998/namespace}"
TOKEN = re.compile(r"<!--.*?-->|<![^>]*>|<[^>\"']*(?:\"[^\"]*\"|'[^']*'|[^>\"']*)*>|[^<]+|<", re.S)

def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))+"\n").encode()

def _append_text(parent, value):
    if len(parent):
        parent[-1].tail = (parent[-1].tail or "") + value
    else:
        parent.text = (parent.text or "") + value

def _inline(parent, source):
    if isinstance(source, NavigableString):
        _append_text(parent, str(source))
        return
    if not isinstance(source, Tag):
        raise ValueError("unsupported collect fragment carrier")
    if source.name == "br" and not source.attrs:
        etree.SubElement(parent, NS+"lb")
    elif source.name == "a" and source.attrs == {"name":"anchor1121543", "id":"anchor1121543"} and not source.get_text():
        etree.SubElement(parent, NS+"anchor", {XML+"id":"anchor1121543"})
    else:
        raise ValueError(f"unsupported selected collect carrier: {source.name} {source.attrs}")

def _ledger(raw, path, fragment):
    text = raw.decode("utf-8")
    # The whole byte envelope is inventoried; non-collect page material is an
    # explicit exclusion from this collect selection, never a hidden omission.
    begin = text.find(fragment) if fragment else -1
    if fragment and (begin < 0 or text.find(fragment, begin+1) >= 0):
        raise ValueError("selected collect fragment is not unique in source")
    end = begin+len(fragment) if fragment else -1
    tokens = []
    cursor = 0
    for position, match in enumerate(TOKEN.finditer(text), 1):
        if match.start() != cursor:
            raise ValueError("source lexical inventory has a gap")
        literal = match.group()
        tokens.append({"position":position,"start":match.start(),"end":match.end(),
            "kind":"markup" if literal.startswith("<") else "text",
            "sha256":sha256(literal.encode()).hexdigest(),
            "disposition":"selected-collect-carrier" if begin >= 0 and match.start() >= begin and match.end() <= end else "outside-collect-selection"})
        cursor = match.end()
    if cursor != len(text):
        raise ValueError("source lexical inventory does not cover source")
    return {"path":path,"bytes":len(raw),"sha256":sha256(raw).hexdigest(),
        "characters":len(text),"selected_fragment_start":begin,"selected_fragment_end":end,
        "tokens":tokens,"exclusion_reason":"Other propers, hymns, navigation, styling, scripts and provider page material are outside this explicitly partial collect selection; their exact bytes remain retained."}

def _convert(manifest):
    payloads = dict(historical._convert(manifest))
    old = etree.fromstring(payloads["content.tei.xml"])
    root = etree.Element(NS+"TEI", nsmap={None:NS[1:-1]})
    header = old[0]
    revision = header.find(NS+"revisionDesc")
    revision.set("status","candidate")
    revision[0].attrib.pop("status")
    root.append(header)
    text = etree.SubElement(root, NS+"text")
    # Empty front is a declared, reversible native-document routing marker.
    etree.SubElement(text, NS+"front")
    body = etree.SubElement(text, NS+"body")
    account = json.loads(payloads["source-accountability.json"])
    by_path = {}
    for record in account["records"]:
        by_path.setdefault(record["source_path"], []).append(record)
    ledger = []
    features = Counter()
    for member in manifest.record["source_members"]:
        path = str(member["path"])
        raw = (manifest.repository_root/path).read_bytes()
        cleaned = bcp1928.strip_scripts(raw.decode("utf-8"))
        fragment = bcp1928.extract_collect_html_block(cleaned)
        ledger.append(_ledger(raw,path,fragment))
        page = etree.SubElement(body,NS+"div",type="source-page",n=str(member["logical_name"]))
        page.set(XML+"id","page-"+re.sub(r"[^a-zA-Z0-9]+","-",str(member["logical_name"])).strip("-").lower())
        records = by_path.get(path,[])
        if not records:
            if fragment:
                raise ValueError("unaccounted source collect fragment")
            etree.SubElement(page,NS+"note",type="source-page-without-collect").text = "No collect is present in the retained HTML; the alternate witness claim remains unresolved."
            continue
        etree.SubElement(page,NS+"head").text = records[0]["title"]
        paragraph = etree.SubElement(page,NS+"p")
        soup = BeautifulSoup(fragment,"html.parser",preserve_whitespace_tags={"[document]","font"})
        if len(records)==1:
            segment = etree.SubElement(paragraph,NS+"seg",type="collect",n=records[0]["id"])
            segment.set(XML+"id",records[0]["tei_id"])
            for node in soup.contents:
                _inline(segment,node)
            if " ".join("".join(segment.itertext()).split()) != records[0]["text"]:
                raise ValueError("native collect wording differs from retained extraction")
        else:
            if len(records)!=3 or str(member["logical_name"]).lower()!="goodfriday.html":
                raise ValueError("unknown plural collect source")
            font = soup.find("font")
            if font is None or font.attrs!={"color":"#000000"} or any(str(n).strip() for n in soup.contents if n is not font):
                raise ValueError("Good Friday source wrapper differs")
            wrapper = etree.SubElement(paragraph,NS+"hi",rend="color:#000000")
            current = None
            index = 0
            for node in font.contents:
                if current is not None and " ".join("".join(current.itertext()).split())==records[index]["text"]:
                    current = None
                    index += 1
                if current is None and isinstance(node,Tag) and node.name=="br":
                    _inline(wrapper,node)
                    continue
                if current is None and isinstance(node,NavigableString) and not str(node).strip():
                    _append_text(wrapper,str(node))
                    continue
                if current is None:
                    if index>=len(records):raise ValueError("extra Good Friday source wording")
                    current=etree.SubElement(wrapper,NS+"seg",type="collect",n=records[index]["id"])
                    current.set(XML+"id",records[index]["tei_id"])
                _inline(current,node)
            if current is not None:
                if " ".join("".join(current.itertext()).split())!=records[index]["text"]:raise ValueError("Good Friday final collect differs")
                index += 1
            if index!=3:raise ValueError("Good Friday source segmentation differs")
        for node in paragraph.iter():features[etree.QName(node).localname]+=1
    native = etree.tostring(root,encoding="UTF-8",xml_declaration=True,pretty_print=False)
    account["tei"]={"bytes":len(native),"sha256":sha256(native).hexdigest()}
    account["schema"]="sources/prayers/bcp-1928-collects/bcp1928-current.source-accountability.schema.json"
    account["carrier_ledger"]={"status":"partial-collect-selection","members":ledger,"features":dict(features),"unbound_manual_claims":["trinity23","trinity24"],"routing_front":"empty native-document marker, no source content"}
    payloads["content.tei.xml"] = native
    payloads["source-accountability.json"] = canonical(account)
    return payloads

_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()
