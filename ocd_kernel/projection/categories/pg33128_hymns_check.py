"""PG33128 HTML oracle independent of the TEI hymn-row producer."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping
import html5lib
from lxml import etree
from ocd_kernel.library._common import PipelineError


def check_pg33128_document(tei_path: Path, rows: list[dict[str, Any]], receipt: Mapping[str, Any], *, retained_path: Path, identity: Mapping[str, str], language: str, representation_revision: str, edition_title: str) -> list[str]:
    errors: list[str] = []
    try:
        digest = lambda value: hashlib.sha256(value).hexdigest()
        canonical = lambda value: json.dumps(value, ensure_ascii=False,sort_keys=True,separators=(",", ":")).encode("utf-8")
        raw = retained_path.read_bytes()
        source_hash = "da72fc391ad5d0f599293ba91194a247e7303a1f77d0eb09bba9bed71228b135"
        if len(raw) != 185532 or digest(raw) != source_hash:
            raise PipelineError("PG33128 checker source identity differs")
        if identity.get("work_id") != "l744-pg33128-gospel-hymns" or language != "mul":
            raise PipelineError("PG33128 checker work or edition language differs")
        html = html5lib.parse(raw,treebuilder="etree",namespaceHTMLElements=False)
        body = html.find("body")
        collection = next(node for node in body.iter() if node.get("id") == "h")
        units = [node for node in collection if node.tag == "div" and node.get("id", "").startswith("h")]
        expected_ids = []
        for number in range(1,39): expected_ids.extend(["h"+str(number),"h"+str(number)+"a"])
        if [node.get("id") for node in units] != expected_ids:
            raise PipelineError("PG33128 source pair census differs")
        xml = etree.fromstring(tei_path.read_bytes(),etree.XMLParser(resolve_entities=False,no_network=True,recover=False))
        by_id = {node.get("{http://www.w3.org/XML/1998/namespace}id"):node for node in xml.iter() if node.get("{http://www.w3.org/XML/1998/namespace}id")}
        ordinals = {node:ordinal for ordinal,node in enumerate(body.iter())}
        parent = {child:node for node in body.iter() for child in node}
        tags = {"div":"div","p":"p","span":"seg","i":"hi","h3":"head"}
        # Compare native master carriers against source independently, rather
        # than deriving master expectations by running any projection function.
        for unit in units:
            native_unit = by_id.get(unit.get("id"))
            if native_unit is None: raise PipelineError("PG33128 master occurrence missing")
            expected_order = [str(ordinals[node]) for node in unit.iter() if isinstance(node.tag,str)]
            actual_order = [node.get("n") for node in native_unit.iter() if node.get("n") is not None]
            if actual_order != expected_order: raise PipelineError("PG33128 master scoped carrier order differs")
            for node in native_unit.iter():
                if node.get("n") is None:
                    wrapper = etree.QName(node).localname == "div" and node.get("type") == "source-block-segment" and not (node.text or "").strip()
                    ancestor = node.getparent()
                    label_parent = ancestor
                    label_path_valid = True
                    while label_parent is not None and label_parent.get("n") is None:
                        if label_parent.get("type") != "source-block-segment" or len(label_parent) != 1:
                            label_path_valid = False
                        label_parent = label_parent.getparent()
                    page_label = etree.QName(node).localname == "p" and dict(node.attrib) == {"rend":"source-direct-text"} and label_path_valid and label_parent is not None and label_parent.get("rend") == "source-class:page_break" and len(label_parent) == 1
                    if not wrapper and not page_label:
                        raise PipelineError(f"PG33128 master invented or unsupported carrier: {etree.QName(node).localname}, parent={dict(ancestor.attrib) if ancestor is not None else None}, text={(node.text or '')[:30]!r}")
            for source_node in unit.iter():
                if not isinstance(source_node.tag,str): continue
                sid = source_node.get("id") or f"source-node-{ordinals[source_node]}"
                target = by_id.get(sid)
                if target is None or etree.QName(target).localname != tags[source_node.tag]:
                    raise PipelineError(f"PG33128 master source carrier differs: {sid}")
                if "".join(source_node.itertext()).replace("\r\n","\n").replace("\r","\n") != "".join(target.itertext()).replace("\r\n","\n").replace("\r","\n"):
                    raise PipelineError(f"PG33128 master text/attachment differs: {sid}")
                if target.get("n") != str(ordinals[source_node]):
                    raise PipelineError(f"PG33128 master source order differs: {sid}")
                if "class" in source_node.attrib and target.get("rend") != "source-class:"+source_node.get("class"):
                    raise PipelineError(f"PG33128 master source class differs: {sid}")
                if source_node.get("title") is not None and target.get("rend") != "source-title:"+source_node.get("title"):
                    raise PipelineError(f"PG33128 master occurrence title differs: {sid}")
                ancestor = target.getparent()
                while ancestor is not None and ancestor.get("n") is None: ancestor = ancestor.getparent()
                if ancestor is None or ancestor.get("n") != str(ordinals[parent[source_node]]):
                    raise PipelineError(f"PG33128 master parent attachment differs: {sid}")
        actual_units = [node.get("{http://www.w3.org/XML/1998/namespace}id") for node in by_id["h"] if node.get("{http://www.w3.org/XML/1998/namespace}id", "").startswith("h")]
        if actual_units != expected_ids: raise PipelineError("PG33128 master pair order differs")
        expected: list[dict[str,Any]] = []
        for index,unit in enumerate(units):
            source_id = unit.get("id")
            heading = next("".join(node.itertext()).strip() for node in unit if node.tag == "h3")
            notes = []
            tune = None
            stanzas = []
            segments = []
            for node in unit:
                kind = node.get("class")
                if node.tag == "p" and kind in ("meter","srcttl"):
                    notes.append({"text":"".join(node.itertext()).strip(),"place":"unspecified","label":"meter" if kind=="meter" else "source-title"})
                elif node.tag == "p" and kind == "tune": tune = "".join(node.itertext()).strip()
                elif node.tag == "div" and kind == "verse":
                    lines = []
                    label = None
                    number = None
                    for paragraph in node:
                        text_parts = [paragraph.text or ""]
                        for child in paragraph:
                            if child.get("class") == "vn":
                                number = int("".join(child.itertext()).strip())
                            else: text_parts.append("".join(child.itertext()))
                            text_parts.append(child.tail or "")
                        text = "".join(text_parts).strip()
                        if paragraph.get("class") == "vno":
                            # Literal source chorus prefixes, independently
                            # parsed without the producer's regex or line reader.
                            for prefix in ("Chorus:—","Chorus.—","Cho.—","Chorus:","Chorus."):
                                if text.startswith(prefix):
                                    label = prefix
                                    remainder = text[len(prefix):].strip()
                                    if remainder: lines.append(remainder)
                                    break
                            else: raise PipelineError("PG33128 source chorus label differs")
                        else: lines.append(text)
                    if label is None:
                        stanza = {"number":number if number is not None else len(stanzas)+1,"lines":lines}
                        stanzas.append(stanza)
                        segments.append({"kind":"stanza",**stanza})
                    else: segments.append({"kind":"refrain","label":label,"lines":lines})
            value = {key:identity[key] for key in ("work_id","textual_form_id","edition_id")}
            sequence = index+1
            text = "\n".join(line for segment in segments for line in segment["lines"])
            value.update(record_id=f"{identity['edition_id']}:hymn:{digest(source_id.encode())[:20]}",sequence=sequence,category="hymns",language="mul",text=text,representation_revision=representation_revision,
                         locator={"kind":"hymn-occurrence","text_part":"body","part_titles":[],"divisions":[{"order":sequence,"type":"source-hymn-occurrence","titles":[heading]}],"occurrence":sequence},provenance={"edition_title":edition_title},notes=notes,references=[],occurrence_id=source_id,hymn_text_id=f"pg33128-{source_id}-{digest(canonical(segments))[:16]}",title=unit.get("title"),first_line=stanzas[0]["lines"][0],stanzas=stanzas,segments=segments)
            if tune is not None: value["tune"]=tune
            choruses = [segment for segment in segments if segment["kind"]=="refrain"]
            if choruses: value["refrain"]={"label":choruses[0]["label"],"lines":choruses[0]["lines"]}
            expected.append(value)
        if rows != expected:
            errors.append("PG33128 rows differ from independent source hymn, stanza, line, label, metadata or order expectations")
        schema = Path(__file__).resolve().parents[3]/"schemas/v2/categories/hymns.schema.json"
        common = schema.parents[1]/"public-row.schema.json"
        expected_fields = dict(mapping_version="ocd-pg33128-native-hymns-v1",assembler_version="ocd-hymns-assembler-provisional-v1",master_sha256=digest(tei_path.read_bytes()),source_sha256=source_hash,policy_sha256=digest(schema.read_bytes()),common_schema_sha256=digest(common.read_bytes()),output_sha256=digest(canonical(expected)),row_count=76,
                               anchors=[dict(record_id=row["record_id"],source_id=row["occurrence_id"],source_order=row["sequence"],text_sha256=digest(row["text"].encode())) for row in expected],
                               inventory=dict(hymn_pairs=38,hymn_occurrences=76,verse_divisions=390,refrain_bodies=6,lines=sum(len(segment["lines"]) for row in expected for segment in row["segments"])),references=[],unsupported=[],independent_check=dict(status="pending",errors=[]))
        for key,value in expected_fields.items():
            if receipt.get(key) != value: errors.append(f"PG33128 receipt {key} differs")
        excluded = {item.get("scope"):item.get("reason") for item in receipt.get("exclusions",[]) if isinstance(item,dict)}
        expected_exclusions = {
            "pg-header":"provider title, credit and terms remain in master and visible source notices",
            "titlepg":"printed title matter remains in complete master",
            "index_e,index_o":"indexes remain in complete master; hymn rows follow collection order",
            "phonics":"pronunciation key remains in complete master",
            "pg-footer":"complete retained license remains in master and data-path license notice",
            "page_break and display typography":"display markers remain in master; stanza numbers and chorus labels are explicitly structured",
            "archive, cover, receipt, inventory":"hash-bound retained support members are not hymn text",
        }
        if excluded != expected_exclusions or len(receipt.get("exclusions",[])) != len(expected_exclusions):
            errors.append("PG33128 receipt source exclusions differ")
        if receipt.get("source_disposition") != dict(textual_member="raw/gutenberg/33128/html/pg33128-images.html",support_member_count=4,accepted_member_count=5,source_order="h1,h1a through h38,h38a",master_scope="complete retained digital witness"):
            errors.append("PG33128 receipt source envelope disposition differs")
        allowed_fields = set(expected_fields)|{"warnings","exclusions","source_disposition"}
        expected_warnings = ["Edition language mul records the source-labeled bilingual collection; no individual Ojibway language code or print collation is asserted."]
        if set(receipt)!=allowed_fields or receipt.get("warnings") != expected_warnings:
            errors.append("PG33128 receipt contract fields or warnings differ")
        from .hymns import _validator
        validator=_validator()
        for index,row in enumerate(rows,1):
            for finding in validator.iter_errors(row): errors.append(f"PG33128 row {index} schema: {finding.message}")
    except (OSError,ValueError,KeyError,TypeError,StopIteration,etree.XMLSyntaxError,PipelineError) as exc:
        errors.append(str(exc))
    return errors
