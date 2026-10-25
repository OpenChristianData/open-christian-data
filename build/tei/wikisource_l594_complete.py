"""Reconstruct the complete validated 1866 Wikisource Chrysostom witness."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import urljoin

from lxml import etree, html
from ocd_kernel.reconstruction.contract import SourceManifest

T = '{http://www.tei-c.org/ns/1.0}'
X = '{http://www.w3.org/XML/1998/namespace}'
CONVERTER_ID = 'ocd-l594-complete-validated-wikisource'
CONVERTER_VERSION = '1'
IMAGES = {'Liturgy_of_John_Chrysostom_diagram.png': 'liturgy-diagram.png',
          'IC_XC_NI_KA_-_Liturgy_of_John_Chrysostom.png': 'liturgy-seal.png'}


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))+'\n').encode()


def _convert(manifest: SourceManifest):
    profile = json.loads(manifest.authority_path('profile').read_bytes())
    source = json.loads(manifest.authority_path('rendered-text').read_bytes())
    document = html.fromstring(source['parse']['text'])
    containers = document.xpath('.//div[@class="prp-pages-output"]')
    if len(containers) != 1:
        raise ValueError('exact one complete page-transclusion envelope required')
    root = etree.Element(T+'TEI', nsmap={None:T[1:-1]})
    root.set(X+'lang', 'en')
    header = etree.SubElement(root,T+'teiHeader')
    fd = etree.SubElement(header,T+'fileDesc')
    title = etree.SubElement(etree.SubElement(fd,T+'titleStmt'),T+'title')
    title.text = profile['title']
    etree.SubElement(etree.SubElement(fd,T+'publicationStmt'),T+'p').text = 'Source-bound reconstruction of the validated 1866 Wikisource electronic witness; contributor transcription under CC BY-SA 4.0. See SOURCE_CREDIT.md.'
    etree.SubElement(etree.SubElement(fd,T+'sourceDesc'),T+'p').text = profile['scope']
    body = etree.SubElement(etree.SubElement(root,T+'text'),T+'body')
    content = etree.SubElement(body,T+'div',type='complete-validated-transcription')
    ordinal = 0

    def copy(s, parent):
        nonlocal ordinal
        if not isinstance(s.tag,str): return
        classes = set((s.get('class') or '').split())
        if s.tag in {'style','link'} or classes & {'ws-noexport','wst-dhr','__nop'}: return
        if 'pagenum' in classes:
            etree.SubElement(parent,T+'pb',n=s.get('data-page-index'),facs='https://en.wikisource.org/wiki/'+s.get('data-page-name').replace(' ','_'))
            return
        if s.tag in {'tbody','thead','tfoot'}:
            for c in s: copy(c,parent)
            return
        mapping = {'div':'div','p':'p','span':'hi','i':'hi','b':'hi','a':'ref','br':'lb','hr':'milestone','table':'table','tr':'row','td':'cell','figure':'figure','figcaption':'figDesc','img':'graphic'}
        if s.tag not in mapping: raise ValueError('unmapped source element: '+s.tag)
        tag = mapping[s.tag]
        # The figure's provider link is file navigation, not printed text.
        if s.tag=='a' and s.find('img') is not None:
            for c in s: copy(c,parent)
            return
        ordinal += 1
        n = etree.SubElement(parent,T+tag)
        n.set(X+'id',f'l594-node-{ordinal}')
        if tag=='div': n.set('type','source-layout')
        if tag=='hi':
            rend=' '.join(filter(None,[s.tag if s.tag in {'i','b'} else '',s.get('class'),s.get('style')]))
            if rend: n.set('rend',rend)
        elif tag=='ref': n.set('target',urljoin('https://en.wikisource.org',s.get('href','')))
        elif tag=='milestone': n.set('unit','source-rule')
        elif tag=='graphic':
            matches = [name for key,name in IMAGES.items() if key in s.get('src','')]
            if len(matches)!=1: raise ValueError('unknown graphic')
            n.set('url', 'https://upload.wikimedia.org/wikipedia/commons/'+('d/d0/Liturgy_of_John_Chrysostom_diagram.png' if matches[0]=='liturgy-diagram.png' else '1/1a/IC_XC_NI_KA_-_Liturgy_of_John_Chrysostom.png'))
        elif tag=='cell':
            for a,b in [('colspan','cols'),('rowspan','rows')]:
                if s.get(a): n.set(b,s.get(a))
        if s.get('lang'): n.set(X+'lang',s.get('lang'))
        n.text=s.text
        for c in s:
            copy(c,n)
        n.tail=s.tail

    envelope=containers[0]
    content.text=envelope.text
    for child in envelope:
        copy(child,content)
    # HTML permits loose inline runs in a div; P5 requires a block carrier.
    for div in reversed(list(content.iter(T+'div'))):
        children=list(div)
        leading=div.text
        div.text=None
        for child in children: div.remove(child)
        run=None
        if leading and leading.strip():
            run=etree.SubElement(div,T+'ab');run.text=leading
        for child in children:
            tail=child.tail;child.tail=None
            if child.tag in {T+'hi',T+'ref',T+'lb'}:
                if run is None: run=etree.SubElement(div,T+'ab')
                run.append(child);child.tail=tail
            else:
                div.append(child);run=None
                if tail and tail.strip():
                    run=etree.SubElement(div,T+'ab');run.text=tail
                else: child.tail=tail
        if any(child.tag==T+'div' for child in div):
            children=list(div)
            for child in children: div.remove(child)
            block=None
            for child in children:
                if child.tag==T+'div':
                    div.append(child);block=None
                else:
                    if block is None: block=etree.SubElement(div,T+'div',type='source-block-run')
                    block.append(child)
    # Printed running heads are navigational; the printer's final imprint is not.
    imprint=etree.SubElement(body,T+'div',type='printer-imprint')
    etree.SubElement(imprint,T+'p').text=profile['final_imprint']
    raw=etree.tostring(root,encoding='UTF-8',xml_declaration=True)
    account=profile | {'candidate_sha256':hashlib.sha256(raw).hexdigest(),'candidate_bytes':len(raw)}
    return {'content.tei.xml':raw,'source-accountability.json':encoded(account),
            'README.source.md':manifest.authority_path('readme').read_bytes(),
            'provenance.json':manifest.authority_path('provenance').read_bytes(),
            'unresolved.jsonl':b''}


_convert.converter_id=CONVERTER_ID
_convert.converter_version=CONVERTER_VERSION
_convert.implementation_path=Path(__file__).resolve()
