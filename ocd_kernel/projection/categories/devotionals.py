"""devotionals source-native offline projection and independent correspondence checker.

Only the declared closed profile is supported. Unknown input fails visibly.
Document entry points are experiments; they do not establish master acceptance.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
import xml.etree.ElementTree as ET

import jsonschema
from lxml import etree
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.scripture_authority import BOOK_CODES_PATH, load_book_codes
from ocd_kernel.projection.scripture_targets import normalize_reference_record
from ocd_kernel.projection.scripture_targets_check import observe_reference_record

devotionals = "devotionals"
ROOT = Path(__file__).resolve().parents[3]
SCHEMA = ROOT / "schemas/v2/categories/devotionals.schema.json"
COMMON = ROOT / "schemas/v2/public-row.schema.json"
NS = "{http://www.tei-c.org/ns/1.0}"
XMLID = "{http://www.w3.org/XML/1998/namespace}id"


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _schemas():
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    common = json.loads(COMMON.read_text(encoding="utf-8"))
    registry = Registry().with_resource(common["$id"], Resource.from_contents(common, default_specification=DRAFT202012))
    return schema, jsonschema.Draft202012Validator(schema, registry=registry)


def project_devotionals_document(tei_path, *, identity, language, representation_revision, edition_title):
    """Project complete native units in one explicitly bounded TEI document."""
    path = Path(tei_path)
    raw = path.read_bytes()
    # Reject declarations even for UTF-16 inputs before the XML parser sees them.
    if any(token in raw.replace(b"\x00", b"").upper() for token in (b"<!DOCTYPE", b"<!ENTITY", b"<!--")):
        raise PipelineError("unsupported-visible: XML declarations or comments")
    if re.search(br"<\?(?!xml(?:\s|\?>))", raw.replace(b"\x00", b""), re.IGNORECASE):
        raise PipelineError("unsupported-visible: processing instruction")
    try:
        root = ET.fromstring(raw, parser=ET.XMLParser(target=ET.TreeBuilder(insert_pis=True)))
    except ET.ParseError as exc:
        raise PipelineError(f"invalid devotionals TEI: {exc}") from exc
    schema, validator = _schemas()
    policy = schema["x-ocd-profile"]
    inventory, exclusions, warnings, ids = [], [], [], set()

    def walk(node, in_header=False):
        if not isinstance(node.tag, str) or not node.tag.startswith(NS):
            raise PipelineError("unsupported-visible: namespace or processing instruction")
        tag = node.tag[len(NS):]
        in_header = in_header or tag == "teiHeader"
        elements = policy["header_elements"] if in_header else policy["elements"]
        attributes = policy["header_attributes"] if in_header else policy["attributes"]
        if tag not in elements:
            raise PipelineError(f"unsupported-visible: {tag}")
        allowed = attributes.get(tag, [])
        for key in node.attrib:
            name = "xml:id" if key == XMLID else key
            if name not in allowed:
                raise PipelineError(f"unsupported-visible: {tag}@{name}")
        if node.get(XMLID):
            if node.get(XMLID) in ids:
                raise PipelineError("duplicate native unit identity")
            ids.add(node.get(XMLID))
        if tag == "hi" and node.get("rend") not in policy["renditions"]:
            raise PipelineError("unsupported-visible: rendition")
        if tag == "div" and (node.get("type") != policy["unit_type"] or not node.get(XMLID) or (node.get("n") is not None and not node.get("n", "").strip())):
            raise PipelineError("unsupported-visible: native unit type/identity/number")
        if tag == "ref" and node.get("type") != "citation":
            raise PipelineError("unsupported-visible: reference role")
        in_header = in_header or tag == "teiHeader"
        role = policy["exclusion_reasons"][0] if in_header else "mapped"
        ordinal = len(inventory) + 1
        inventory.append({"ordinal": ordinal, "tag": tag, "role": role})
        if role != "mapped": exclusions.append({"ordinal": ordinal, "reason": role})
        if tag == "hi" and not in_header: warnings.append({"ordinal": ordinal, "reason": policy["warning_reasons"][0]})
        if tag in ("TEI", "teiHeader", "fileDesc", "titleStmt", "publicationStmt", "sourceDesc", "text", "body", "div", "cit", "bibl", "dateline", "lg"):
            if (node.text or "").strip() or any((c.tail or "").strip() for c in node):
                raise PipelineError(f"unsupported-visible: loose text in {tag}")
        for child in node:
            if not isinstance(child.tag, str) or child.tag.removeprefix(NS) not in elements[tag]:
                raise PipelineError(f"unsupported-visible: child of {tag}")
            walk(child, in_header)

    walk(root)
    if root.tag != NS + "TEI" or [c.tag for c in root] != [NS+"teiHeader", NS+"text"]:
        raise PipelineError("unsupported-visible: TEI envelope")
    text = root.find(NS+"text")
    if [c.tag for c in text] != [NS+"body"]:
        raise PipelineError("unsupported-visible: text envelope")
    units = list(text.find(NS+"body"))
    if not units: raise PipelineError("empty native-unit scope")
    rows, anchors = [], []
    book_codes = load_book_codes(BOOK_CODES_PATH)
    def readable(node):
        return " ".join("".join(node.itertext()).split()) if node is not None else None
    def body_references(node):
        references = []
        for ref in node.findall(NS + "ref"):
            record = {"raw": readable(ref)}
            for key in ("cRef", "target"):
                if key in ref.attrib:
                    if not ref.get(key).strip():
                        raise PipelineError("unsupported-visible: empty source reference target")
                    record[key] = ref.get(key)
            references.append(normalize_reference_record(record, book_codes=book_codes))
        return {"references": references} if references else {}
    for sequence, unit in enumerate(units, 1):
        heads, citations = unit.findall(NS+"head"), unit.findall(NS+"cit")
        if len(heads) > 1 or not citations:
            raise PipelineError("unsupported-visible: unit requires at most one heading and at least one reading/quotation")
        heading = readable(heads[0]) if heads else None
        if heads and not heading:
            raise PipelineError("unsupported-visible: supplied heading must contain text")
        row = {k: identity[k] for k in ("work_id", "textual_form_id", "edition_id")}
        row.update(record_id=identity["edition_id"]+":devotionals:"+_hash(unit.get(XMLID).encode())[:20], sequence=sequence, category=devotionals, language=language, representation_revision=representation_revision, provenance={"edition_title": edition_title}, locator={"kind": policy["unit_type"], "number": unit.get("n"), "heading": heading})
        if len(heads) != 1 or not row["locator"]["heading"]: raise PipelineError("unsupported-visible: devotional unit requires one non-empty heading")
        if unit.get("n") is None or not unit.get("n", "").strip(): raise PipelineError("unsupported-visible: devotional unit requires non-empty number")
        if [c.tag for c in unit][:1+len(citations)] != [NS+"head"] + [NS+"cit"] * len(citations): raise PipelineError("unsupported-visible: devotional opening order")
        readings = []
        if sum(cit.get('type') == 'primary-reading' for cit in citations) > 1:
            raise PipelineError('multiple primary devotional readings')
        for cit in citations:
            if cit.get('type') not in (None, 'primary-reading'):
                raise PipelineError('unsupported devotional reading role')
            if [c.tag for c in cit] != [NS+"quote", NS+"bibl"]: raise PipelineError("unsupported-visible: citation order")
            bibl = cit.find(NS+"bibl")
            if bibl is None: raise PipelineError("unsupported-visible: reading bibliography")
            if any(len(bibl.findall(NS+t)) > 1 for t in ("author", "title", "ref")): raise PipelineError("unsupported-visible: citation cardinality")
            if any(r.get("type") != "citation" for r in bibl.findall(NS+"ref")): raise PipelineError("unsupported-visible: citation role")
            if bibl.find(NS+"author") is not None or bibl.find(NS+"title") is not None: raise PipelineError("unsupported-visible: reading bibliography")
            reading_text = readable(cit.find(NS+"quote"))
            if not reading_text: raise PipelineError("unsupported-visible: empty devotional reading")
            readings.append({"text": reading_text, "locus": readable(bibl.find(NS+"ref"))})
            if cit.get('type') == 'primary-reading':
                if not readings[-1]['locus']:
                    raise PipelineError('primary reading requires an explicit reference label')
                readings[-1]['role'] = 'primary'
            reference = bibl.find(NS+"ref")
            if reference is not None:
                targets = {key: reference.get(key) for key in ("cRef", "target") if key in reference.attrib}
                if any(not value.strip() for value in targets.values()):
                    raise PipelineError("unsupported-visible: empty source reference target")
                readings[-1]["source_reference"] = normalize_reference_record(targets, book_codes=book_codes)
        dates = unit.findall(NS+"dateline")
        if len(dates) > 1 or any(len(d) != 1 for d in dates): raise PipelineError("unsupported-visible: date cardinality")
        row["date"] = readable(dates[0][0]) if dates else None
        row["readings"] = readings
        row["divisions"] = []
        for block in unit:
            if block.tag == NS+"p": row["divisions"].append({"kind":"paragraph","text":readable(block), **body_references(block)})
            elif block.tag == NS+"lg": row["divisions"].append({"kind":"verse","lines":[{"text":readable(line),"rendition":line.get("rend"), **body_references(line)} for line in block]})
        if not row["divisions"]: raise PipelineError("unsupported-visible: empty devotional body")
        row["text"] = "\n\n".join(d["text"] if d["kind"] == "paragraph" else "\n".join(line["text"] for line in d["lines"]) for d in row["divisions"])
        errors = list(validator.iter_errors(row))
        if errors: raise PipelineError(f"invalid devotionals row: {errors[0].message}")
        rows.append(row)
        anchors.append({"unit_id": unit.get(XMLID), "record_id": row["record_id"], "text_sha256": _hash(row["text"].encode())})
    receipt = {"scope": "tei-document; context supplied by caller", "mapping_version": policy["version"], "master_sha256": _hash(raw), "policy_sha256": _hash(SCHEMA.read_bytes()), "common_schema_sha256": _hash(COMMON.read_bytes()), "book_codes_sha256": _hash(BOOK_CODES_PATH.read_bytes()), "output_sha256": _hash(_canonical(rows)), "row_count": len(rows), "anchors": anchors, "inventory": inventory, "warnings": warnings, "exclusions": exclusions, "unsupported": [], "independent_check": {"status": "pending"}}
    return {"rows": rows, "receipt": receipt}


def verify_devotionals_document(tei_path, rows, receipt, *, identity, language, representation_revision, edition_title):
    """Recompute correspondence with lxml XPath/event traversal, never the producer."""
    errors = []
    try:
        path = Path(tei_path)
        raw = path.read_bytes()
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        policy = schema["x-ocd-profile"]
        doc = etree.fromstring(raw, parser=etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True))
        if doc.getroottree().docinfo.doctype or doc.xpath('//comment() | //processing-instruction()'):
            raise ValueError("unsupported-visible: declarations/comments/instructions")
        n = {"t": NS[1:-1]}
        inventory, exclusions, warnings = [], [], []
        seen = set()
        # XPath independently identifies each node and its header ancestry.
        for ordinal, node in enumerate(doc.xpath('descendant-or-self::*'), 1):
            q = etree.QName(node)
            tag = q.localname
            header = bool(node.xpath("ancestor-or-self::t:teiHeader", namespaces=n))
            elements = policy["header_elements"] if header else policy["elements"]
            attributes = policy["header_attributes"] if header else policy["attributes"]
            if q.namespace != n["t"] or tag not in elements:
                raise ValueError(f"unsupported-visible: {tag}")
            keys = [("xml:id" if k == XMLID else k) for k in node.attrib]
            if set(keys) - set(attributes.get(tag, [])):
                raise ValueError(f"unsupported-visible: {tag} attributes")
            if node.get(XMLID):
                if node.get(XMLID) in seen: raise ValueError("duplicate native identity")
                seen.add(node.get(XMLID))
            if tag == "hi" and node.get("rend") not in policy["renditions"]: raise ValueError("unsupported-visible: rendition")
            if tag == "div" and (node.get("type") != policy["unit_type"] or not node.get(XMLID) or (node.get("n") is not None and not node.get("n", "").strip())): raise ValueError("unsupported-visible: native identity")
            if tag == "ref" and node.get("type") != "citation": raise ValueError("unsupported-visible: reference role")
            if any(etree.QName(c).namespace != n['t'] or etree.QName(c).localname not in elements[tag] for c in node):
                raise ValueError(f"unsupported-visible: child of {tag}")
            if tag in ("TEI", "teiHeader", "fileDesc", "titleStmt", "publicationStmt", "sourceDesc", "text", "body", "div", "cit", "bibl", "dateline", "lg") and any(str(s).strip() for s in node.xpath('text()')):
                raise ValueError(f"unsupported-visible: loose text in {tag}")
            header = bool(node.xpath('ancestor-or-self::t:teiHeader', namespaces=n))
            role = policy["exclusion_reasons"][0] if header else "mapped"
            inventory.append({"ordinal": ordinal, "tag": tag, "role": role})
            if role != "mapped": exclusions.append({"ordinal": ordinal, "reason": role})
            if tag == "hi" and not header: warnings.append({"ordinal": ordinal, "reason": policy["warning_reasons"][0]})
        if doc.tag != NS+"TEI" or [c.tag for c in doc] != [NS+"teiHeader", NS+"text"] or len(doc.xpath('t:text/*',namespaces=n)) != 1 or not doc.xpath('t:text/t:body',namespaces=n):
            raise ValueError("unsupported-visible: document envelope")
        units = doc.xpath('t:text/t:body/t:div', namespaces=n)
        if not units: raise ValueError("empty native-unit scope")
        expected, anchors = [], []
        book_codes = load_book_codes(BOOK_CODES_PATH)
        for sequence, node in enumerate(units, 1):
            def value(expression):
                found = node.xpath(expression,namespaces=n)
                return ' '.join(''.join(found[0].xpath('.//text()')).split()) if found else None
            heads = node.xpath('t:head',namespaces=n)
            citations = node.xpath('t:cit',namespaces=n)
            if len(heads) > 1 or not citations:
                raise ValueError("unsupported-visible: unit requires at most one heading and at least one reading/quotation")
            heading = value('t:head')
            if heads and not heading:
                raise ValueError("unsupported-visible: supplied heading must contain text")
            item = dict(work_id=identity['work_id'], textual_form_id=identity['textual_form_id'], edition_id=identity['edition_id'], record_id=identity['edition_id']+':devotionals:'+hashlib.sha256(node.get(XMLID).encode('utf-8')).hexdigest()[:20], sequence=sequence, category='devotionals', language=language, representation_revision=representation_revision, provenance={'edition_title':edition_title}, locator={'kind':policy['unit_type'],'number':node.get('n'),'heading':heading})
            if len(node.xpath('t:head',namespaces=n)) != 1 or not node.get('n','').strip(): raise ValueError('unsupported-visible: devotional unit requires one non-empty heading and number')
            citations = node.xpath('t:cit',namespaces=n)
            if [etree.QName(c).localname for c in node][:1+len(citations)] != ['head'] + ['cit'] * len(citations): raise ValueError('unsupported-visible: devotional opening order')
            readings = []
            if len([cit for cit in citations if cit.get('type') == 'primary-reading']) > 1:
                raise ValueError('multiple primary readings')
            for cit in citations:
                if cit.get('type') not in (None, 'primary-reading'):
                    raise ValueError('unsupported reading role')
                if [c.tag for c in cit] != [NS+'quote',NS+'bibl']: raise ValueError('unsupported-visible: citation order')
                bibl_nodes = cit.xpath('t:bibl',namespaces=n)
                if len(bibl_nodes) != 1: raise ValueError('unsupported-visible: reading bibliography')
                bibl = bibl_nodes[0]
                for name in ('author','title','ref'):
                    if len(bibl.xpath('t:'+name,namespaces=n)) > 1: raise ValueError('unsupported-visible: citation cardinality')
                if bibl.xpath('t:author | t:title',namespaces=n): raise ValueError('unsupported-visible: reading bibliography')
                if bibl.xpath('t:ref[not(@type="citation")]',namespaces=n): raise ValueError('unsupported-visible: citation role')
                reading_text = ' '.join(''.join(cit.xpath('t:quote//text()',namespaces=n)).split())
                if not reading_text: raise ValueError('unsupported-visible: empty devotional reading')
                readings.append({'text':reading_text,'locus':' '.join(''.join(bibl.xpath('t:ref//text()',namespaces=n)).split()) if bibl.xpath('t:ref',namespaces=n) else None})
                if cit.get('type') == 'primary-reading':
                    if not readings[-1]['locus']:
                        raise ValueError('primary reading lacks a reference label')
                    readings[-1]['role'] = 'primary'
                reference_nodes = bibl.xpath('t:ref', namespaces=n)
                if reference_nodes:
                    attributes = dict(reference_nodes[0].attrib)
                    source_reference = {}
                    for attribute in ('cRef', 'target'):
                        if attribute in attributes:
                            if not attributes[attribute].strip():
                                raise ValueError('unsupported-visible: empty source reference target')
                            source_reference[attribute] = attributes[attribute]
                    readings[-1]['source_reference'] = observe_reference_record(source_reference, book_codes=book_codes)
            if len(node.xpath('t:dateline',namespaces=n)) > 1 or any(len(d) != 1 for d in node.xpath('t:dateline',namespaces=n)): raise ValueError('unsupported-visible: date cardinality')
            item['date'] = value('t:dateline/t:date')
            item['readings'] = readings
            item['divisions'] = []
            def attached_references(carrier):
                references = []
                for reference in carrier.xpath('t:ref', namespaces=n):
                    record = {'raw': ' '.join(''.join(reference.xpath('.//text()')).split())}
                    for attribute in ('cRef', 'target'):
                        if attribute in reference.attrib:
                            target = reference.attrib[attribute]
                            if not target.strip():
                                raise ValueError('unsupported-visible: empty source reference target')
                            record[attribute] = target
                    references.append(observe_reference_record(record, book_codes=book_codes))
                return {'references': references} if references else {}
            for block in node.xpath('t:p | t:lg',namespaces=n):
                if etree.QName(block).localname == 'p': item['divisions'].append({'kind':'paragraph','text':' '.join(''.join(block.xpath('.//text()')).split()), **attached_references(block)})
                else: item['divisions'].append({'kind':'verse','lines':[{'text':' '.join(''.join(line.xpath('.//text()')).split()),'rendition':line.get('rend'), **attached_references(line)} for line in block.xpath('t:l',namespaces=n)]})
            if not item['divisions']: raise ValueError('unsupported-visible: empty devotional body')
            item['text'] = '\n\n'.join(p['text'] if p['kind']=='paragraph' else '\n'.join(line['text'] for line in p['lines']) for p in item['divisions'])
            expected.append(item)
            anchors.append({'unit_id':node.get(XMLID),'record_id':item['record_id'],'text_sha256':hashlib.sha256(item['text'].encode('utf-8')).hexdigest()})
        if rows != expected: errors.append('source correspondence: rows differ in identity/order/text/structure')
        canonical = json.dumps(expected,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
        expected_receipt = dict(scope='tei-document; context supplied by caller', mapping_version=policy['version'], master_sha256=hashlib.sha256(raw).hexdigest(), policy_sha256=hashlib.sha256(SCHEMA.read_bytes()).hexdigest(), common_schema_sha256=hashlib.sha256(COMMON.read_bytes()).hexdigest(), book_codes_sha256=hashlib.sha256(BOOK_CODES_PATH.read_bytes()).hexdigest(), output_sha256=hashlib.sha256(canonical).hexdigest(), row_count=len(expected), anchors=anchors, inventory=inventory, warnings=warnings, exclusions=exclusions, unsupported=[])
        if set(receipt) != set(expected_receipt) | {'independent_check'}: errors.append('receipt fields differ')
        if receipt.get('independent_check') != {'status':'pending'}: errors.append('receipt independent_check must remain pending')
        for key, value_ in expected_receipt.items():
            if receipt.get(key) != value_: errors.append('receipt correspondence: '+key)
        common = json.loads(COMMON.read_text(encoding='utf-8'))
        registry = Registry().with_resource(common['$id'],Resource.from_contents(common,default_specification=DRAFT202012))
        validator = jsonschema.Draft202012Validator(schema,registry=registry)
        for item in rows:
            errors.extend('schema: '+e.message for e in validator.iter_errors(item))
    except (OSError, ValueError, KeyError, TypeError, etree.XMLSyntaxError) as exc:
        errors.append(str(exc))
    return errors


def project_accepted_devotionals(root, *, acceptance_path):
    """Derive every public context field from validated promoted authority."""
    from ocd_kernel.tei.acceptance import validate_acceptance
    from ocd_kernel.library.identities import edition_by_id, resolve_edition_language
    root = Path(root).resolve()
    acceptance_path = Path(acceptance_path).resolve()
    accepted = validate_acceptance(acceptance_path, root=root)
    if accepted['promotion']['status'] != 'promoted':
        raise PipelineError('projection requires a promoted accepted master')
    work, edition = edition_by_id(root, accepted['identity']['edition_id'], work_id=accepted['identity']["work_id"])
    if edition.record.get('category', work.record.get('category')) != 'devotionals':
        raise PipelineError('accepted edition category mismatch')
    if accepted['identity']['work_id'] == 'daily-light':
        from ocd_kernel.projection.categories.daily_light import project_document
        result = project_document(edition.path, identity={k:accepted['identity'][k] for k in ('work_id','textual_form_id','edition_id')}, language=resolve_edition_language(work.record, edition.record, edition.textual_form_id), representation_revision=accepted['representation_revision']['id'], edition_title=edition.title)
    else:
        result = project_devotionals_document(edition.path, identity={k:accepted['identity'][k] for k in ('work_id','textual_form_id','edition_id')}, language=resolve_edition_language(work.record, edition.record, edition.textual_form_id), representation_revision=accepted['representation_revision']['id'], edition_title=edition.title)
    bindings = {}
    for key, value in {'acceptance':acceptance_path,'work':work.path,'master':edition.path,'acquisition':root/accepted['source']['source_manifest']['path']}.items():
        path = Path(value).resolve()
        try: relative = path.relative_to(root).as_posix()
        except ValueError as exc: raise PipelineError('accepted authority outside root') from exc
        bindings[key] = {'path':relative,'sha256':_hash(path.read_bytes())}
    result['receipt']['authority'] = bindings
    result['receipt']['scope'] = 'tei-document; context derived from validated acceptance'
    return result


def verify_accepted_devotionals(root, *, acceptance_path, rows, receipt):
    """Independently validate authority and then recompute category correspondence."""
    from ocd_kernel.tei.acceptance import validate_acceptance
    from ocd_kernel.library.identities import edition_by_id, resolve_edition_language
    try:
        directory = Path(root).resolve()
        accepted_file = Path(acceptance_path).resolve()
        record = validate_acceptance(accepted_file, root=directory)
        if record['promotion']['status'] != 'promoted': return ['accepted master is not promoted']
        work, edition = edition_by_id(directory,record['identity']['edition_id'], work_id=record['identity']["work_id"])
        if edition.record.get('category',work.record.get('category')) != 'devotionals': return ['accepted category mismatch']
        expected = {}
        for key, path in [('acceptance',accepted_file),('work',Path(work.path)),('master',Path(edition.path)),('acquisition',directory/record['source']['source_manifest']['path'])]:
            resolved = path.resolve()
            expected[key] = {'path':resolved.relative_to(directory).as_posix(),'sha256':hashlib.sha256(resolved.read_bytes()).hexdigest()}
        problems = [] if receipt.get('authority') == expected else ['accepted authority bindings differ']
        if receipt.get('scope') != 'tei-document; context derived from validated acceptance': problems.append('accepted scope label differs')
        document_receipt = {k:v for k,v in receipt.items() if k != 'authority'}
        document_receipt['scope'] = 'tei-document; context supplied by caller'
        if record['identity']['work_id'] == 'daily-light':
            from ocd_kernel.projection.categories.daily_light import verify_document
            problems.extend(verify_document(edition.path,rows,document_receipt,identity={k:record['identity'][k] for k in ('work_id','textual_form_id','edition_id')},language=resolve_edition_language(work.record, edition.record, edition.textual_form_id),representation_revision=record['representation_revision']['id'],edition_title=edition.title))
        else:
            problems.extend(verify_devotionals_document(edition.path,rows,document_receipt,identity={k:record['identity'][k] for k in ('work_id','textual_form_id','edition_id')},language=resolve_edition_language(work.record, edition.record, edition.textual_form_id),representation_revision=record['representation_revision']['id'],edition_title=edition.title))
        return problems
    except (PipelineError,OSError,ValueError,KeyError,TypeError) as exc:
        return [str(exc)]
