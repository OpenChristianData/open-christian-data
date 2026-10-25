"""Present current, acquisition-bound SWORD member sets without legacy ZIP routes."""
import hashlib
import json
import re
import struct

from cvw_app.renderer_nodes import RendererError, _node, _nodes_text, _finalize_structure, _heading_contexts


def declared_module_context(work_id, manifest, artifacts):
    families = {
        "naves-topical-bible": {"dict.zdt", "dict.zdx", "dict.dat", "dict.idx"},
        "barnes-nt-notes": {"nt.czs", "nt.czv", "nt.czz"},
        "daily-light": {"daily.dat", "daily.idx"},
    }
    if not manifest.record.get("source_id", "").endswith("-installed-review-copy") or work_id not in families:
        return None
    if {a["path"] for a in artifacts} != families[work_id]:
        raise RendererError("Declared SWORD acquisition members are incomplete")
    members = []
    for artifact in artifacts:
        artifact["name"] = artifact["path"]
        members.append({key: artifact[key] for key in ("name", "root", "path", "bytes", "sha256")})
    context = dict(source_set_sha256=manifest.sha256, members=sorted(members,key=lambda m:m["name"]))
    canonical=(json.dumps(context,sort_keys=True,separators=(',',':'))+'\n').encode()
    return {**context,"sha256":hashlib.sha256(canonical).hexdigest()}


def render_sword_members(media_type, context):
    from cvw_app.review_renderers import _render_sword_zld_members, _decode_barnes_members, _barnes_zcom_carrier_text, _SafeHtmlNodes, _BARNES_ZCOM_MEMBERS

    names = set(context) - {"__selected_name__", "__source_set_sha256__"}
    if names == {"dict.zdt", "dict.zdx", "dict.dat", "dict.idx"}:
        mapped = {key.replace('.', '-', 1): value for key,value in context.items()}
        selected=context['__selected_name__'].decode('ascii').replace('.', '-', 1)
        rendered=_render_sword_zld_members(mapped,selected,context['__source_set_sha256__'].decode('ascii'),include_targets=False)
        nodes,outline=[],[]
        for number,row in enumerate(rendered['nodes'][1:],1):
            location=f"entry-{number}"
            match=re.fullmatch(r'\d+\. (.*?) ⟦entryFree/@n:(.*?)⟧ — (.*)',row['text'],re.S)
            if match is None:
                raise RendererError('SWORD entry projection is malformed')
            label,native_number,text=match.groups()
            nodes.extend([_node('heading',label,level=2,location=location),_node('paragraph',text),
                          _node('details','Source details',children=[_node('paragraph',f'Entry identifier: {native_number}')])])
            outline.append(dict(location=location,label=label,level=2))
    elif names in ({"nt.czs", "nt.czv", "nt.czz"}, {"daily.dat", "daily.idx"}):
        if 'nt.czv' in names:
            for name,(size,digest,_) in _BARNES_ZCOM_MEMBERS.items():
                if len(context[name]) != size or hashlib.sha256(context[name]).hexdigest() != digest:
                    raise RendererError('Barnes source member identity differs from the supported module')
            for name,payload in context.items():
                if name in names and len(payload)>16*1024*1024:
                    raise RendererError('SWORD member exceeds reader limit')
            records=[(f"Source entry {number}",raw) for number,raw in _decode_barnes_members(context) if raw]
        else:
            index,data=context['daily.idx'],context['daily.dat']
            if len(index)%6 or not index or index[:6]!=bytes(6):
                raise RendererError('Daily Light index is truncated or invalid')
            records=[]
            previous=0
            for position in range(6,len(index),6):
                offset,size=struct.unpack_from('<IH',index,position)
                if not size or offset<previous or offset+size>len(data):
                    raise RendererError('Daily Light index range is invalid')
                key,separator,raw=data[offset:offset+size].partition(b'\r\n')
                if not separator:
                    raise RendererError('Daily Light record has no heading')
                records.append((key.decode('utf8'),raw))
                previous=offset+size
        nodes,outline=[],[]
        for number,(label,raw) in enumerate(records,1):
            location=f"entry-{number}"
            nodes.append(_node('heading',label,level=2,location=location))
            outline.append(dict(location=location,label=label,level=2))
            text=_barnes_zcom_carrier_text(raw)
            if text.startswith('[WARNING:'):
                nodes.append(_node('preformatted',text))
            else:
                parser=_SafeHtmlNodes(native_divisions=True)
                parser.feed(text.replace('\x00', ''));parser.close()
                nodes.extend(parser.nodes or [_node('paragraph',text)])
    else:
        raise RendererError('SWORD member set is incomplete or unknown')
    if not nodes:
        raise RendererError('SWORD member set contains no readable entries')
    return _finalize_structure('sanitized-html',nodes,outline,_heading_contexts(nodes,outline))
