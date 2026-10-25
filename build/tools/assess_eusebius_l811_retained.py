"""Read-only whole-object assessment of L811's retained three-tome composition.

No producer/checker ancestor is imported. Actual source and candidate fields are
compared by independent ordinal traversal; source parser behavior is corroborated
with the standard-library XML parser, including comments and processing nodes.
"""
from pathlib import Path
from hashlib import sha256
from collections import Counter
import json,re,sys
import xml.etree.ElementTree as ET
from lxml import etree

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
LOG=ROOT/'reports/_logs/eusebius-l811-existing-install-20261004-v1'
CLOSEOUT=ROOT/'plans/2026-09-23-acquisition-manifest-source-to-tei/PTA_L811_L812_TECHNICAL_CLOSEOUT_20260929.json'
WORK=ROOT/'library/works/eusebius-commentarii-in-psalmos'
NS='{http://www.tei-c.org/ns/1.0}';XML='{http://www.w3.org/XML/1998/namespace}'

def digest(raw):return sha256(raw).hexdigest()
def encode(value):return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
def tag(n):
    if isinstance(n.tag,str):return n.tag
    return 'comment' if n.tag in (ET.Comment,etree.Comment) else 'processing-instruction'
def fields(n):return [tag(n),dict(n.attrib),n.text,n.tail,[fields(c) for c in n]]
def parse(raw):return etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,load_dtd=False,recover=False))

def assess():
    target=LOG/'whole-retained-assessment-v1.json'
    if target.exists():raise FileExistsError('Preserve previous L811 assessment')
    route=json.loads(CLOSEOUT.read_bytes())['routes']['L811'];package=Path(route['candidate']['package_path'])
    package_pins={}
    for name,row in route['candidate']['members'].items():
        raw=(package/name).read_bytes()
        if digest(raw)!=row['sha256'] or len(raw)!=row['bytes']:raise ValueError('Historical package pin differs: '+name)
        package_pins[name]=row
    canonical={p.relative_to(WORK).as_posix():dict(bytes=p.stat().st_size,sha256=digest(p.read_bytes())) for p in WORK.rglob('*') if p.is_file()}
    if len(canonical)!=5 or any('master.tei.xml' in p or 'acceptance.json' in p for p in canonical):raise ValueError('Unexpected L811 canonical scope')
    retained=LOG/'retained-canonical-five'
    if retained.exists():raise FileExistsError('Preserve original L811 identity evidence')
    for relative,row in canonical.items():
        p=retained/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((WORK/relative).read_bytes())
    actual=parse((package/'content.tei.xml').read_bytes());header=actual.find(NS+'teiHeader');out_file=header.find(NS+'fileDesc');volumes=actual.find(NS+'text/'+NS+'body')
    if actual.tag!=NS+'TEI' or [c.tag for c in actual]!=[NS+'teiHeader',NS+'text'] or len(volumes)!=3:raise ValueError('Unexpected old composite envelope')
    cursors={name:0 for name in ('titleStmt','editionStmt','publicationStmt','sourceDesc','encodingDesc','profileDesc','revisionDesc')}
    differences=[];members=[];field_count=0;attributes=0;reference_rewrites=0
    def compare(before,after,path,idmap,scope=False):
        nonlocal field_count,attributes,reference_rewrites
        field_count+=1;expected=dict(before.attrib)
        for key,value in list(expected.items()):
            if key==XML+'id':expected[key]=idmap[value]
            else:
                tokens=value.split();rewritten=['#'+idmap[v[1:]] if v.startswith('#') and v[1:] in idmap else v for v in tokens]
                if rewritten!=tokens:
                    expected[key]=' '.join(rewritten);reference_rewrites+=1
                    exact=re.sub(r'(?<!\S)#([^\s]+)',lambda m:'#'+idmap.get(m.group(1),m.group(1)),value)
                    if exact!=expected[key]:differences.append(dict(path=path,field='attribute-whitespace-normalization',name=key,before=value,after=after.get(key),declared_old_mapping='split whitespace and rejoin changed fragment-reference attribute',repair='preserve literal source attribute whitespace while rewriting only bound ID tokens'))
        if scope and 'n' not in expected:expected['n']=scope
        attributes+=len(expected)
        for key,left,right in [('tag',tag(before),tag(after)),('attributes',expected,dict(after.attrib)),('text',before.text,after.text),('tail',before.tail,after.tail),('children',len(before),len(after))]:
            if left!=right:raise ValueError('Old actual composition mismatch '+path+' '+key)
        for i,(b,a) in enumerate(zip(before,after,strict=True),1):compare(b,a,path+'/'+str(i),idmap)
    for position,row in enumerate(route['source_members'],1):
        raw=(ROOT/row['source_path']).read_bytes()
        if digest(raw)!=row['source_sha256'] or len(raw)!=row['source_bytes']:raise ValueError('Exact raw tome pin differs')
        source=parse(raw);stdlib=ET.fromstring(raw,parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True,insert_pis=True)))
        if fields(source)!=fields(stdlib):raise ValueError('Independent XML parser corroboration failed')
        ids=[n.get(XML+'id') for n in source.iter() if isinstance(n.tag,str) and n.get(XML+'id')]
        if len(ids)!=len(set(ids)):raise ValueError('Source duplicate IDs')
        idmap={v:f'l811-t{position}-'+v for v in ids};label='Tome '+row['tome'];h=source.find(NS+'teiHeader');fd=h.find(NS+'fileDesc');body=source.find(NS+'text/'+NS+'body');volume=volumes[position-1]
        if dict(volume.attrib)!={'type':'volume','n':label,XML+'lang':source.get(XML+'lang')} or len(volume)!=2 or volume[0].tag!=NS+'head' or volume[0].text!=row['source_title']:raise ValueError('Tome boundary/title differs')
        out_body=volume[1]
        if dict(out_body.attrib)!={'type':'source-body'} or out_body.text!=body.text or len(out_body)!=len(body):raise ValueError('Source-body envelope differs')
        for i,(b,a) in enumerate(zip(body,out_body,strict=True),1):compare(b,a,f't{position}/text/body/{i}',idmap)
        for name in cursors:
            parent=fd.find(NS+name) if name in ('titleStmt','editionStmt','publicationStmt','sourceDesc') else h.find(NS+name)
            output=out_file.find(NS+name) if name in ('titleStmt','editionStmt','publicationStmt','sourceDesc') else header.find(NS+name)
            if name=='titleStmt' and cursors[name]==0:cursors[name]=1
            for ordinal,child in enumerate(parent,1):
                if name=='titleStmt' and child.tag==NS+'title':continue
                index=cursors[name];compare(child,output[index],f't{position}/header/{name}/{ordinal}',idmap,scope=label);cursors[name]+=1
            if name=='sourceDesc':
                bibl=output[cursors[name]]
                if dict(bibl.attrib)!={'type':'source-tome-title','n':label} or len(bibl)!=1:raise ValueError('Actual tome title carrier differs')
                compare(fd.find(NS+'titleStmt/'+NS+'title'),bibl[0],f't{position}/header/title',idmap);cursors[name]+=1
        envelope_nodes=[source,h,fd,*fd,*list(h)[1:],source.find(NS+'text'),body]
        envelope=[dict(path=source.getroottree().getpath(n),tag=tag(n),attributes=dict(n.attrib),text=n.text,tail=n.tail) for n in envelope_nodes]
        prefix=raw[:raw.index(b'<TEI')].decode('utf-8');suffix=raw[raw.rindex(b'</TEI>')+6:].decode('utf-8')
        primary=body[1];psalms=[int(n.get('n')[3:]) for n in primary if isinstance(n.tag,str) and re.fullmatch(r'Ps_\d+',n.get('n',''))]
        expected_psalms=list(range(50*(position-1)+1,50*position+1))
        if psalms!=expected_psalms:raise ValueError('Source Psalm coverage boundary differs')
        census=dict(Counter(tag(n).removeprefix(NS) for n in source.iter()))
        receipt=json.loads((ROOT/row['source_path']).with_name('acquisition-receipt.json').read_bytes())
        members.append(dict(position=position,tome=row['tome'],source_path=row['source_path'],source_sha256=digest(raw),source_bytes=len(raw),source_title=row['source_title'],source_author=[''.join(n.itertext()).strip() for n in fd.findall(NS+'titleStmt/'+NS+'author')],root_language=source.get(XML+'lang'),edition_language=primary.get(XML+'lang'),preface_language=body[0].get(XML+'lang'),psalm_numbers=psalms,body_census=dict(Counter(tag(n).removeprefix(NS) for n in body.iter())),whole_document_census=census,source_prefix=prefix,source_suffix=suffix,source_envelope_fields=envelope,old_envelope_disposition='Wrapper field values/attributes and literal xml-model prolog were not carried by the historical composite; source-backed readable administration repair proposed.',actual_body_children_fully_compared=True,actual_header_carriers_fully_compared=True,stdlib_lxml_whole_graph_equal=True,source_url=receipt['source_url'],final_url=receipt['final_url'],source_quality_statements=[''.join(n.itertext()).strip() for n in fd.findall(NS+'editionStmt/'+NS+'p')]))
    for name,index in cursors.items():
        output=out_file.find(NS+name) if name in ('titleStmt','editionStmt','publicationStmt','sourceDesc') else header.find(NS+name)
        if len(output)!=index:raise ValueError('Unexpected extra old header carrier '+name)
    report=dict(status='source-assessed-with-located-repair-gaps',contract='ocd-l811-retained-full-graph-assessment-v1',work_id='eusebius-commentarii-in-psalmos',complete_titled_works=1,source_tomes=3,package_path=package.as_posix(),package_members=package_pins,canonical_before=canonical,actual_source_carrier_nodes_compared=field_count,attributes_compared=attributes,reference_attributes_rewritten=reference_rewrites,members=members,located_attribute_normalizations=differences,findings=['Historical three-tome body and all copied header child carriers agree with each exact source under bounded ID/fragment prefixing and scope labels.','Source revisionDesc status=draft/draft/approved and complete document-shell fields/prolog were omitted; repair these administrative fields without changing valid body.','Root language en is retained editorial context; authored edition language grc and preface deu do not establish an English translation.','Historical oracle copies producer scoping logic and pins a static five-file closure; current independent actual-object/execution proof must supersede those assumptions.'],next='Work-local successor preserving proven body bytes; readable located source administration/URI context and truthful Greek identity; immutable L811 row snapshot and full actual runtime admission. No source acquisition/shared ancestor edits.',rights='CC BY-SA4.0 source statements retained; human rights/publication separate',canonical_installation='not performed')
    target.write_bytes(encode(report));return dict(status=report['status'],report=target.as_posix(),sha256=digest(target.read_bytes()),nodes_compared=field_count,attribute_normalizations=len(differences),source_tomes=3,complete_titled_works=1)

if __name__=='__main__':print(json.dumps(assess(),sort_keys=True))
