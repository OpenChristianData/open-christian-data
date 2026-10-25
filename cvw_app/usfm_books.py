"""Read explicit USFM transcriptions and semantic Bible blocks as books."""

from cvw_app.renderer_nodes import _node, _local_name, _finalize_structure, _heading_contexts, project_visible_text
from cvw_app.structured_text import render_structured_text

XML_ID='{http://www.w3.org/XML/1998/namespace}id'


def usfm_tei_book(root):
    bodies=[e for e in root.iter() if _local_name(e.tag)=='body']
    if not bodies:
        return None
    if len(bodies)>1:
        parents={child:parent for parent in root.iter() for child in parent}
        nodes,outline=[],[]
        for number,body in enumerate(bodies,1):
            rendered=usfm_tei_book(body)
            if rendered is None:
                return None
            parent=parents.get(body)
            label=parent.get('n') if parent is not None else None
            prefix=(parent.get(XML_ID) if parent is not None else None) or f'witness-{number}'
            nodes.append(_node('heading',label or f'Witness {number}',level=1,location=prefix))
            outline.append(dict(location=prefix,label=label or f'Witness {number}',level=1))
            for node in rendered['nodes']:
                if node.get('type')=='heading':
                    node['level']=min(6,node.get('level',1)+1)
                if node.get('location'):
                    node['location']=f'{prefix}-{node["location"]}'
            nodes.extend(rendered['nodes'])
            outline.extend({**item,'level':min(6,item['level']+1),'location':f'{prefix}-{item["location"]}','label':f'{label or number}: {item["label"]}'} for item in rendered['outline'])
        return _finalize_structure('tei-reader',nodes,outline,_heading_contexts(nodes,outline))
    body=bodies[0]
    raw_lines=[e for e in body.iter() if e.get('type')=='usfm-source-line']
    if raw_lines:
        books=[e for e in body.iter() if _local_name(e.tag)=='div' and e.get('type')=='book']
        if not books or sum(len([e for e in book.iter() if e.get('type')=='usfm-source-line']) for book in books)!=len(raw_lines):
            return None
        nodes,outline=[],[]
        for number,book in enumerate(books,1):
            lines=[e for e in book.iter() if e.get('type')=='usfm-source-line']
            if any(len(e) for e in lines):
                return None
            rendered=render_structured_text('text/x-usfm','\n'.join(e.text or '' for e in lines))
            if rendered is None:
                return None
            prefix=book.get(XML_ID) or f'usfm-book-{number}'
            for node in rendered['nodes']:
                if node.get('location'):
                    node['location']=f'{prefix}-{node["location"]}'
            nodes.extend(rendered['nodes'])
            outline.extend({**item,'location':f'{prefix}-{item["location"]}','label':f'{book.get("n") or number}: {item["label"]}'} for item in rendered['outline'])
        return _finalize_structure('tei-reader',nodes,outline,_heading_contexts(nodes,outline))
    if not any((e.get('type') or '').startswith('usfm-') for e in body.iter()):
        return None
    nodes,outline,metadata=[],[],[]
    book_label=''
    serial=0

    def text(element):
        parts=[element.text or '']
        for child in element:
            if child.get('type') not in {'source-usfm-raw','source-feature-annotation'}:
                parts.append('\n' if _local_name(child.tag)=='lb' else text(child))
            parts.append(child.tail or '')
        return ''.join(parts)

    def heading(value,element,level=2):
        nonlocal serial
        serial+=1
        location=element.get(XML_ID) or f'usfm-unit-{serial}'
        nodes.append(_node('heading',project_visible_text(value),level=level,location=location))
        outline.append(dict(location=location,label=project_visible_text(f'{book_label}: {value}' if book_label and level>1 else value),level=level))

    def visit(element):
        nonlocal book_label
        name,kind=_local_name(element.tag),element.get('type','')
        if kind=='source-usfm-raw':
            # These duplicate the semantic verse and remain available in the original TEI.
            return
        if kind=='source-feature-annotation':
            value=project_visible_text(''.join(element.itertext()))
            if value:
                metadata.append(_node('paragraph',f'Source annotation: {value}'))
            return
        if kind in {'usfm-id','usfm-ide','usfm-h','usfm-toc1','usfm-toc2','usfm-toc3','usfm-rem'}:
            value=project_visible_text(text(element))
            if value:
                metadata.append(_node('paragraph',f'{kind.removeprefix("usfm-")}: {value}'))
            return
        if name=='div' and kind in {'book','paratext'}:
            book_label=next((project_visible_text(text(e)) for e in element if e.get('type')=='usfm-h'),element.get('n') or 'Book')
            heading(book_label,element,1)
        elif name=='div' and kind=='chapter':
            heading(f'Chapter {element.get("n") or ""}'.strip(),element)
        elif name=='head' or kind.startswith('usfm-mt'):
            value=text(element)
            if value.strip():
                heading(value,element,3)
            return
        elif name in {'ab','p','note'}:
            value=project_visible_text(text(element))
            if value:
                if kind=='verse' and element.get('n'):
                    value=f'{element.get("n")} {value}'
                nodes.append(_node('paragraph',value))
            return
        for child in element:
            visit(child)
    visit(body)
    if metadata:
        nodes.insert(0,_node('details','About this source',children=metadata))
    return _finalize_structure('tei-reader',nodes,outline,_heading_contexts(nodes,outline)) if nodes else None
