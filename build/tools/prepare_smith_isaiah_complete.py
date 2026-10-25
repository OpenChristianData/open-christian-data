"""Author explicit append-only Isaiah source identity and nonaccepted package."""
from copy import deepcopy
from pathlib import Path
from hashlib import sha256
import json
from build.tei.smith_isaiah_complete_prepare import convert
from build.tei.smith_isaiah_complete_oracle import ROOT,WORK,KEY,MEMBERS,TITLE,BOUNDARY,SHARED,EXCLUDED,ORACLE_IMPORTS,PRODUCER_IMPORTS,expected_profile,expected_policy,expected_readme,raw_records,closure,canonical
from ocd_kernel.reconstruction import SourceManifest,reconstruct
from ocd_kernel.library.acquisitions import source_member_set_bytes,validate_acquisition
from ocd_kernel.library.identities import validate_record

LOG=Path('reports/_logs/smith-isaiah-complete-20261003-v1')
SOURCE=Path('sources/commentaries/expositors-bible/smith-isaiah-complete-20261003-v3')
DESTINATION=Path('D:/Library/Open Christian Data/candidate-reviews/smith-isaiah-complete-20261003-v3')
FORM=WORK+'--smith-ga-isaiah-complete--retained-en'
EDITION=WORK+'--smith-ga-isaiah-complete--ccel-electronic'
ACQUISITION=WORK+'--smith-ga-isaiah-complete--retained-member-set'
NAMES=('README.source.md','content.tei.xml','manifest.json','provenance.json','source-accountability.json','unresolved.jsonl')

def sha(raw):return sha256(raw).hexdigest()
def pin(path):
    raw=(ROOT/path).read_bytes();return dict(path=path.as_posix(),bytes=len(raw),sha256=sha(raw))
def write(path,raw):
    target=ROOT/path
    if target.exists():raise FileExistsError('Preserve existing Isaiah evidence: '+str(target))
    target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)

class AuthoringBindings:
    """Temporary authoring-only path map; formal oracle uses verified SourceManifest."""
    def __init__(self,authorities):self.paths={a['name']:a['path'] for a in authorities}
    def authority_path(self,name):return ROOT/self.paths[name]

def main():
    authorities=[]
    def authority(name,path,role):authorities.append(dict(name=name,role=role,**pin(path)))
    assessment=LOG/'existing-complete-scope-assessment.json';scope=json.loads((ROOT/assessment).read_bytes())
    if scope['ordered_members']!=list(MEMBERS) or scope['complete_works']!=1 or scope['source_volumes']!=2 or scope['boundary']!=BOUNDARY or scope['shared_material']!=SHARED or scope['excluded']!=EXCLUDED:raise ValueError('Reviewed scope differs')
    for rel,digest in scope['canonical_files_before'].items():
        if sha((ROOT/'library/works'/WORK/rel).read_bytes())!=digest:raise ValueError('Legacy generation changed before append-only proposal')
    authority('scope-assessment',assessment,'complete-authored-work-boundary-evidence')
    authority('ccel-permission',Path('sources/commentaries/expositors-bible/ccel-permission.md'),'source-rights-evidence')
    authority('installed-parent-readback',Path(scope['parent_readback']['path']),'preexisting-installation-evidence')
    authority('source-mapping-ancestor',Path('build/tei/smith_retained_native_oracle.py'),'historical-independent-source-mapping')
    authority('raw-volume-oracle',Path('build/tei/smith_isaiah_source_oracle.py'),'independent-source-oracle')
    authority('independent-oracle',Path('build/tei/smith_isaiah_complete_oracle.py'),'independent-complete-work-oracle')
    authority('producer',Path('build/tei/smith_isaiah_complete_prepare.py'),'composite-producer-recipe')
    legacy=Path('library/works')/WORK
    for name in ('work.json','state.json','SOURCE_CREDIT.md'):
        destination=LOG/'legacy-catalog-before-grouping'/name
        raw=(ROOT/legacy/name).read_bytes()
        if (ROOT/destination).exists():
            if (ROOT/destination).read_bytes()!=raw:raise ValueError('Preserved catalog baseline changed')
        else:write(destination,raw)
        authority('legacy-catalog' if name=='work.json' else 'legacy-'+name,destination,'preserved-catalog-baseline')
    for row in scope['volumes']:
        m=row['member_id'];authority(m+'-raw',Path(row['source']['path']),'primary-source')
        for role in ('acquisition','master','acceptance'):authority(m+'-'+role,Path(row[role]['path']),'preexisting-installed-'+role)
        for name in NAMES:authority(m+'-'+('manifest' if name=='manifest.json' else name),Path(row['package'])/name,'immutable-source-volume-package')
    acquisition=dict(schema_version='2.0',acquisition_id=ACQUISITION,edition_id=EDITION,provider='Christian Classics Ethereal Library',url=scope['volumes'][0]['source_url'],route='born-digital',source_kind='retained-member-set',source_path=(SOURCE/'isaiah.retained-member-set.json').as_posix(),source_scope=BOUNDARY+' '+SHARED+' Original acquired URL context remains per volume; no human acceptance, print collation, rights clearance or publication authorization.',retained_files=[dict(path=r['source']['path'],sha256=r['source']['sha256'],bytes=r['source']['bytes'],media_type='application/xml',scope='Entire source-attested Volume '+('I','II')[i]+': '+r['source_title']+'; literal printed witness '+r['source_print_statement']+'; acquired URI '+r['source_url']+'. Full front/body/back, metadata, directives and source defects retained.') for i,r in enumerate(scope['volumes'])],rights='Unresolved; retained statements and CCEL developer/publisher permission notice remain subject to review.',warnings=['Derived ordered member set of two existing acquisitions; no downloads or new witnesses.','Entry URL is exact original Volume I acquisition URL; original Volume II URL remains distinct per-volume base.','Author catalog is preserved as inherited container, not asserted to be one intellectual work.','Twelve Prophets Volume I is excluded and explicitly partial.'])
    member_bytes=source_member_set_bytes(acquisition);acquisition.update(source_sha256=sha(member_bytes),source_bytes=len(member_bytes));validate_record('acquisition',acquisition,context='append-only complete Isaiah acquisition proposal')
    write(SOURCE/'isaiah.retained-member-set.json',member_bytes);write(LOG/'isaiah-grouped-acquisition-proposal-v3.json',canonical(acquisition))
    authority('member-set',SOURCE/'isaiah.retained-member-set.json','ordered-retained-source-member-set')
    authority('grouped-acquisition-proposal',LOG/'isaiah-grouped-acquisition-proposal-v3.json','schema-bound-derived-acquisition')
    work=json.loads((ROOT/'library/works'/WORK/'work.json').read_bytes());original=deepcopy(work)
    addition=dict(textual_form_id=FORM,language='en',editions=[dict(edition_id=EDITION,title=TITLE,language='en',category='commentary',acquisition_ids=[ACQUISITION])])
    if any(f['textual_form_id']==FORM for f in work['textual_forms']):raise ValueError('Derived form already exists')
    work['textual_forms'].append(addition);work['evidence']+= [(LOG/'existing-complete-scope-assessment.json').as_posix(),(SOURCE/'isaiah.retained-member-set.json').as_posix()]
    validate_record('work',work,context='append-only complete Isaiah work proposal')
    if work['work_id']!=original['work_id'] or work['title']!=original['title'] or work['textual_forms'][:-1]!=original['textual_forms'] or work['evidence'][:-2]!=original['evidence']:raise ValueError('Proposal altered legacy catalog identities')
    write(LOG/'work-plus-isaiah-group-proposal-v3.json',canonical(work))
    authority('work-proposal',LOG/'work-plus-isaiah-group-proposal-v3.json','append-only-derived-identity-proposal')
    bindings=AuthoringBindings(authorities);profile=expected_profile(bindings);_,packages,_=raw_records(bindings)
    write(SOURCE/'profile.json',canonical(profile));write(SOURCE/'policy.json',canonical(expected_policy()));write(SOURCE/'README.source.md',expected_readme(bindings,profile,packages))
    authority('complete-profile',SOURCE/'profile.json','complete-source-feature-profile');authority('complete-policy',SOURCE/'policy.json','independent-validation-policy');authority('complete-readme',SOURCE/'README.source.md','source-rights-attribution')
    authority('tei-p5-xsd',Path('ocd_kernel/tei/vendor/xsd/tei_all.xsd'),'tei-validation-schema');authority('package-schema',Path('ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json'),'candidate-package-schema')
    dependencies=sorted(set(ORACLE_IMPORTS+PRODUCER_IMPORTS))
    for i,path in enumerate(dependencies):authority('implementation-'+str(i),Path(path),'implementation-dependency')
    for path in sorted((ROOT/'ocd_kernel/tei/vendor/xsd').rglob('*.xsd')):
        if path.name!='tei_all.xsd':authority('p5-import-'+str(len(authorities)),path.relative_to(ROOT),'tei-validation-schema-dependency')
    record=dict(contract='ocd-source-manifest-v1',source_id='ccel-smith-isaiah-complete-existing-v1',work_id=WORK,ticket_id='existing-smith-isaiah-complete-work-reconciliation',authorities=authorities,converter=dict(id=convert.converter_id,version=convert.converter_version,callable='convert',implementation_path='build/tei/smith_isaiah_complete_prepare.py',implementation_sha256=pin(Path('build/tei/smith_isaiah_complete_prepare.py'))['sha256']),validator=dict(id='ocd-smith-isaiah-complete-raw-backed-independent-oracle',version='1',callable='oracle',implementation_path='build/tei/smith_isaiah_complete_oracle.py',implementation_sha256=pin(Path('build/tei/smith_isaiah_complete_oracle.py'))['sha256'],import_closure_sha256=closure()),package_schema=dict(path='ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json',sha256=pin(Path('ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json'))['sha256']),scope=dict(kind='complete-existing-authored-work',complete_work_id=KEY,complete_works=1,source_volumes=2,new_acquisition=False,ordered_members=list(MEMBERS)),source_order=dict(ordered_members=list(MEMBERS),grouping='Two complete electronic source-volume envelopes in source-attested Volume I then Volume II order'))
    write(SOURCE/'source-manifest.json',canonical(record));source=SourceManifest.load(ROOT/SOURCE/'source-manifest.json',repository_root=ROOT)
    fixture=ROOT/'.tmp_audit/smith-isaiah-identity-fixture-20261003-v3';fixture.mkdir(exist_ok=False)
    wp=fixture/'library/works'/WORK/'work.json';wp.parent.mkdir(parents=True);wp.write_bytes(canonical(work))
    ap=fixture/'library/works'/WORK/'forms'/FORM/'editions'/EDITION/'acquisitions'/(ACQUISITION+'.json');ap.parent.mkdir(parents=True);ap.write_bytes(canonical(acquisition))
    for r in acquisition['retained_files']:
        p=fixture/r['path'];p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((ROOT/r['path']).read_bytes())
    p=fixture/acquisition['source_path'];p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(member_bytes)
    checked=validate_acquisition(ap,root=fixture)
    if checked!=acquisition:raise ValueError('Fixture schema/acquisition result differs')
    write(LOG/'append-only-identity-proposal-proof-v3.json',canonical(dict(status='pass',canonical_changes=False,legacy_catalog_preserved=True,legacy_forms_and_editions_preserved=True,legacy_acquisitions_preserved=True,new_forms=1,new_editions=1,derived_member_set=True,source_members=2,fixture=fixture.as_posix(),acquisition_sha256=sha(canonical(acquisition)),work_sha256=sha(canonical(work)),member_set_sha256=sha(member_bytes),validate_acquisition='pass',limitations='Final identity route is append-only form/edition under inherited author catalog, not an intellectual-work migration.')))
    DESTINATION.mkdir(exist_ok=False);package=reconstruct(source,DESTINATION/'package',convert)
    from ocd_kernel.reconstruction import CandidatePackage
    initial=CandidatePackage.load('D:/Library/Open Christian Data/candidate-reviews/smith-isaiah-complete-20261003-v1/package')
    if initial.member_bytes('content.tei.xml')!=package.member_bytes('content.tei.xml'):raise ValueError('Metadata/checker renewal changed complete TEI bytes')
    from build.tei.smith_isaiah_complete_oracle import oracle,check
    from ocd_kernel.reconstruction import validate
    baseline=validate(source,package,oracle)
    write(LOG/'initial-baseline-v3.json',canonical(dict(status='pass',source_manifest_sha256=source.sha256,candidate_package_sha256=package.sha256,oracle_report_sha256=baseline.sha256,direct_review=check(source,package),canonical_changes=False,tei_bytes_equal_to_initial_candidate=True)))
    print(json.dumps(dict(status='pass',source_manifest_sha256=source.sha256,package_sha256=package.sha256,package=package.path.as_posix(),code_pins=[pin(Path(p)) for p in ('build/tei/smith_isaiah_source_oracle.py','build/tei/smith_isaiah_complete_prepare.py','build/tei/smith_isaiah_complete_oracle.py','build/tools/prepare_smith_isaiah_complete.py')]),sort_keys=True))
if __name__=='__main__':main()
