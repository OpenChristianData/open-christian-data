"""Independent html5lib source observer for PG20476 hymn rows and receipts."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping
import html5lib
from lxml import etree
from ocd_kernel.library._common import PipelineError

def check_pg20476_document(tei_path: Path, rows: list[dict[str, Any]], receipt: Mapping[str, Any], *, retained_path: Path, identity: Mapping[str, str], language: str, representation_revision: str, edition_title: str) -> list[str]:
    errors = []
    try:
        digest = lambda b: hashlib.sha256(b).hexdigest()
        canonical = lambda v: json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        raw = retained_path.read_bytes()
        pin = "f6dc73e560c71b0b1f30510317938a139f0f3d57fb29248500460eeb4453002e"
        if len(raw) != 1488071 or digest(raw) != pin or identity.get("work_id") != "hymns-for-christian-devotion" or language not in ("en", "eng"):
            raise PipelineError("PG20476 source checker identity differs")
        source = html5lib.parse(raw, treebuilder="etree", namespaceHTMLElements=False).find("body")
        units = [n for n in source if n.tag == "div" and n.get("class") == "hymn"]
        source_ids = [f"h{i:04d}" for i in range(1, 1009)]
        if [n.get("id") for n in units] != source_ids:
            raise PipelineError("PG20476 source occurrence census/order differs")
        master = etree.fromstring(tei_path.read_bytes(), etree.XMLParser(resolve_entities=False, no_network=True, recover=False))
        ns = {"t":"http://www.tei-c.org/ns/1.0"}
        envelope = master.find("t:text/t:body/t:p", ns)
        if envelope is None or envelope.get("{http://www.w3.org/XML/1998/namespace}id") != "source-html-body-envelope":
            raise PipelineError("PG20476 source body envelope missing")
        native = [n for n in envelope if n.get("type") == "hymn"]
        if [n.get("{http://www.w3.org/XML/1998/namespace}id") for n in native] != source_ids:
            raise PipelineError("PG20476 master hymn occurrence order differs")
        ordinals = {node: number for number,node in enumerate(list(source.iter())[1:],1)}
        normalize = lambda s: (s or "").replace("\r\n","\n").replace("\r","\n")
        def compare(src, target, sequence):
            original = src.tag
            mapped = "ref" if original == "a" else "hi" if original in ("b","i","small","strong") else "lb" if original == "br" else "seg"
            if etree.QName(target).localname != mapped:
                raise PipelineError("PG20476 master source carrier role differs")
            attrs = {"{http://www.w3.org/XML/1998/namespace}id": src.get("id") or f"src-{ordinals[src]:05d}"}
            rend = ["source-tag:"+original]
            if src.get("class"): rend.append("class:"+src.get("class"))
            if src.get("style"): rend.append("style:"+src.get("style"))
            attrs["rend"] = "; ".join(rend)
            if src.get("lang"): attrs["{http://www.w3.org/XML/1998/namespace}lang"]=src.get("lang")
            if original == "a" and src.get("href"): attrs["target"]=src.get("href")
            if mapped == "seg":
                kind = "hymn" if original == "div" and src.get("class") == "hymn" else "stanza" if original == "div" and src.get("class") == "verse" else "verse-line" if original == "div" and src.get("class") in ("l","t") else "html-"+original
                attrs["type"]=kind
                if kind == "hymn": attrs["n"]=str(sequence)
            if dict(target.attrib) != attrs or normalize(src.text) != normalize(target.text) or normalize(src.tail) != normalize(target.tail) or len(src) != len(target):
                raise PipelineError("PG20476 master source attributes, text or attachment differ")
            for child, mapped_child in zip(src,target):
                compare(child,mapped_child,sequence)
        for i,(src,target) in enumerate(zip(units,native),1):
            compare(src,target,i)
        expected=[]
        stanza_total=line_total=deep_total=0
        for i,unit in enumerate(units,1):
            heading_nodes=[n for n in unit if n.tag=="h3"]
            arguments=[n for n in unit if n.tag=="p" and n.get("class")=="argument"]
            if len(heading_nodes)!=1 or not arguments: raise PipelineError("PG20476 source heading/argument differs")
            heading="".join(heading_nodes[0].itertext()).strip()
            notes=[{"text":heading,"place":"unspecified","label":"printed-heading"}]
            stanzas=[]
            for node in unit:
                if node.tag=="h3": continue
                if node.tag=="p" and node.get("class") in ("argument","author"):
                    if node is not arguments[0]:
                        notes.append({"text":"".join(node.itertext()).strip(),"place":"unspecified","label":"printed-attribution" if node.get("class")=="author" else "additional-argument"})
                    continue
                if node.tag!="div" or node.get("class")!="verse": raise PipelineError("PG20476 unaccounted source hymn child")
                lines=[]
                label=None
                for index,line in enumerate(node):
                    if line.tag!="div" or line.get("class") not in ("l","t","t2","t3"): raise PipelineError("PG20476 unaccounted source lyric")
                    pieces=[line.text or ""]
                    for inline in line:
                        if inline.tag=="span" and inline.get("class")=="vn":
                            if index or label is not None: raise PipelineError("PG20476 misplaced source numeral")
                            label=int("".join(inline.itertext()).strip())
                        else:
                            if inline.tag!="i": raise PipelineError("PG20476 unexpected source inline")
                            pieces.append("".join(inline.itertext()))
                        pieces.append(inline.tail or "")
                    value="".join(pieces).strip()
                    if not value: raise PipelineError("PG20476 empty source lyric")
                    lines.append(value)
                    line_total+=1
                    deep_total+=line.get("class") in ("t2","t3")
                stanza_total+=1
                stanzas.append({"number":label if label is not None else len(stanzas)+1,"lines":lines})
            segments=[{"kind":"stanza",**s} for s in stanzas]
            sid=source_ids[i-1]
            value={k:identity[k] for k in ("work_id","textual_form_id","edition_id")}
            text="\n".join(line for s in stanzas for line in s["lines"])
            value.update(record_id=f"{identity['edition_id']}:hymn:{digest(sid.encode())[:20]}",sequence=i,category="hymns",language="eng",text=text,
                         representation_revision=representation_revision,
                         locator={"kind":"hymn-occurrence","text_part":"body","part_titles":[],"divisions":[{"order":i,"type":"source-hymn-occurrence","titles":[heading]}],"occurrence":i},
                         provenance={"edition_title":edition_title},notes=notes,references=[],occurrence_id=sid,
                         hymn_text_id=f"pg20476-{sid}-{digest(canonical(segments))[:16]}",
                         title="".join(arguments[0].itertext()).strip(),first_line=stanzas[0]["lines"][0],stanzas=stanzas,segments=segments)
            expected.append(value)
        if (len(expected),stanza_total,line_total,deep_total)!=(1008,3771,17169,313):
            raise PipelineError("PG20476 complete source stanza/line/deep-indentation census differs")
        if any(n.tag=="a" for unit in units for n in unit.iter()): raise PipelineError("PG20476 unexpected source hymn reference")
        if rows!=expected: errors.append("PG20476 rows differ from independent source wording, stanza attachment, metadata or order")
        schema=Path(__file__).resolve().parents[3]/"schemas/v2/categories/hymns.schema.json"
        fields=dict(mapping_version="ocd-pg20476-native-hymns-v1",assembler_version="ocd-hymns-assembler-provisional-v1",
                    master_sha256=digest(tei_path.read_bytes()),source_sha256=pin,policy_sha256=digest(schema.read_bytes()),
                    common_schema_sha256=digest((schema.parents[1]/"public-row.schema.json").read_bytes()),
                    output_sha256=digest(canonical(expected)),row_count=len(expected),
                    anchors=[dict(record_id=r["record_id"],source_id=r["occurrence_id"],source_order=r["sequence"],text_sha256=digest(r["text"].encode())) for r in expected],
                    inventory=dict(hymn_occurrences=len(expected),verse_divisions=stanza_total,lines=line_total,deeply_indented_lines=deep_total),
                    references=[],unsupported=[],independent_check=dict(status="pending",errors=[]),
                    warnings=["Printed stanza numbers are structured separately; unlabeled stanzas use source order. Line indentation and inline typography remain in the master. Printed attribution is not an inferred author identity."],
                    exclusions=[dict(scope="non-hymn body matter",reason="Provider terms, title matter, section headings, indexes and complete license remain in the master; rows select the 1008 source hymn occurrences.")],
                    source_disposition=dict(textual_member="raw/gutenberg/20476/html/pg20476-images.html",accepted_member_count=1,support_member_count=1,source_order="h0001 through h1008",master_scope="complete retained digital witness"))
        if dict(receipt)!=fields: errors.append("PG20476 projection receipt differs from independent source expectations")
        from .hymns import _validator
        validator = _validator()
        for i,row in enumerate(rows,1):
            for error in validator.iter_errors(row): errors.append(f"PG20476 row {i} schema: {error.message}")
    except (OSError, ValueError, KeyError, TypeError, etree.XMLSyntaxError, PipelineError) as exc:
        errors.append(str(exc))
    return errors



