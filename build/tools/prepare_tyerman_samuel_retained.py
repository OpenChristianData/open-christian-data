"""Prepare only the existing L637 successor authorities and execution inventory."""
from pathlib import Path
from hashlib import sha256
from zipfile import ZipFile
from collections import Counter
import argparse, json, sys
import html5lib

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
HOME='sources/manifest-acquisitions/tyerman-samuel-retained-install-20261004-v1'
LOG='reports/_logs/tyerman-samuel-existing-install-20261004-v1'
OLD='sources/manifest-acquisitions/tyerman-life-times-samuel-wesley-1866'
WORK='tyerman-life-times-samuel-wesley-1866';SOURCE='gutenberg-67980'
SCOPE='The Life and Times of the Rev. Samuel Wesley, M.A.'
PRODUCER='build/tei/tyerman_samuel_retained_repair.py'
ORACLE='build/tei/tyerman_samuel_source_oracle.py'

def enc(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
def sha(v):return sha256(v).hexdigest()
def pin(path):
    b=(ROOT/path).read_bytes();return dict(path=path,bytes=len(b),sha256=sha(b))
def write_new(path,raw):
    p=ROOT/path
    if p.exists():raise FileExistsError('Preserve existing evidence: '+str(p))
    p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
def fields(n):return dict(tag=n.tag if isinstance(n.tag,str) else '#comment',attributes=dict(sorted(n.attrib.items())),text=n.text,tail=n.tail,children=[fields(c) for c in n])
def source_nodes(n,path='html'):
    yield path,n
    for i,c in enumerate(n,1):yield from source_nodes(c,path+'/'+str(i)+':'+(c.tag if isinstance(c.tag,str) else '#comment'))

def authority_spec():
    result=[('primary-html','raw/gutenberg/67980/html/pg67980-images.html','primary-source'),('retained-archive','raw/gutenberg/67980/pg67980-h.zip','retained-source-archive'),('acquisition-receipt','raw/gutenberg/67980/acquisition-receipt.json','retained-acquisition-receipt'),('retained-member-inventory','raw/gutenberg/67980/member-inventory.tsv','retained-member-inventory')]
    for filename in ['manifest.json','content.tei.xml','provenance.json','source-accountability.json','README.source.md','unresolved.jsonl']:
        name='original-tei' if filename=='content.tei.xml' else 'original-package-manifest' if filename=='manifest.json' else 'original-'+filename
        result.append((name,LOG+'/retained-original-package/'+filename,'retained-original-package-member'))
    for name in ['validation','mutation-reproduction']:result.append(('original-'+name,LOG+'/retained-original-'+name+'.json','historical-technical-proof'))
    for name in ['source-manifest.json','profile.json','policy.json','README.source.md','REVIEW.md']:result.append(('historical-'+name,OLD+'/'+name,'historical-source-authority'))
    result.extend([('historical-producer','build/tei/tyerman_pg_html.py','historical-producer-lineage'),('historical-oracle','build/tei/tyerman_pg_html_oracle.py','historical-oracle-lineage'),('producer',PRODUCER,'bounded-repair-implementation'),('oracle',ORACLE,'independent-source-oracle-implementation'),('runtime',HOME+'/runtime.json','actual-execution-runtime-closure'),('profile',HOME+'/profile.json','complete-source-feature-profile'),('policy',HOME+'/policy.json','independent-validation-policy'),('readme',HOME+'/README.source.md','source-local-attribution-readme'),('tei-validation-schema','ocd_kernel/tei/vendor/xsd/tei_all.xsd','tei-validation-schema'),('tei-examples-schema','ocd_kernel/tei/vendor/xsd/tei_all_teix.xsd','tei-schema-import'),('tei-xml-schema','ocd_kernel/tei/vendor/xsd/tei_all_xml.xsd','tei-schema-import'),('candidate-package-schema','ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json','candidate-package-schema')])
    return result

def prepare():
    with ZipFile(ROOT/'raw/gutenberg/67980/pg67980-h.zip') as z:
        raw=z.read('pg67980-images.html')
        rows=[dict(path=n.filename,bytes=n.file_size,compressed_bytes=n.compress_size,crc32=f'{n.CRC:08x}',sha256=sha(z.read(n))) for n in z.infolist() if not n.is_dir()]
    source=html5lib.parse(raw,treebuilder='etree',namespaceHTMLElements=False)
    nodes=list(source_nodes(source));body=source.find('body');head=source.find('head')
    attributes=Counter((n.tag,k) for _,n in nodes if isinstance(n.tag,str) for k in n.attrib)
    profile=dict(contract='ocd-l637-whole-html-source-profile-v1',work_id=WORK,source_id=SOURCE,scope=SCOPE,complete_html5_source_tree=fields(source),archive_members=rows,source_element_census=dict(sorted(Counter(n.tag for _,n in nodes if isinstance(n.tag,str)).items())),source_attribute_census=[dict(tag=k[0],attribute=k[1],count=v) for k,v in sorted(attributes.items())],source_direct_body_elements=len(body),source_body_elements=sum(1 for n in body.iter() if isinstance(n.tag,str)),source_head_children=len(head),source_prolog=raw.decode().split('<html',1)[0],source_document_suffix=raw.decode().rsplit('</body>',1)[1],correction_fields=[dict(pointer=p,attributes=dict(n.attrib),text=n.text,tail=n.tail) for p,n in nodes if n.tag=='ins'],language_fields=[dict(pointer=p,attributes=dict(n.attrib)) for p,n in nodes if n.tag=='span' and 'lang' in n.attrib],media_fields=[dict(pointer=p,attributes=dict(n.attrib),member=n.get('src'),payload_sha256=next(r['sha256'] for r in rows if r['path']==n.get('src')),archive_sha256=pin('raw/gutenberg/67980/pg67980-h.zip')['sha256']) for p,n in nodes if n.tag=='img'],located_dispositions=[dict(pointer=p,source_fields=fields(n),disposition='Existing ordered native row/column flattening: wrapper attributes absent; formatting whitespace joined to actual adjacent carrier tails under declared grammar.') for p,n in nodes if n.tag in ('tbody','colgroup')]+[dict(pointer=p,source_fields=fields(n),disposition='Existing native grammar omits only this whitespace-only leading text field; all remaining fields are constrained by the complete source grammar.') for p,n in nodes if n.tag in ('table','ul') and n.text and not n.text.strip()]+[dict(pointer='html/3:#comment',source_fields=fields(source[2]),disposition='Located root administration after body; literal document suffix and comment fields visible in sourceDesc, not footer content.')],source_order=dict(primary_members=['pg67980-images.html'],front='provider header',body='Entire complete biography, including twenty chapters, appendices A-C, name index, 361 footnotes, transcriber notes, and all intervening text.',back='Structured complete provider footer',administration='Root/head/body fields, all 23 head children, literal prolog/document suffix, located root comment.'),original_package_members=[pin(LOG+'/retained-original-package/'+n) for n in ['manifest.json','content.tei.xml','provenance.json','source-accountability.json','README.source.md','unresolved.jsonl']],authority_layout=[dict(name=n,path=p,role=r) for n,p,r in authority_spec()])
    provenance=dict(provider='Project Gutenberg',ebook_id='67980',manifest_row='L637',attribution='L. Tyerman; Project Gutenberg; KD Weeks, Brian Wilson, and the Online Distributed Proofreading Team at https://www.pgdp.net; source images credited to The Internet Archive/American Libraries.',rights='The retained source states public domain in the USA and requires local-law review outside the United States. No human rights clearance or publication authorization is implied.',source_archive_sha256=pin('raw/gutenberg/67980/pg67980-h.zip')['sha256'],complete_work_boundary=SCOPE,modifications='Exact retained original TEI component plus bounded source-backed attribute repairs, self-contained image payloads, structured provider footer, and readable located head/prolog/root administration; source wording is preserved.',composite_producer=dict(original_package_manifest=pin(LOG+'/retained-original-package/manifest.json'),original_tei=pin(LOG+'/retained-original-package/content.tei.xml'),historical_converter=pin('build/tei/tyerman_pg_html.py'),bounded_repair=pin(PRODUCER),recipe='Use retained original content.tei.xml plus exact retained HTML/archive with build.tei.tyerman_samuel_retained_repair._convert through the maintained reconstruct_candidate CLI. The shared historical converter is lineage, not the sole current producer.'))
    policy=dict(contract='ocd-l637-whole-source-bounded-repair-policy-v1',work_id=WORK,source_id=SOURCE,scope=SCOPE,provenance=provenance,repair_scope='63 literal correction title attributes; 52 span language attributes; actual source presentation classes and 25 column styles; provider header language; two exact retained JPEG payloads with archive/member URN context; full structured provider footer; all head/root/prolog/document suffix administration. No source text correction.',image_context='The source meta dcterms.source is retained metadata, not an asserted document base. Each graphic embeds exact JPEG bytes and names the exact retained archive SHA and member via corresp URN. No network xml:base is asserted.',parser_policy='HTML5 CRLF/CR normalization to LF; strict independent lexical corroboration permits exactly five known document-formatting differences. Table sections retain ordered native rows/columns and exact declared whitespace joins, with located wrapper disposition. No visual CSS/print-layout claim.',unresolved=[dict(kind='human-review',message='Technical nonaccepted candidate only; human acceptance, rights and attribution applicability remain open.'),dict(kind='visual-review',message='Print-page facsimile comparison, CSS rendering fidelity, and CVW visual review remain open.'),dict(kind='source-metadata-discrepancy',message='The literal HTML title miscredits John and Charles Wesley as authors; retained primary h1 and provider author identify the Samuel Wesley biography by L. Tyerman. Both literal fields are retained.')])
    readme=('''# Retained source: The Life and Times of the Rev. Samuel Wesley, M.A.\n\nOne complete authored biography by L. Tyerman, published in 1866, from the already retained Project Gutenberg eBook 67980. This successor preserves the exact original six-member v4 package and source authorities as historical lineage. It repairs the existing TEI; it does not acquire another text.\n\nCredits: KD Weeks, Brian Wilson, and the Online Distributed Proofreading Team at https://www.pgdp.net. The retained provider credits source images to The Internet Archive/American Libraries. Attribution to L. Tyerman and Project Gutenberg, the entire structured provider license footer, provider credits, transcriber notices, and all source wording remain represented. The source states public domain in the USA; people outside the United States must check applicable local laws. Technical validation is not rights clearance, human acceptance, or publication authorization.\n\nThe actual primary title and provider creator control the biography identity. The conflicting HTML title that names John and Charles Wesley is preserved as located metadata. All twenty chapters, appendices A-C, name index, 361 footnotes, and transcriber notes remain in source order.\n\nThe 63 literal correction tooltips, 52 span language attributes, actual presentation classes and column styles are preserved. Both graphic payloads are exact retained JPEGs, embedded without a network request. Each corresp URN names its retained archive SHA and member; provider dcterms.source remains separate metadata and supplies no assumed network base. Empty image alt attributes remain explicitly empty.\n\nAll 23 head children, root/head/body fields, literal prolog and document suffix, and the ppgen comment at HTML root child 3 are visible source administration. The comment is not provider footer content. An independent lexical reader corroborates the entire source tree after declared HTML newline normalization and exactly five document-formatting recovery differences. Whitespace-only table/list leading fields are explicitly located and dispositioned. Table-section wrappers are located and accounted for; the inherited native grammar flattens those formatting wrappers while preserving row/column order and exact declared whitespace joins.\n\nThe full repaired actual object is checked against the retained source. The separate byte inverse restores the verified original header/footer baseline and reverses observed carrier attributes; byte inversion alone does not establish repaired footer fidelity. Browser CSS, print-page visual fidelity, and human review remain open. This is a nonaccepted candidate; canonical installation is a separate reviewed action.\n''').encode()
    write_new(HOME+'/profile.json',enc(profile));write_new(HOME+'/policy.json',enc(policy));write_new(HOME+'/README.source.md',readme)
    write_new(HOME+'/runtime.json',enc(dict(contract='ocd-l637-actual-runtime-closure-v1',first_party_files=[],external_runtime_files=[])))
    seal_manifest()

def seal_manifest():
    old_path=ROOT/(HOME+'/source-manifest.json')
    if old_path.exists():
        index=1
        while (ROOT/(LOG+'/source-manifest-before-capture-'+str(index)+'.json')).exists():index+=1
        write_new(LOG+'/source-manifest-before-capture-'+str(index)+'.json',old_path.read_bytes())
    authorities=[dict(name=n,role=r,**pin(p)) for n,p,r in authority_spec()]
    manifest=dict(contract='ocd-source-manifest-v1',work_id=WORK,source_id=SOURCE,scope=SCOPE,manifest_row='L637',source_order=dict(primary_members=['pg67980-images.html'],archive_members=['pg67980-images.html','images/cover.jpg','images/i_004.jpg']),authorities=authorities,converter=dict(id='ocd-l637-retained-component-bounded-repair',version='1',callable='_convert',implementation_path=PRODUCER,implementation_sha256=pin(PRODUCER)['sha256']),validator=dict(id='ocd-l637-whole-source-retained-repair-oracle',version='1',callable='_oracle',implementation_path=ORACLE,implementation_sha256=pin(ORACLE)['sha256'],import_closure_sha256=pin(HOME+'/runtime.json')['sha256']),package_schema={k:v for k,v in pin('ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json').items() if k!='bytes'})
    old_path.write_bytes(enc(manifest))

def inventory():
    from ocd_kernel.lib.path_io import resolve_path
    root=resolve_path(ROOT,strict=True);library=resolve_path(Path('D:/Library/Open Christian Data'),strict=True)
    paths={resolve_path(Path(getattr(n,'__file__')),strict=True) for n in sys.modules.copy().values() if getattr(n,'__file__',None)}
    first=[];external=[]
    for p in sorted(paths,key=str):
        if p.is_relative_to(root):first.append(dict(path=p.relative_to(root).as_posix(),bytes=p.stat().st_size,sha256=sha(p.read_bytes())))
        elif p.is_relative_to(library):first.append(dict(path='reports/'+p.relative_to(library/'reports').as_posix(),bytes=p.stat().st_size,sha256=sha(p.read_bytes())))
        else:external.append(dict(path=p.as_posix(),bytes=p.stat().st_size,sha256=sha(p.read_bytes())))
    executable=resolve_path(Path(sys.executable),strict=True)
    return dict(first_party_files=first,external_runtime_files=external,runtime_executable=dict(path=executable.as_posix(),bytes=executable.stat().st_size,sha256=sha(executable.read_bytes())))

def capture(destination):
    from build.tools import reconstruct_candidate as cli
    from build.tools import prove_tyerman_samuel_retained
    import build.tei
    original_loader=cli._bound_callable
    snapshots=[]
    def recording_loader(*args,**kwargs):
        value=original_loader(*args,**kwargs);module=sys.modules[value.__module__]
        def record(manifest):snapshots.append(inventory());return sorted(getattr(n,'__file__') for n in sys.modules.copy().values() if getattr(n,'__file__',None))
        if kwargs['role']=='converter':module.guard=record
        else:module.runtime_guard=record
        return value
    cli._bound_callable=recording_loader
    summary=cli.run(manifest=HOME+'/source-manifest.json',destination=destination,repository_root=str(ROOT))
    observed=inventory()
    old=(ROOT/(HOME+'/runtime.json')).read_bytes()
    write_new(LOG+'/runtime-before-capture.json',old)
    (ROOT/(HOME+'/runtime.json')).write_bytes(enc(dict(contract='ocd-l637-actual-runtime-closure-v1',**observed)))
    write_new(LOG+'/execution-capture.json',enc(dict(contract='ocd-l637-supported-cli-execution-capture-v1',qualification='Initial inventory recording substitutes only in-memory guard functions; not a final guarded validation receipt. Final supported CLI and independent proof must pass the frozen exact guard.',destination=destination,summary=summary,snapshots=snapshots,final_inventory=observed)))
    seal_manifest()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','capture']);parser.add_argument('--destination');args=parser.parse_args()
    if args.mode=='prepare':prepare()
    else:capture(args.destination)
