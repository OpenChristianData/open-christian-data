from __future__ import annotations
import json, re
from hashlib import sha256
from pathlib import Path
from lxml import etree

TEI = "http://www.tei-c.org/ns/1.0"
XML = "{http://www.w3.org/XML/1998/namespace}"
TOKEN = re.compile(r"\\(?P<tag>\+?[A-Za-z][A-Za-z0-9]*)(?P<close>\*)?")
OPEN_MAP = {
    "w": ("w", {}), "+w": ("w", {"type": "usfm-plus-w"}),
    "wj": ("q", {"type": "words-of-Jesus"}),
    "+wh": ("foreign", {XML+"lang": "he"}),
    "qs": ("seg", {"type": "selah"}),
    "bk": ("title", {"type": "biblical-book"}),
    "k": ("term", {}),
}
FIELD_MAP = {
    "fr": ("ref", {"type": "source-label"}),
    "xo": ("ref", {"type": "source-origin"}),
    "ft": ("seg", {"type": "footnote-text"}),
    "xt": ("ref", {"type": "source-target"}),
    "fqa": ("seg", {"type": "alternate-reading"}),
    "fq": ("seg", {"type": "quoted-reading"}),
}

def _add_text(parent, text):
    if not text:
        return
    if len(parent):
        parent[-1].tail = (parent[-1].tail or "") + text
    else:
        parent.text = (parent.text or "") + text

def _parse_inline(parent, value, base_pointer):
    matches = list(TOKEN.finditer(value))
    if not matches:
        _add_text(parent, value)
        return {}
    stats = {}
    stack = []
    active_field = None
    pending_caller = False
    last = 0
    for match in matches:
        between = value[last:match.start()]
        if active_field is not None:
            field_node, field_start = active_field
            field_node.set("corresp", f"{base_pointer}&span={field_start}:{match.start()}")
        if pending_caller:
            caller = re.match(r"^(\s*)\+(\s*)", between)
            if caller:
                note = next((entry[1] for entry in reversed(stack) if entry[0] in {"f", "x"}), None)
                if note is None:
                    raise ValueError("USFM caller marker without note scope")
                target = active_field[0] if active_field is not None else note
                _add_text(target, caller.group(1))
                label = etree.SubElement(note, f"{{{TEI}}}label", type="caller")
                label.text = "+"
                _add_text(target, caller.group(2))
                between = between[caller.end():]
            pending_caller = False
        target = active_field[0] if active_field is not None else (stack[-1][1] if stack else parent)
        _add_text(target, between)
        active_field = None
        tag = match.group("tag")
        closing = bool(match.group("close"))
        stat = tag + ("*" if closing else "")
        stats[stat] = stats.get(stat, 0) + 1
        if tag in {"f", "x"} and not closing:
            node = etree.SubElement(stack[-1][1] if stack else parent, f"{{{TEI}}}note", type="footnote" if tag == "f" else "cross-reference")
            stack.append((tag, node, match.start()))
            pending_caller = True
        elif tag in FIELD_MAP and not closing:
            name, attrs = FIELD_MAP[tag]
            node = etree.SubElement(stack[-1][1] if stack else parent, f"{{{TEI}}}{name}", **attrs)
            active_field = (node, match.start())
        elif closing:
            if not stack or stack[-1][0] != tag:
                raise ValueError(f"unbalanced USFM inline marker {tag}*")
            _, node, start = stack.pop()
            node.set("corresp", f"{base_pointer}&span={start}:{match.end()}")
            if tag in {"w", "+w"}:
                raw = node.text or ""
                word = re.fullmatch(r"(.*?)(?:\|strong=\"([^\"]+)\")?", raw, re.DOTALL)
                if word is None:
                    raise ValueError(f"unparsed Strong's annotation: {raw!r}")
                node.text = word.group(1)
                if word.group(2):
                    node.set("n", word.group(2))
                leading = re.match(r"^\s+", node.text or "")
                if leading:
                    parent_node = node.getparent()
                    position = parent_node.index(node)
                    if position:
                        previous = parent_node[position - 1]
                        previous.tail = (previous.tail or "") + leading.group(0)
                    else:
                        parent_node.text = (parent_node.text or "") + leading.group(0)
                    node.text = (node.text or "")[leading.end():]
        elif tag in OPEN_MAP:
            name, attrs = OPEN_MAP[tag]
            node = etree.SubElement(stack[-1][1] if stack else parent, f"{{{TEI}}}{name}", **attrs)
            stack.append((tag, node, match.start()))
        else:
            raise ValueError(f"unsupported inline USFM marker \\{tag}")
        last = match.end()
    tail = value[last:]
    if pending_caller:
        caller = re.match(r"^(\s*)\+(\s*)", tail)
        if caller:
            note = next((entry[1] for entry in reversed(stack) if entry[0] in {"f", "x"}), None)
            if note is None:
                raise ValueError("USFM caller marker without note scope")
            _add_text(note, caller.group(1))
            label = etree.SubElement(note, f"{{{TEI}}}label", type="caller")
            label.text = "+"
            _add_text(note, caller.group(2))
            tail = tail[caller.end():]
    target = active_field[0] if active_field is not None else (stack[-1][1] if stack else parent)
    _add_text(target, tail)
    if active_field is not None:
        active_field[0].set("corresp", f"{base_pointer}&span={active_field[1]}:{len(value)}")
    if stack:
        raise ValueError(f"unclosed USFM inline scope: {[entry[0] for entry in stack]}")
    return stats

def _convert(manifest):
    assert manifest.record['work_id']=='engwmb'
    raw=manifest.authority_path('previous-content').read_bytes()
    assert sha256(raw).hexdigest()=='4af183d98a800c196648b38bb6108f1a8ffb401a43693787a1fe90337de2c5be'
    result={name:manifest.authority_path('previous-'+name).read_bytes() for name in ['README.source.md','provenance.json','source-accountability.json','unresolved.jsonl']}
    root=etree.fromstring(raw,etree.XMLParser(huge_tree=True,resolve_entities=False,no_network=True))
    totals={}
    for node in list(root.iter()):
        if node.text and '\\' in node.text and node.get('corresp','').startswith('source-usfm:'):
            value=node.text;node.text=None
            for key,count in _parse_inline(node,value,node.get('corresp')).items():totals[key]=totals.get(key,0)+count
    moves=[]
    for head in root.xpath('//t:head[@type="usfm-ms1"]',namespaces={'t':TEI}):
        pointer=head.get('corresp');member,line=pointer.split('/',1)[1].rsplit('#line=',1);number=int(line)
        source=manifest.authority_path('text-'+member).read_text(encoding='utf-8').splitlines()
        chapter=next(x[3:].partition(' ')[0] for x in reversed(source[:number-1]) if x.startswith('\\c '))
        old=head.getparent();book=old.getparent();dest=next(x for x in book if x.get('type')=='chapter' and x.get('n')==chapter)
        assert dict(old.attrib)=={'type':'usfm-heading','n':'ms1-'+str(number)} and len(old)==1 and old.text is None and old.tail is None and head.tail is None
        moves.append(dict(pointer=pointer,chapter=chapter,wrapper_attributes=dict(old.attrib),wrapper_index=book.index(old)))
        old.remove(head);book.remove(old);dest.insert(0,head)
    assert len(moves)==5
    result['content.tei.xml']=etree.tostring(root,encoding='UTF-8',xml_declaration=True,pretty_print=False)
    account=json.loads(result['source-accountability.json']);account['inline_marker_counts']=dict(sorted(totals.items()));account['source_heading_moves']=moves
    result['source-accountability.json']=(json.dumps(account,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
    return result
_convert.converter_id='ocd-l225-engwmb-source-native-successor'
_convert.converter_version='1'
_convert.implementation_path=Path(__file__).resolve()
