"""Bounded nonaccepted L811 repair/P5/independent byte-inverse prototype."""
from pathlib import Path
from hashlib import sha256
import json,sys
from lxml import etree
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from build.tei.eusebius_l811_retained_repair import repair
from ocd_kernel.tei.validate import validate_file

LOG=ROOT/'reports/_logs/eusebius-l811-existing-install-20261004-v1'
NS='{http://www.tei-c.org/ns/1.0}';XML='{http://www.w3.org/XML/1998/namespace}'
def encode(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
def digest(v):return sha256(v).hexdigest()
def prototype():
    if digest((ROOT/'build/tei/eusebius_l811_retained_repair.py').read_bytes())!='7fc9ddf22921f576f778bd3299a50baaa55651ee61564d1ce742ff2b0eecf8d9':raise ValueError('Reviewed producer drift')
    if digest((LOG/'root-source-repair-successor-review-v2.json').read_bytes())!='694115928ff1961065d27a7e57ba598ec615c95127af27d6b4101383d6df8496':raise ValueError('Prototype release receipt differs')
    route=json.loads((ROOT/'plans/2026-09-23-acquisition-manifest-source-to-tei/PTA_L811_L812_TECHNICAL_CLOSEOUT_20260929.json').read_bytes())['routes']['L811'];original=(LOG/'retained-original-package/content.tei.xml').read_bytes()
    destination=LOG/'bounded-prototype-v2'
    if destination.exists():raise FileExistsError('Preserve L811 bounded prototype')
    destination.mkdir();raws=[(ROOT/row['source_path']).read_bytes() for row in route['source_members']];receipts=[json.loads((ROOT/row['source_path']).with_name('acquisition-receipt.json').read_bytes()) for row in route['source_members']]
    actual,ledger=repair(original,raws,receipts);candidate=destination/'candidate.tei.xml';candidate.write_bytes(actual);(destination/'producer-repair-ledger.json').write_bytes(encode(ledger))
    errors=validate_file(candidate)
    (destination/'p5-result.json').write_bytes(encode(dict(status='pass' if not errors else 'fail',errors=errors,candidate_sha256=digest(actual))))
    if errors:raise ValueError('Bounded prototype failed P5: '+str(errors))
    tree=etree.fromstring(actual);notes=tree.findall(NS+'teiHeader/'+NS+'fileDesc/'+NS+'sourceDesc/'+NS+'bibl[@type="retained-source-document-envelope"]')
    if len(notes)!=3:raise ValueError('Exactly three administration carriers required')
    restored=actual;seen_status=[];prefixes=[]
    for position,(bibl,raw,receipt) in enumerate(zip(notes,raws,receipts,strict=True),1):
        if len(bibl)!=1 or bibl[0].tag!=NS+'note' or bibl[0].get('type')!='source-document-envelope-administration':raise ValueError('P5 administration note branch differs')
        fields={p.get('n'):p.text for p in bibl[0]}
        source=etree.fromstring(raw);header=source.find(NS+'teiHeader');file=header.find(NS+'fileDesc');body=source.find(NS+'text/'+NS+'body')
        original_fields=[dict(path=source.getroottree().getpath(n),tag=n.tag,attributes=dict(n.attrib),text=n.text,tail=n.tail) for n in [source,header,file,*file,*list(header)[1:],source.find(NS+'text'),body]]
        if json.loads(fields['source_shell_fields'])!=original_fields:raise ValueError('Actual readable source shell fields differ')
        if fields['literal_document_prefix']!=raw[:raw.index(b'<TEI')].decode('utf-8') or fields['literal_document_suffix']!=raw[raw.rindex(b'</TEI>')+6:].decode('utf-8'):raise ValueError('Actual readable literal source prefix/suffix differs')
        context=json.loads(fields['source_uri_context'])
        if any(context[k]!=receipt[k] for k in ('source_url','final_url','reader_url','pinned_commit')):raise ValueError('Actual source URI context differs')
        seen_status.append(header.find(NS+'revisionDesc').get('status'));prefixes.append(digest(fields['literal_document_prefix'].encode()))
        opening=('<bibl xmlns="http://www.tei-c.org/ns/1.0" type="retained-source-document-envelope" n="Tome '+['I','II','III'][position-1]+'">').encode()
        if restored.count(opening)!=1:raise ValueError('Unique independent inverse carrier boundary differs')
        start=restored.index(opening);end=restored.index(b'</bibl>',start)+len(b'</bibl>');restored=restored[:start]+restored[end:]
    # Independently locate the actual one-byte change, without the producer's
    # Expat byte index, repair ledger, or inverse algorithm.
    if len(restored)!=len(original)+1:raise ValueError('Expected one restored source-space byte only')
    changed=next(i for i,(a,b) in enumerate(zip(restored,original)) if a!=b)
    if restored[changed:changed+1]!=b' ' or restored[:changed]+restored[changed+1:]!=original:raise ValueError('Full independent historical TEI byte inverse differs')
    source=etree.fromstring(raws[0]);wanted=source.find(NS+'text/'+NS+'body');observed=tree.find(NS+'text/'+NS+'body')[0][1]
    for ordinal in [2,40,3,2,26,1,2,1]:wanted=wanted[ordinal-1];observed=observed[ordinal-1]
    if not observed.get('wit').endswith(' ') or observed.get('wit').replace('l811-t1-','')!=wanted.get('wit'):raise ValueError('Actual witness whitespace/source binding differs')
    report=dict(status='nonaccepted-bounded-prototype-pass',candidate_sha256=digest(actual),candidate_bytes=len(actual),original_component_sha256=digest(original),p5_valid=True,full_independent_original_tei_byte_inverse=True,body_delta='One exact source-backed witness attribute trailing-space byte; remaining body bytes unchanged.',independent_one_byte_index=changed,actual_three_source_envelopes_checked=True,source_revision_statuses=seen_status,source_prefix_sha256=prefixes,all_ids_unchanged=True,source_uri_contexts_checked=True,source_uri_ambiguity='Original bare target IDs and bibliographic labels retained literally, not repaired or claimed resolved.',formal_source_oracle='not yet executed',candidate_package='not generated',agent_acceptance='not recorded',canonical_installation='not performed')
    (destination/'prototype-receipt.json').write_bytes(encode(report));return dict(status=report['status'],path=(destination/'prototype-receipt.json').relative_to(ROOT).as_posix(),sha256=digest((destination/'prototype-receipt.json').read_bytes()),candidate_sha256=digest(actual),p5_valid=True,inverse_exact=True)

if __name__=='__main__':print(json.dumps(prototype(),sort_keys=True))
