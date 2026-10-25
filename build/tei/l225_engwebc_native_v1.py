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
    "+bk": ("title", {"type": "biblical-book"}),
    "k": ("term", {}),
}
FIELD_MAP = {
    "fr": ("ref", {"type": "source-label"}),
    "fl": ("label", {"type": "footnote-label"}),
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


def _line(node,default):
    for child in node.iter():
        pointer=child.get('corresp','')
        if pointer.startswith('source-usfm:') and '#line=' in pointer:
            return int(pointer.split('#line=',1)[1].split('&',1)[0])
    return default

def _convert(manifest):
    import bisect
    assert manifest.record['work_id']=='eng-web-c'
    raw=manifest.authority_path('previous-content').read_bytes()
    assert sha256(raw).hexdigest()=='aff6bb38c3d3d7c5838c4c7b0b4b9ea73e12d63c4100823a0b73449aa8ff7869'
    result={name:manifest.authority_path('previous-'+name).read_bytes() for name in ['README.source.md','provenance.json','source-accountability.json','unresolved.jsonl']}
    root=etree.fromstring(raw,etree.XMLParser(huge_tree=True,resolve_entities=False,no_network=True));totals={}
    for node in list(root.iter()):
        if node.text and '\\' in node.text and node.get('corresp','').startswith('source-usfm:'):
            value=node.text;node.text=None
            for key,count in _parse_inline(node,value,node.get('corresp')).items():totals[key]=totals.get(key,0)+count
    moves=[];sections=[]
    for book in root.xpath('/t:TEI/t:text/t:body/t:div',namespaces={'t':TEI}):
        headings=[]
        for wrapper in list(book):
            if wrapper.get('type')!='usfm-heading' or len(wrapper)!=1 or wrapper[0].get('type') not in {'usfm-ms1','usfm-s1'}:continue
            head=wrapper[0];pointer=head.get('corresp');member,line=pointer.split('/',1)[1].rsplit('#line=',1);number=int(line)
            lines=manifest.authority_path('text-'+member).read_text(encoding='utf-8').splitlines()
            chapter=next(x[3:].partition(' ')[0] for x in reversed(lines[:number-1]) if x.startswith('\\c '))
            assert len(wrapper)==1 and wrapper.text is None and wrapper.tail is None and head.tail is None
            moves.append(dict(pointer=pointer,chapter=chapter,wrapper_attributes=dict(wrapper.attrib),wrapper_index=book.index(wrapper)))
            wrapper.remove(head);book.remove(wrapper);headings.append((chapter,number,head))
        for chapter in book:
            if chapter.get('type')!='chapter':continue
            own=[(number,head) for label,number,head in headings if label==chapter.get('n')]
            if not own:continue
            original=list(chapter);first=own[0][0];chapter_line=int(chapter.get('corresp').rsplit('=',1)[1])
            if not any(node.tag=='{'+TEI+'}ab' and _line(node,chapter_line)<first for node in original):
                assert len(own)==1;chapter.insert(0,own[0][1]);continue
            # Source-defined section heads inside a chapter introduce sibling
            # flow divisions. They never become verse wording or leave the chapter.
            for node in original:chapter.remove(node)
            groups=[etree.SubElement(chapter,'{'+TEI+'}div',type='usfm-section',n='pre-heading')]
            for number,head in own:
                part=etree.SubElement(chapter,'{'+TEI+'}div',type='usfm-section',n='s1-'+str(number));part.append(head);groups.append(part)
            cuts=[number for number,_head in own]
            for node in original:groups[bisect.bisect_right(cuts,_line(node,chapter_line))].append(node)
            sections.append(dict(book=book.get('n'),chapter=chapter.get('n'),headings=[head.get('corresp') for _,head in own],sections=len(groups)))
    assert len(moves)==10 and len(sections)==1 and sections[0]['book']=='DAG' and sections[0]['chapter']=='3' and sections[0]['sections']==3
    result['content.tei.xml']=etree.tostring(root,encoding='UTF-8',xml_declaration=True,pretty_print=False)
    account=json.loads(result['source-accountability.json']);account['inline_marker_counts']=dict(sorted(totals.items()));account['source_heading_moves']=moves;account['source_midchapter_sections']=sections
    result['source-accountability.json']=(json.dumps(account,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
    return result
_convert.converter_id='ocd-l225-engwebc-source-native-successor'
_convert.converter_version='1'
_convert.implementation_path=Path(__file__).resolve()
