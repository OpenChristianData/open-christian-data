"""Exact-work header facts after complete streamed document observation.

Proposed maintained helper only, unexecuted. Returned tree contains the actual
prefix/header only; has_text is established from the complete actual document.
No synthesized text/body is used and no source module is imported.
"""
from pathlib import Path
from xml.parsers import expat
import hashlib
from lxml import etree
from ocd_kernel.library._common import PipelineError

IDENTITY={'work_id':'catholic-encyclopedia-vol01','textual_form_id':'catholic-encyclopedia-vol01-retained-en','edition_id':'catholic-encyclopedia-vol01-retained-electronic','acquisition_id':'catholic-encyclopedia-vol01-acquired-member-set'}
MASTER_SHA='5d9bd4892220a40418c5c04cf9421f6a1e40fc8232da06df2dc5796ad460fa33'
PREFIX_SHA='88f7e31539943c9d46e890fc555acb0ffd104c83fb9244ce77f20203025025b9'
NS='http://www.tei-c.org/ns/1.0'

def parse_bound_header(path,*,identity):
    if dict(identity)!=IDENTITY:raise PipelineError('Catholic streaming facts exact identity differs')
    source=Path(path);prefix=b'';stack=[];ids=set();counts={'header':0,'text':0,'body':0,'source_pages':0,'body_units':0,'gaps':0,'repaired_refs':0};sha=hashlib.sha256()
    parser=expat.ParserCreate(namespace_separator='}')
    def forbid(*args):raise PipelineError('Catholic streaming facts reject DTD/entity declarations')
    parser.StartDoctypeDeclHandler=forbid;parser.EntityDeclHandler=forbid;parser.ExternalEntityRefHandler=forbid
    def start(name,attrs):
        if not name.startswith(NS+'}'):raise PipelineError('Catholic streaming facts unexpected namespace')
        tag=name[len(NS)+1:];parent=stack[-1] if stack else None;stack.append(tag)
        key='http://www.w3.org/XML/1998/namespace}id'
        if key in attrs:
            if attrs[key] in ids:raise PipelineError('Catholic streaming facts duplicate XML ID')
            ids.add(attrs[key])
        if tag=='teiHeader' and parent=='TEI':counts['header']+=1
        if tag=='text' and parent=='TEI':counts['text']+=1
        if tag=='body' and parent=='text':counts['body']+=1
        if tag=='div' and attrs.get('type')=='source-page':counts['source_pages']+=1
        if tag=='div' and parent=='body':counts['body_units']+=1
        if tag=='gap':counts['gaps']+=1
        if tag=='ref' and attrs.get('type')=='source-href-reconciled':counts['repaired_refs']+=1
    parser.StartElementHandler=start;parser.EndElementHandler=lambda name:stack.pop()
    try:
        with source.open('rb') as stream:
            opening=stream.read(65536);end=opening.find(b'</teiHeader>')
            if end<0:raise PipelineError('Catholic bounded actual header missing')
            prefix=opening[:end+len(b'</teiHeader>')]
            sha.update(opening);parser.Parse(opening,False)
            for block in iter(lambda:stream.read(4*1024*1024),b''):sha.update(block);parser.Parse(block,False)
            parser.Parse(b'',True)
    except (OSError,expat.ExpatError) as exc:raise PipelineError('Complete Catholic XML observation failed: '+str(exc)) from exc
    if stack or sha.hexdigest()!=MASTER_SHA or hashlib.sha256(prefix).hexdigest()!=PREFIX_SHA:raise PipelineError('Catholic complete document/header binding differs')
    if counts!={'header':1,'text':1,'body':1,'source_pages':11680,'body_units':11681,'gaps':26,'repaired_refs':7}:raise PipelineError('Catholic complete document/source census differs')
    # Appending only the closing original root creates a finite header view,
    # never a stand-in body. Whole document facts came from complete Expat above.
    try:
        header_root=etree.fromstring(prefix+b'</TEI>',etree.XMLParser(resolve_entities=False,no_network=True,load_dtd=False))
    except etree.XMLSyntaxError as exc:raise PipelineError('Catholic actual finite header view failed') from exc
    return header_root.getroottree(),True
