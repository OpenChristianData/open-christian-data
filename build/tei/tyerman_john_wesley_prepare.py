"""One complete Tyerman John Wesley biography from three retained components."""
from pathlib import Path
from copy import deepcopy
from zipfile import ZipFile
from hashlib import sha256
import json
import xml.etree.ElementTree as ET
import html5lib
from lxml import etree
from ocd_kernel.reconstruction import SourceManifest
from build.tei.tyerman_john_wesley_emitter import repair_component,fields,visible_text

ROOT=Path(__file__).resolve().parents[2]
LOG=Path('reports/_logs/tyerman-john-wesley-existing-install-20261004-v1')
SOURCE=Path('sources/manifest-acquisitions/tyerman-life-times-john-wesley-complete-20261004-v2')
WORK='tyerman-life-times-john-wesley'
TITLE='The Life and Times of the Rev. John Wesley, M.A., Founder of the Methodists.'
PAGES=(69582,71130,76882)
N='{http://www.tei-c.org/ns/1.0}'
X='{http://www.w3.org/XML/1998/namespace}'

def enc(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode('utf-8')
def sha(b):return sha256(b).hexdigest()
def sub(p,n,text=None,**attrs):
    c=etree.SubElement(p,N+n,**attrs);c.text=text;return c
def raw_fields(tree):
    return [dict(tag=n.tag if isinstance(n.tag,str) else '!comment',attributes=dict(n.attrib),text=n.text,tail=n.tail,children=len(n)) for n in tree.iter()]

def build():
    recovery=json.loads((ROOT/LOG/'retained-recovery-receipt.json').read_bytes())
    if recovery['status']!='pass' or [r['ebook_id'] for r in recovery['records']]!=list(map(str,PAGES)):raise ValueError('Retained component denominator differs')
    for r in recovery['records']:
        for p in r['files']:
            raw=(ROOT/p['path']).read_bytes()
            if len(raw)!=p['bytes'] or sha(raw)!=p['sha256']:raise ValueError('Retained component bytes drifted')
    root=etree.Element(N+'TEI',nsmap={None:N[1:-1]});root.set(X+'id',WORK+'--candidate');root.set(X+'lang','en')
    fd=sub(sub(root,'teiHeader'),'fileDesc');ts=sub(fd,'titleStmt');sub(ts,'title',TITLE);sub(ts,'author','L. Tyerman')
    sub(ts,'respStmt');ts[-1].append(etree.Element(N+'resp'));ts[-1][0].text='Appendix in Volume III';sub(ts[-1],'name','Abel Stevens')
    pub=sub(fd,'publicationStmt');sub(pub,'p','Nonaccepted retained electronic reconstruction of the complete three-volume work. Human verification, print collation, rights and publication remain separate.')
    desc=sub(fd,'sourceDesc');text=sub(root,'text');group=sub(text,'group');group.set(X+'id',WORK+'--volumes')
    units=[];media=[];readme=['# '+TITLE,'','One complete authored work in three ordered source volumes. The original volume packages and their historical separate-work claims are preserved as component evidence, not adopted as the current work boundary. No new source was acquired.','','Source abbreviation titles are represented as choice/abbr/expan alternatives; the retained abbreviation is the default source reading. Classes, styles, administrative comments and folded table section fields remain literal, located source annotations. Source display metadata does not invent new prose.','','Human verification, rendered comparison, printed-witness collation and applicable rights remain unresolved. Project Gutenberg notices and credited contributors remain visible in every volume.','']
    for volume,pg in enumerate(PAGES,1):
        base=ROOT/LOG/'retained-v4'/str(pg)/'package';old=etree.fromstring((base/'content.tei.xml').read_bytes())
        ap=Path(f'raw/gutenberg/{pg}/pg{pg}-h.zip');ar=(ROOT/ap).read_bytes()
        with ZipFile(ROOT/ap) as archive:
            raw=archive.read(f'pg{pg}-images.html');src=html5lib.parse(raw,treebuilder='etree',namespaceHTMLElements=False);body=src.find('body');head=src.find('head')
            if body is None or head is None:raise ValueError('Complete source envelope missing')
            native,patches,records=repair_component(old,body,archive,volume)
            for name in archive.namelist():
                if name.endswith('/') or name.endswith('.html'):continue
                payload=archive.read(name);media.append(dict(volume=volume,ebook_id=str(pg),archive_member=name,path=f'raw/gutenberg/{pg}/html/{name}',bytes=len(payload),sha256=sha(payload),media_type='image/jpeg'))
        group.append(native)
        b=sub(desc,'bibl',type='retained-source-volume');b.set(X+'id','wesley-source-'+str(volume));sub(b,'title',old.findtext(N+'teiHeader/'+N+'fileDesc/'+N+'titleStmt/'+N+'title'));sub(b,'author','L. Tyerman');sub(b,'pubPlace','New York');sub(b,'publisher','Harper & Brothers, Publishers');sub(b,'date','1872')
        receipt=json.loads((ROOT/f'raw/gutenberg/{pg}/acquisition-receipt.json').read_bytes());sub(b,'ref',receipt['source_url'],target=receipt['source_url'])
        sub(b,'note','Primary title page: IN THREE VOLUMES; VOL. '+('I','II','III')[volume-1]+'. Source Gutenberg electronic release, update, contributor and license statements remain literal in its complete volume envelope.',type='volume-scope')
        # Bind the complete original TEI header and entire source head/prefix,
        # without disguising historical assertions as current acceptance.
        sub(b,'note',etree.tostring(old.find(N+'teiHeader'),encoding='unicode'),type='historical-component-header')
        prefix=raw[:raw.lower().index(b'<html')].decode('utf-8');sub(b,'note',prefix,type='source-document-prefix')
        head_literal=ET.tostring(head,encoding='unicode')
        sub(b,'note',head_literal,type='source-head-literal')
        suffix=raw[raw.lower().rfind(b'</body>')+len(b'</body>'):].decode('utf-8')
        envelope=dict(root_tag=src.tag,root_attributes=dict(src.attrib),root_text=src.text,root_tail=src.tail,root_child_tags=[n.tag if isinstance(n.tag,str) else '!comment' for n in src],head_tail=head.tail,body_text=body.text,body_tail=body.tail,raw_suffix_after_body=suffix,parser_line_endings='HTML5 CRLF and CR normalization to LF; original bytes remain unchanged in the retained archive.')
        sub(b,'note',enc(envelope).decode('utf-8'),type='source-envelope-fields')
        readme.extend(['## Volume '+str(volume)+' — Gutenberg '+str(pg),'','Primary title page: IN THREE VOLUMES; VOL. '+('I','II','III')[volume-1]+'. New York: Harper & Brothers, Publishers, Franklin Square, 1872.','',('Volume III explicitly includes the appendix by Abel Stevens and the index.' if volume==3 else 'The complete source front, book body and provider footer are retained.'),'','Source: '+receipt['source_url'],'','### Original source document prefix','```xml',prefix,'```','','### Literal source head, including styles and support context','```xml',head_literal,'```','','### Original retained source notice', (base/'README.source.md').read_text(encoding='utf-8'),''])
        readme.extend(['### Exact source envelope fields, suffix and parser disposition','```json',enc(envelope).decode('utf-8'),'```',''])
        units.append(dict(volume=volume,ebook_id=str(pg),source_path=ap.as_posix(),source_bytes=len(ar),source_sha256=sha(ar),html_member=f'pg{pg}-images.html',html_sha256=sha(raw),source_url=receipt['source_url'],downloaded_utc=receipt['downloaded_utc'],source_manifest_path=f'sources/manifest-acquisitions/tyerman-life-times-john-wesley-vol-{volume}-1872/source-manifest.json',source_manifest_sha256=sha((ROOT/f'sources/manifest-acquisitions/tyerman-life-times-john-wesley-vol-{volume}-1872/source-manifest.json').read_bytes()),legacy_package_path=(LOG/'retained-v4'/str(pg)/'package').as_posix(),legacy_manifest_sha256=sha((base/'manifest.json').read_bytes()),legacy_tei_sha256=sha((base/'content.tei.xml').read_bytes()),source_root_attributes=dict(src.attrib),source_envelope=envelope,source_head=raw_fields(head),document_prefix=prefix,source_body_records=records,native_patch=patches,native_fields_sha256=sha(enc(fields(native))),original_visible_text_sha256=sha(visible_text(body).encode('utf-8')),original_visible_text_characters=len(visible_text(body))))
    raw_tei=etree.tostring(root,encoding='UTF-8',xml_declaration=True)
    profile=dict(contract='ocd-tyerman-wesley-complete-profile-v1',work_id=WORK,complete_work_count=1,source_volume_count=3,volume_order=list(map(str,PAGES)),primary_boundary='All three primary title pages explicitly say IN THREE VOLUMES; distinct numbered source volumes share the complete biography title and 1872 New York imprint.',units=units,media=media,component_route='Existing three TEI text trees are checked against their unchanged declared mapping and patched in place; original packages remain byte-identical. Only located source-backed field, whitespace, footer hierarchy, ID/ref and media repairs are applied.',field_dispositions={'body_comments':'Exact administrative payload, parent and position retained in source annotations; comment text is not invented as visible prose. All comment tail joins are retained.','table_sections':'tbody/thead/tfoot/colgroup are declared layout folds at their table owner; exact fields and child relations remain in annotations; row/cell roles and all spans are native.','page_labels':'Exact source page subtree fields remain at the native page marker; original label text remains adjacent.','source_head':'Complete head fields, style and prefix are literal human-visible header/source README support context.','source_attributes':'Every attribute remains literal at the source-bound native owner; language, rowspans, abbreviation expansion alternatives and graphics also have native semantic representations.'})
    policy=dict(contract='ocd-tyerman-wesley-complete-policy-v1',work_id=WORK,scope='Complete retained three-volume John Wesley biography; Volume III appendix by Abel Stevens and index included.',provenance={'provider':'Project Gutenberg','modifications':profile['component_route'],'historical_scope_qualification':'The old separate-volume complete-work claims are preserved as dated component evidence and superseded by primary three-volume title evidence.','human_verification':'not_recorded','rights':'unresolved','publication':'not_ready'},unresolved=[{'kind':'human-review','message':'No human textual acceptance, rendered comparison or printed-witness collation is claimed.'},{'kind':'rights','message':'Project Gutenberg notices and contributors are retained; applicable jurisdiction and reuse rights remain unresolved.'}])
    account=dict(contract='ocd-tyerman-wesley-complete-accounting-v1',work_id=WORK,complete_work_count=1,source_volume_count=3,volume_order=list(map(str,PAGES)),source_tei_sha256=sha(raw_tei),profile_sha256=sha(enc(profile)),media=media,historical_recovery_receipt_sha256=sha((ROOT/LOG/'retained-recovery-receipt.json').read_bytes()),source_reading_rule='For a source-attested abbreviation choice, read abbr; expan is an explicitly separate source title alternative.')
    provenance=dict(contract='ocd-tyerman-wesley-composite-provenance-v1',status='nonaccepted',work_id=WORK,source_volumes=[{k:u[k] for k in ('volume','ebook_id','source_path','source_sha256','source_bytes','source_url','downloaded_utc','source_manifest_path','source_manifest_sha256','legacy_package_path','legacy_manifest_sha256','legacy_tei_sha256')} for u in units],producer_recipe_sha256=sha(Path(__file__).read_bytes()),emitter_sha256=sha((ROOT/'build/tei/tyerman_john_wesley_emitter.py').read_bytes()),oracle_sha256=sha((ROOT/'build/tei/tyerman_john_wesley_oracle.py').read_bytes()),ancestor_pins=[dict(path=p,sha256=sha((ROOT/p).read_bytes())) for p in ('build/tei/tyerman_pg_html.py','build/tei/tyerman_pg_html_oracle.py')],human_verification='not_recorded',rights='unresolved',publication='not_ready')
    payload={'content.tei.xml':raw_tei,'source-accountability.json':enc(account),'provenance.json':enc(provenance),'README.source.md':('\n'.join(readme)+'\n').encode('utf-8'),'unresolved.jsonl':b''.join(enc(r) for r in policy['unresolved'])}
    return payload,profile,policy

def _convert(manifest:SourceManifest):
    # Shared with the independent checker only for file/runtime pin enforcement.
    # No source mapping, source traversal or expected content comes from it.
    from build.tei.tyerman_john_wesley_oracle import assert_runtime
    assert_runtime()
    manifest.verify();payload,profile,policy=build()
    if manifest.record['work_id']!=WORK or manifest.record['scope']!=policy['scope']:raise ValueError('Complete work scope differs')
    for name,data in [('profile',enc(profile)),('policy',enc(policy)),('readme',payload['README.source.md'])]:
        if manifest.authority_path(name).read_bytes()!=data:raise ValueError('Complete source authority differs: '+name)
    provenance=json.loads(payload['provenance.json']);provenance.update(source_manifest_sha256=manifest.sha256,converter=dict(manifest.record['converter']),oracle=dict(manifest.record['validator']),code_closure_sha256=sha((ROOT/SOURCE/'code-closure.json').read_bytes()),execution_runtime_sha256=sha((ROOT/SOURCE/'runtime-bindings.json').read_bytes()));payload['provenance.json']=enc(provenance)
    assert_runtime()
    return payload
_convert.converter_id='ocd-tyerman-wesley-retained-three-volume-repair'
_convert.converter_version='1'
_convert.implementation_path=Path(__file__).resolve()
