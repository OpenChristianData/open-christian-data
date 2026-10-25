"""Read the explicit Hymnary TEI records without traversing metadata twice."""
from cvw_app.renderer_nodes import _node, _local_name, _finalize_structure, _heading_contexts, project_visible_text

XML_ID='{http://www.w3.org/XML/1998/namespace}id'

def hymn_tei_book(root):
    bodies=[e for e in root.iter() if _local_name(e.tag)=='body']
    if len(bodies)!=1 or not len(bodies[0]):
        return None
    records=list(bodies[0])
    if any(e.get('type')!='hymn-record' or [_local_name(c.tag) for c in e]!=['head','ab','list'] or e[1].get('type')!='hymn-text' or e[2].get('type')!='source-metadata' for e in records):
        return None
    nodes,outline=[],[]
    for record in records:
        title,body,metadata=record
        if len(title) or any(_local_name(c.tag) not in {'lb','g'} or len(c) or (_local_name(c.tag)=='lb' and (c.text or '').strip()) for c in body):
            return None
        fields=[]
        for item in metadata:
            if _local_name(item.tag)!='item' or [_local_name(c.tag) for c in item]!=['label','seg'] or any(len(c) for c in item):
                return None
            fields.append(_node('paragraph',project_visible_text(''.join(item.itertext()))))
        label=project_visible_text(title.text or '')
        location=record.get(XML_ID)
        if not label or not location:
            return None
        verse=(body.text or '')+''.join(('\n' if _local_name(line.tag)=='lb' else line.text or '')+(line.tail or '') for line in body)
        nodes.extend([_node('heading',label,level=2,location=location),_node('preformatted',verse),_node('details','Source details',children=fields)])
        outline.append(dict(location=location,label=label,level=2))
    # Retain front/back records outside the primary reading, including field labels.
    for part in root.iter():
        if _local_name(part.tag) in {'front','back'}:
            value=project_visible_text(' '.join(part.itertext()))
            if value:
                nodes.append(_node('details','About this source',children=[_node('paragraph',value)]))
    return _finalize_structure('tei-reader',nodes,outline,_heading_contexts(nodes,outline))
