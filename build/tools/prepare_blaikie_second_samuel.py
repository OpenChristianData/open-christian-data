"""Bound and prove exactly one already retained complete Second Samuel work."""
from collections import Counter
from copy import deepcopy
import json,subprocess,sys
from pathlib import Path
from lxml import etree
from build.tei.blaikie_second_samuel_prepare import ROOT,LOG,SOURCE_DIR,WORK_ID,SPECS,MEMBERS,OLD_PACKAGE,REPLAY_LOG,canonical,sha,convert,_convert
from build.tei.blaikie_second_samuel_scope import scope_report,BOUNDARY,reconcile
from build.tei.blaikie_second_samuel_oracle import check,_oracle,import_closure,ORACLE_IMPORTS,PRODUCER_IMPORTS
from ocd_kernel.reconstruction import SourceManifest,CandidatePackage,reconstruct,validate

CANDIDATES=Path('D:/Library/Open Christian Data/candidate-reviews/blaikie-second-samuel-existing-20261003-v4')
MEMBER='blaikie-expositor2sam'
def write(relative,raw):
    target=ROOT/relative
    if target.exists():raise FileExistsError('Preserve Second Samuel authority '+str(relative))
    target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
def authority(name,path,role):
    raw=(ROOT/path).read_bytes();return dict(name=name,path=Path(path).as_posix(),role=role,bytes=len(raw),sha256=sha(raw))
def manifest():
    spec=SPECS[MEMBER];payload=convert(MEMBER);raw=(ROOT/spec['path']).read_bytes();tree=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,load_dtd=False));body=tree.find('ThML.body')
    oracle_closure=import_closure();producer_closure=import_closure('build.tei.blaikie_second_samuel_prepare')
    profile=SOURCE_DIR/(MEMBER+'.profile.json');policy=SOURCE_DIR/(MEMBER+'.policy.json');readme=SOURCE_DIR/(MEMBER+'.README.source.md')
    write(profile,canonical(dict(contract='ocd-blaikie-second-samuel-complete-retained-work-profile-v1',member_id=MEMBER,work_id=WORK_ID,source=spec,source_body_c14n_sha256=sha(etree.tostring(body,method='c14n',with_comments=True)),body_tags=dict(Counter(n.tag for n in body.iter() if isinstance(n.tag,str))),front=list(MEMBERS[MEMBER][1]),back=list(MEMBERS[MEMBER][2]),retained_work_sources=1,complete_works=1,retained_crosswalk_field_count=15,source_boundary=BOUNDARY,excluded_works=['First Samuel','Joshua'],producer_import_closure_sha256=producer_closure,producer_imports=list(PRODUCER_IMPORTS),oracle_imports=list(ORACLE_IMPORTS),genre='commentary',scope='Complete acquired Second Samuel authored work; not entire author catalog or series',graphics='Source contains no images',adaptations='Exact10 administrative comment fields/positions; whitespace-only joins;42 per-reference acquired URL bases; complete native source attributes; readable original source fields and actual source-body inverse')))
    write(policy,canonical(dict(contract='ocd-blaikie-second-samuel-independent-readable-policy-v1',member_id=MEMBER,independence='Declared prior exposure to the reviewed Bennett oracle. Source-specific stdlib raw parser and actual serialized TEI comparisons derive all fields/roles/order/ownership/URI bases; no producer or emitter imported. lxml separately corroborates all raw fields.',required=['whole actual source envelope','complete15-field raw-derived retained crosswalk including XPath selectors ordinal identity and text hashes','complete authored work boundary','exact direct and tail text roles attributes parent order','actual native source-body inverse with all10 comments','whole source header root prefix and permission','P5-valid semantic mutations','two fresh process exact six-member replays'],patterns=['RP-03','RP-04','RP-06','RP-11','RP-13','RP-14','RP-15'],visual='Not performed; no source images')))
    write(readme,payload['README.source.md'])
    acq=Path('library/works')/WORK_ID/'forms'/spec['form']/'editions'/spec['edition']/'acquisitions'/(spec['acquisition']+'.json')
    authorities=[authority('retained-thml',spec['path'],'primary-source'),authority('volume-profile',profile,'complete-source-feature-profile'),authority('volume-policy',policy,'independent-validation-policy'),authority('source-local-attribution-readme',readme,'source-rights-attribution'),authority('primary-acquired-url-context',acq,'primary-source-url-context'),authority('ccel-permission','sources/commentaries/expositors-bible/ccel-permission.md','source-rights-evidence'),authority('original-source-credit','data/commentaries/expositors-bible/README.md','historical-source-credit'),authority('scope-recovery',LOG/'retained-scope-reconciliation.json','qualified-existing-lineage-source-boundary'),authority('raw-preflight',LOG/'raw-preflight.json','whole-source-inventory'),authority('lineage-field-negative-proof',LOG/'retained-lineage-field-mutation-proof.json','complete-retained-crosswalk-selector-ordinal-hash-negatives'),authority('tei-p5-xsd','ocd_kernel/tei/vendor/xsd/tei_all.xsd','tei-validation-schema'),authority('candidate-package-schema','ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json','candidate-package-schema'),authority('frozen-emitter-ancestor','build/tei/ccel_retained_native_emitter.py','reviewed-frozen-ancestor')]
    for ordinal,path in enumerate(sorted(set(ORACLE_IMPORTS+PRODUCER_IMPORTS))):authorities.append(authority('import-'+str(ordinal),path,'observed-first-party-import-dependency'))
    for name in ('README.source.md','content.tei.xml','manifest.json','provenance.json','source-accountability.json','unresolved.jsonl'):authorities.append(authority('qualified-replay-'+name,OLD_PACKAGE/name,'qualified-current-LIB036-converter-only-replay'))
    authorities.extend([authority('replay-receipt',REPLAY_LOG/'qualified-current-lib036-replay-receipt.json','qualified-converter-replay-receipt'),authority('replay-source-manifest','sources/commentaries/expositors-bible/bennett-retained-install-20261003-v1/qualified-lib036-replay.source-manifest.json','converter-only-execution-admission-no-oracle-pass'),authority('historical-profile','sources/commentaries/expositors-bible/lib036.reconstruction-profile.json','historical-source-profile-zero-second-samuel-corrections')])
    record=dict(contract='ocd-source-manifest-v1',source_id='ccel-blaikie-second-samuel-retained-native-'+MEMBER+'-v1',work_id=WORK_ID,ticket_id='LIB036-existing-Blaikie-Second-Samuel-only',authorities=authorities,converter=dict(id=_convert.converter_id,version=_convert.converter_version,callable='_convert',implementation_path='build/tei/blaikie_second_samuel_prepare.py',implementation_sha256=sha((ROOT/'build/tei/blaikie_second_samuel_prepare.py').read_bytes())),validator=dict(id=_oracle.oracle_id,version=_oracle.oracle_version,callable='_oracle',implementation_path='build/tei/blaikie_second_samuel_oracle.py',implementation_sha256=sha((ROOT/'build/tei/blaikie_second_samuel_oracle.py').read_bytes()),import_closure_sha256=oracle_closure),package_schema=dict(path='ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json',sha256=sha((ROOT/'ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json').read_bytes())),scope=dict(kind='one-complete-existing-authored-work',member_id=MEMBER,complete_works=1,retained_sources=1,no_acquisition_or_download=True,excluded_works=['First Samuel','Joshua']),source_order=dict(order='Complete original Second Samuel DOM; title page i, chapters ii through xxxiv, indexes xxxv; all comment and tail attachment'))
    path=SOURCE_DIR/(MEMBER+'.source-manifest.json');write(path,canonical(record));return SourceManifest.load(ROOT/path,repository_root=ROOT)
def challenges(package):
    ns={'t':'http://www.tei-c.org/ns/1.0'};xml='{http://www.w3.org/XML/1998/namespace}';tag='{http://www.tei-c.org/ns/1.0}';raw=package.member_bytes('content.tei.xml');schema=etree.XMLSchema(etree.parse(str(ROOT/'ocd_kernel/tei/vendor/xsd/tei_all.xsd')));results=[];directory=CANDIDATES/'semantic-challenges';directory.mkdir(exist_ok=False)
    def reject(label,tree=None,account=None,other=None):
        dest=directory/label;dest.mkdir();data=etree.tostring(tree,encoding='UTF-8',xml_declaration=True) if tree is not None else raw;schema.assertValid(etree.fromstring(data))
        for name in package.member_names:(dest/name).write_bytes(package.member_bytes(name))
        (dest/'content.tei.xml').write_bytes(data)
        if account is not None:(dest/'source-accountability.json').write_bytes(canonical(account))
        for name,value in (other or {}).items():(dest/name).write_bytes(value)
        metadata=json.loads((dest/'manifest.json').read_bytes())
        for row in metadata['members']:
            payload=(dest/row['name']).read_bytes();row.update(bytes=len(payload),sha256=sha(payload))
        (dest/'manifest.json').write_bytes(canonical(metadata));mutant=CandidatePackage.load(dest)
        try:validate(source,mutant,_oracle)
        except ValueError as error:results.append(dict(challenge=label,p5_valid=True,rejected=True,reason=str(error)))
        else:raise ValueError('Second Samuel oracle admitted '+label)
    cases=[('paragraph-text','./t:text//t:p','text'),('source-tail','./t:text//t:ref[parent::t:p]','tail'),('heading-level','./t:text//t:p[contains(@rend,"source-h")]','rend'),('scripture-target','./t:text//t:ref[@target][not(starts-with(@target,"#"))]','target'),('index-directive','./t:text//t:milestone[@unit="insertIndex"]','n'),('note-label','./t:text//t:note[@n]','n'),('original-source-attribute','./t:text//*[@ana]','ana'),('relative-uri-base','./t:text//t:ref[@xml:base]',xml+'base'),('source-line-role','./t:text//t:l[@rend]','rend'),('source-page-number','./t:text//t:pb[@n]','n'),('source-verse-role','./t:text//t:lg','type')]
    for label,selector,field in cases:
        tree=etree.fromstring(raw);nodes=tree.xpath(selector,namespaces=ns)
        if not nodes:raise ValueError('Bound source challenge feature absent '+label)
        node=next((n for n in nodes if getattr(n,field,None)),nodes[0]) if field in ('text','tail') else nodes[0]
        if field in ('text','tail'):setattr(node,field,(getattr(node,field) or '')+'CHALLENGE')
        else:node.set(field,'urn:challenge' if field=='ana' else 'https://example.invalid/' if field==xml+'base' else (node.get(field) or '')+'CHALLENGE')
        reject(label,tree=tree)
    tree=etree.fromstring(raw);note=tree.xpath('./t:text//t:note',namespaces=ns)[0];target=next(n for n in tree.xpath('./t:text//t:p',namespaces=ns) if n is not note.getparent() and note not in n.iterancestors());note.getparent().remove(note);target.append(note);reject('note-ownership',tree=tree)
    tree=etree.fromstring(raw);body=tree.find(tag+'text/'+tag+'body');first=body[0];body.remove(first);body.insert(1,first);reject('chapter-order',tree=tree)
    tree=etree.fromstring(raw);index=tree.xpath('./t:text//t:div[@type="source-index"]',namespaces=ns)[0];owner=tree.xpath('./t:text/t:back/t:div/t:div',namespaces=ns)[-1];index.getparent().remove(index);owner.append(index);reject('index-ownership',tree=tree)
    account=json.loads(package.member_bytes('source-accountability.json'));next(r for r in account['features'] if r['source_tag']=='#comment')['source_text']='CHALLENGE';reject('administrative-comment',account=account)
    account=json.loads(package.member_bytes('source-accountability.json'));account['source_document_prefix']+='CHALLENGE';reject('literal-source-prefix',account=account)
    tree=etree.fromstring(raw);tree.xpath('./t:teiHeader/t:fileDesc/t:titleStmt/t:title',namespaces=ns)[0].text+='CHALLENGE';reject('primary-title',tree=tree)
    tree=etree.fromstring(raw);tree.xpath('.//t:note[@type="complete-source-head-field"]',namespaces=ns)[0].text+='CHALLENGE';reject('complete-source-header',tree=tree)
    tree=etree.fromstring(raw);stand=etree.SubElement(tree,tag+'standOff');listing=etree.SubElement(stand,tag+'list');etree.SubElement(listing,tag+'item').text='Unacquired outer payload';reject('outer-payload',tree=tree)
    provenance=json.loads(package.member_bytes('provenance.json'));provenance['composite_binding']['primary_acquisition']['url']='https://example.invalid/';reject('composite-acquisition-url',other={'provenance.json':canonical(provenance)})
    reject('qualification',other={'unresolved.jsonl':b'{}\n'});reject('visible-credit',other={'README.source.md':b'# Missing credit\n'})
    return results
def lineage_challenges():
    original=CandidatePackage.load(ROOT/OLD_PACKAGE);directory=CANDIDATES/'qualified-lineage-field-challenges';directory.mkdir()
    schema=etree.XMLSchema(etree.parse(str(ROOT/'ocd_kernel/tei/vendor/xsd/tei_all.xsd')))
    schema.assertValid(etree.fromstring(original.member_bytes('content.tei.xml'),etree.XMLParser(huge_tree=True)))
    baseline=reconcile(MEMBER);results=[]
    for field in ('source_selector','source_direct_text_sha256','source_tail_text_sha256','feature_id'):
        dest=directory/field;dest.mkdir()
        for name in original.member_names:(dest/name).write_bytes(original.member_bytes(name))
        account=json.loads(original.member_bytes('source-accountability.json'));row=next(r for r in account['crosswalk'] if r['member_id']==MEMBER);row[field]+='CHALLENGE'
        (dest/'source-accountability.json').write_bytes(canonical(account));metadata=json.loads(original.member_bytes('manifest.json'))
        for row in metadata['members']:
            payload=(dest/row['name']).read_bytes();row.update(bytes=len(payload),sha256=sha(payload))
        (dest/'manifest.json').write_bytes(canonical(metadata));mutant=CandidatePackage.load(dest)
        if mutant.member_bytes('content.tei.xml')!=original.member_bytes('content.tei.xml'):raise ValueError('Lineage challenge changed P5-valid TEI')
        try:reconcile(MEMBER,package_path=dest)
        except ValueError as error:
            if 'complete15-field raw-derived retained crosswalk differs' not in str(error):raise
            results.append(dict(field=field,rejected=True,p5_valid=True,exact_tei_unchanged=True,reason=str(error),package_sha256=mutant.sha256))
        else:raise ValueError('Retained lineage field mutation admitted '+field)
    proof=dict(status='pass',member_id=MEMBER,baseline=baseline,mutations=results,qualification='Current qualified converter-only replay; no historical dated TEI recovery or old oracle validation claim')
    write(LOG/'retained-lineage-field-mutation-proof.json',canonical(proof));return proof

def contract_challenges(source,package):
    from jsonschema import Draft202012Validator
    directory=CANDIDATES/'source-contract-challenges';directory.mkdir()
    contract_dir=SOURCE_DIR/'contract-challenge-authorities';(ROOT/contract_dir).mkdir()
    p5=etree.XMLSchema(etree.parse(str(ROOT/'ocd_kernel/tei/vendor/xsd/tei_all.xsd')))
    p5.assertValid(etree.fromstring(package.member_bytes('content.tei.xml')))
    schema=Draft202012Validator(json.loads((ROOT/'ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json').read_bytes()))
    baseline=json.loads(source.path.read_bytes());results=[]
    cases=['source-id','legacy-work-id','complete-scope','complete-order','authority-role','entire-profile','entire-policy','converter-id','extra-contract-field','package-source-id','package-source-digest','package-source-path']
    for label in cases:
        dest=directory/label;dest.mkdir();record=deepcopy(baseline);metadata=json.loads(package.member_bytes('manifest.json'));challenged_source=source
        if not label.startswith('package-'):
            if label=='source-id':record['source_id']+='-CHALLENGE'
            elif label=='legacy-work-id':record['work_id']='blaikie-second-book-of-samuel'
            elif label=='complete-scope':record['scope']['complete_works']=2
            elif label=='complete-order':record['source_order']['order']+=' CHALLENGE'
            elif label=='authority-role':next(row for row in record['authorities'] if row['name']=='original-source-credit')['role']='changed-source-credit'
            elif label=='converter-id':record['converter']['id']+='-CHALLENGE'
            elif label=='extra-contract-field':record['additional_complete_work']='CHALLENGE'
            else:
                name='volume-profile' if label=='entire-profile' else 'volume-policy';row=next(row for row in record['authorities'] if row['name']==name)
                document=json.loads(source.authority_path(name).read_bytes())
                if label=='entire-profile':document['scope']+=' CHALLENGE'
                else:document['visual']='CHALLENGE human visual review asserted'
                authority_path=contract_dir/(label+'.json');data=canonical(document);write(authority_path,data)
                row.update(path=authority_path.as_posix(),bytes=len(data),sha256=sha(data))
            manifest_path=contract_dir/(label+'.source-manifest.json');write(manifest_path,canonical(record))
            challenged_source=SourceManifest.load(ROOT/manifest_path,repository_root=ROOT);challenged_source.verify()
            metadata.update(source_id=record['source_id'],source_manifest=dict(path=manifest_path.as_posix(),sha256=challenged_source.sha256),converter=record['converter'])
        elif label=='package-source-id':metadata['source_id']+='-CHALLENGE'
        elif label=='package-source-digest':metadata['source_manifest']['sha256']='0'*64
        elif label=='package-source-path':metadata['source_manifest']['path']='sources/commentaries/expositors-bible/unbound-second-samuel-source-manifest.json'
        for name in package.member_names:(dest/name).write_bytes(package.member_bytes(name))
        (dest/'manifest.json').write_bytes(canonical(metadata));schema.validate(metadata);mutant=CandidatePackage.load(dest)
        if mutant.member_bytes('content.tei.xml')!=package.member_bytes('content.tei.xml'):raise ValueError('Contract challenge changed source/TEI')
        try:_oracle(challenged_source,mutant)
        except ValueError as error:direct_reason=str(error)
        else:raise ValueError('Direct Second Samuel oracle admitted contract challenge '+label)
        try:validate(challenged_source,mutant,_oracle)
        except ValueError as error:seam_reason=str(error)
        else:raise ValueError('Second Samuel validation seam admitted contract challenge '+label)
        results.append(dict(challenge=label,valid_source_manifest=True,candidate_package_schema_valid=True,p5_valid=True,exact_tei_unchanged=True,direct_oracle_rejected=True,rejected=True,direct_reason=direct_reason,seam_reason=seam_reason))
    return results

if __name__=='__main__':
    if CANDIDATES.exists():raise FileExistsError('Fresh Second Samuel package and proof destinations required')
    CANDIDATES.mkdir();lineage_proof=lineage_challenges();source=manifest();package=reconstruct(source,CANDIDATES/'package',_convert);report=validate(source,package,_oracle);direct=check(MEMBER,package.path,native=False);negatives=[]
    for module in ('build.tei.blaikie_second_samuel_oracle','build.tei.blaikie_second_samuel_prepare'):
        try:import_closure(module,extra_import='ocd_kernel.reconstruction.verifier')
        except ValueError as error:negatives.append(dict(module=module,rejected=True,reason=str(error)))
        else:raise ValueError('Second Samuel unexpected import admitted')
    mutations=challenges(package);contract_mutations=contract_challenges(source,package);replays=[]
    for number in (1,2):
        destination=CANDIDATES/('fresh-process-'+str(number));subprocess.run([sys.executable,'-B','-m','build.tei.blaikie_second_samuel_prepare',str(destination),'--source-manifest',str(source.path)],cwd=ROOT,check=True,capture_output=True);replay=CandidatePackage.load(destination)
        if any(replay.member_bytes(n)!=package.member_bytes(n) for n in package.member_names):raise ValueError('Second Samuel fresh package replay differs')
        replays.append(dict(path=destination.as_posix(),fresh_python_process=True,exact_six_member_bytes_equal=True,package_sha256=replay.sha256))
    result=dict(status='pass',retained_lineage_field_proof=lineage_proof,work_id=WORK_ID,complete_works=1,retained_sources=1,excluded_works=['First Samuel','Joshua'],source_manifest_path=source.path.as_posix(),source_manifest_sha256=source.sha256,package_path=package.path.as_posix(),package_sha256=package.sha256,oracle_report_sha256=report.sha256,direct_source_review=direct,mutations=mutations,contract_mutations=contract_mutations,replays=replays,import_negatives=negatives,canonical_installation=False,identity_state_staging='Deferred until First Samuel canonical readback; shared catalog preserved through root')
    write(LOG/'candidate-completion-receipt.json',canonical(result));print(json.dumps(dict(status='pass',package_sha256=package.sha256,mutations=len(mutations),receipt_sha256=sha((ROOT/LOG/'candidate-completion-receipt.json').read_bytes()))))
