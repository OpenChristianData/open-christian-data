"""Reading view of the explicit TOML transcription, retaining every source field."""
from cvw_app.renderer_nodes import _node, _local_name, _finalize_structure, _heading_contexts, project_visible_text


def toml_tei_book(root):
    bodies=[element for element in root.iter() if _local_name(element.tag)=='body']
    if len(bodies)!=1:
        return None
    members=list(bodies[0])
    if not members or any(element.get('type')!='source-member' or element.get('subtype') not in {'metadata','commentary'} for element in members):
        return None
    nodes,outline=[],[]
    for position,member in enumerate(members,1):
        source=next((''.join(element.itertext()) for element in member if _local_name(element.tag)=='head'),'')
        directory=next((project_visible_text(''.join(e.itertext())) for e in member if e.get('type')=='source-directory'),'')
        records=[element for element in member if element.get('type')=='commentary-record'] if member.get('subtype')=='commentary' else [member]
        for number,record in enumerate(records,1):
            lists=[element for element in record if element.get('type')=='toml-object']
            if len(lists)!=1:
                return None
            fields={}
            for item in lists[0]:
                key=item.get('n')
                if not key or key in fields:
                    return None
                fields[key]=''.join(''.join(child.itertext()) for child in item if _local_name(child.tag)!='label')
            if member.get('subtype')=='metadata':
                nodes.append(_node('details',f'Source details: {source}',children=[_node('paragraph',project_visible_text(f'{key.replace("_"," ")}: {value}')) for key,value in fields.items()]))
                continue
            if 'quote' not in fields:
                return None
            title=project_visible_text(fields.get('source_title') or '')
            suffix=project_visible_text(fields.get('append_to_author_name') or '')
            label=title or (project_visible_text(f'{directory} {suffix}') if directory and suffix else f'Quotation {number}')
            location=f'toml-member-{position}-record-{number}'
            nodes.extend([_node('heading',label,level=2,location=location),_node('paragraph',project_visible_text(fields['quote']))])
            outline.append(dict(location=location,label=label,level=2))
            details=[_node('paragraph',project_visible_text(f'{key.replace("_"," ")}: {value}')) for key,value in fields.items() if key not in {'quote','source_title'}]
            if directory:
                details.append(_node('paragraph',f'Source directory: {directory}'))
            details.append(_node('paragraph',project_visible_text(f'Source file: {source}')))
            nodes.append(_node('details','Source details',children=details))
    return _finalize_structure('tei-reader',nodes,outline,_heading_contexts(nodes,outline))
