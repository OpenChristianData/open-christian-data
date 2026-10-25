"""Package and prove one complete Maclaren Psalms work from installed source-volume lineage."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET
from lxml import etree
from build.tei.maclaren_psalms_complete_prepare import ROOT, WORK, MEMBERS, TITLE, convert, canonical
from build.tei.maclaren_psalms_complete_oracle import IMPORTS, closure, check, oracle
from ocd_kernel.reconstruction import SourceManifest, CandidatePackage, reconstruct, validate

SOURCE = Path('sources/commentaries/expositors-bible/maclaren-psalms-complete-20261003-v2')
LOG = Path('reports/_logs/maclaren-psalms-complete-20261003-v1')
DESTINATION = Path('D:/Library/Open Christian Data/candidate-reviews/maclaren-psalms-complete-20261003-v3')
NAMES = ('README.source.md','content.tei.xml','manifest.json','provenance.json','source-accountability.json','unresolved.jsonl')

def pin(path):
    raw = (ROOT/path).read_bytes()
    return dict(path=path.as_posix(), bytes=len(raw), sha256=sha256(raw).hexdigest())

def write(path, value):
    target = ROOT/path
    if target.exists():
        raise FileExistsError('Preserve existing Maclaren Psalms evidence: '+str(target))
    target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(value)

def manifest():
    report_path = Path('reports/_logs/maclaren-existing-install-20261003-v1/parent-installed-generation-readback.json')
    report_bytes = (ROOT/report_path).read_bytes()
    if sha256(report_bytes).hexdigest() != '5609db1b5751ed8c9642b6e77c447a9cd9dead237ca4be739bba2cf24932c177':
        raise ValueError('Installed parent review pin differs')
    report = json.loads(report_bytes)
    authorities = []
    def authority(name,path,role):
        authorities.append(dict(name=name, role=role, **pin(path)))
    rows = []; readme_parts = []
    for member in MEMBERS:
        raw_path = Path('raw/ccel/expositors-bible')/(member.replace('-','_',1)+'.xml')
        raw = (ROOT/raw_path).read_bytes(); primary = ET.fromstring(raw)
        package_path = Path('library/works')/WORK/'integration/maclaren-retained-current-20261003-v1'/member/'inputs/package'
        package = CandidatePackage.load(ROOT/package_path); package.verify_integrity()
        row = next(x for x in report['masters'] if x['member_id'] == member)
        master_path = Path(row['master_path']); acceptance_path = master_path.parent/'acceptance.json'
        if pin(master_path)['sha256'] != row['master_sha256'] or pin(acceptance_path)['sha256'] != row['acceptance_sha256']:
            raise ValueError('Installed volume lineage differs')
        rows.append(dict(member_id=member, raw_sha256=sha256(raw).hexdigest(), raw_bytes=len(raw),
            raw_elements=sum(1 for n in primary.iter()), package_sha256=package.sha256, title=primary.findtext('.//DC.Title')))
        authority(member+'-raw',raw_path,'primary-source')
        for name in NAMES:
            authority(member+'-'+('manifest' if name=='manifest.json' else name),package_path/name,'preexisting-source-volume-lineage')
        authority(member+'-master',master_path,'preexisting-installed-volume')
        authority(member+'-acceptance',acceptance_path,'preexisting-installed-acceptance')
        acq_path = next((ROOT/master_path.parent).glob('acquisitions/*.json')).relative_to(ROOT)
        authority(member+'-acquisition',acq_path,'source-uri-context-authority')
        readme_parts.append(package.member_bytes('README.source.md').decode('utf-8'))
    profile = dict(contract='ocd-maclaren-psalms-complete-profile-v1', complete_works=1, source_volumes=3,
        ordered_members=list(MEMBERS), title=TITLE, volumes=rows)
    policy = dict(contract='ocd-maclaren-psalms-complete-policy-v1', ordered_members=list(MEMBERS),
        work_count=1, acquired_volume_count=3, full_native_source_inverse=True, full_group_envelope=True,
        exact_metadata=True, new_acquisition=False, oracle_imports=list(IMPORTS))
    readme = ('# Maclaren: The Psalms, complete retained electronic work\n\n'
        'One authored work in three already acquired volumes, I-XXXVIII, XXXIX-LXXXIX, and XC-CL. '
        'The inherited author catalog identity remains unchanged. Legacy source-volume masters and acceptances remain lineage. '
        'No sources downloaded. Source headings that group Psalms remain literal; no invented Psalm chapter divisions. '
        'Colossians and Philemon is a separate authored volume and is excluded. Each source volume retains its own title/front matter and indexes exactly once. '
        'Every native text tree is conserved and independently checked against its exact raw XML; source metadata, source URLs and per-reference URI context remain per volume. '
        'CCEL attribution and formatting restrictions are reproduced below for each source. Human acceptance, print collation, rights clearance, CSS/pixel equivalence and publication remain separate.\n\n'
        +'\n\n'.join(readme_parts)).encode('utf-8')
    for name,value in [('profile.json',canonical(profile)),('policy.json',canonical(policy)),('README.source.md',readme)]:
        write(SOURCE/name,value)
    authority('complete-profile',SOURCE/'profile.json','complete-source-feature-profile')
    authority('complete-policy',SOURCE/'policy.json','independent-validation-policy')
    authority('complete-readme',SOURCE/'README.source.md','source-rights-attribution')
    authority('tei-p5-xsd',Path('ocd_kernel/tei/vendor/xsd/tei_all.xsd'),'tei-validation-schema')
    authority('package-schema',Path('ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json'),'candidate-package-schema')
    authority('ccel-permission',Path('sources/commentaries/expositors-bible/ccel-permission.md'),'source-rights-evidence')
    authority('installed-parent-readback',report_path,'preexisting-installation-evidence')
    for ordinal,path in enumerate(IMPORTS+('build/tei/maclaren_psalms_complete_prepare.py','ocd_kernel/tei/writer.py','ocd_kernel/tei/normalization.py','ocd_kernel/tei/projection_profile.py','ocd_kernel/tei/__init__.py')):
        authority('implementation-'+str(ordinal),Path(path),'implementation-dependency')
    record = dict(contract='ocd-source-manifest-v1', source_id='ccel-maclaren-psalms-complete-v1', work_id=WORK,
        ticket_id='existing-maclaren-psalms-complete-work-reconciliation', authorities=authorities,
        converter=dict(id=convert.converter_id,version=convert.converter_version,callable='convert',implementation_path='build/tei/maclaren_psalms_complete_prepare.py',implementation_sha256=pin(Path('build/tei/maclaren_psalms_complete_prepare.py'))['sha256']),
        validator=dict(id=oracle.oracle_id,version=oracle.oracle_version,callable='oracle',implementation_path='build/tei/maclaren_psalms_complete_oracle.py',implementation_sha256=pin(Path('build/tei/maclaren_psalms_complete_oracle.py'))['sha256'],import_closure_sha256=closure()),
        package_schema=dict(path='ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json',sha256=pin(Path('ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json'))['sha256']),
        scope=dict(kind='complete-existing-authored-work',source_volumes=3,complete_works=1,new_acquisition=False),
        source_order=dict(ordered_members=list(MEMBERS),grouping='three complete electronic source-volume envelopes in primary title order'))
    path = SOURCE/'source-manifest.json'; write(path,canonical(record))
    return SourceManifest.load(ROOT/path,repository_root=ROOT)

def prove(source, package):
    baseline = validate(source,package,oracle)
    proof_root = DESTINATION/'proof-v1'
    proof_root.mkdir(exist_ok=False)
    root = etree.fromstring(package.member_bytes('content.tei.xml'))
    ns = '{http://www.tei-c.org/ns/1.0}'; xml = '{http://www.w3.org/XML/1998/namespace}'
    schema = etree.XMLSchema(etree.parse(str(ROOT/'ocd_kernel/tei/vendor/xsd/tei_all.xsd')))
    mutations = []
    for label in ('volume-order','volume-identity','volume-text','volume-tail','note-attachment','uri-base','source-header','extra-group-payload'):
        changed = deepcopy(root); group = changed.find(ns+'text/'+ns+'group')
        if label=='volume-order':
            first = group[0]; group.remove(first); group.insert(1,first)
        elif label=='volume-identity':group[0].set(xml+'id','maclaren-psalms-wrong-volume')
        elif label=='volume-text':next(n for n in group[0].iter(ns+'p') if n.text).text+=' ALTERED'
        elif label=='volume-tail':next(n for n in group[0].iter() if n.tag in {ns+'hi',ns+'ref'} and n.tail).tail+=' ALTERED'
        elif label=='note-attachment':
            note = next(group[1].iter(ns+'note')); note.getparent().remove(note); next(group[2].iter(ns+'p')).append(note)
        elif label=='uri-base':next(n for n in group[0].iter(ns+'ref') if n.get(xml+'base')).set(xml+'base','https://invalid.example/')
        elif label=='source-header':changed.find('.//'+ns+'listBibl/'+ns+'listBibl/'+ns+'head').text+=' ALTERED'
        elif label=='extra-group-payload':etree.SubElement(next(group[0].iter(ns+'p')),ns+'hi').text='Unacquired text'
        schema.assertValid(changed)
        destination = proof_root/('challenge-'+label); destination.mkdir()
        for name in package.member_names:(destination/name).write_bytes(package.member_bytes(name))
        (destination/'content.tei.xml').write_bytes(etree.tostring(changed,encoding='utf-8',xml_declaration=True))
        record=json.loads((destination/'manifest.json').read_bytes());raw=(destination/'content.tei.xml').read_bytes()
        for item in record['members']:
            if item['name']=='content.tei.xml':item.update(bytes=len(raw),sha256=sha256(raw).hexdigest())
        (destination/'manifest.json').write_bytes(canonical(record))
        mutant=CandidatePackage.load(destination)
        try:validate(source,mutant,oracle)
        except ValueError as error:mutations.append(dict(label=label,p5='pass',rejected=True,reason=str(error)))
        else:raise ValueError('Complete-work mutation admitted: '+label)
    replays=[]
    for number in (1,2):
        destination=proof_root/('replay-'+str(number))
        script='''import sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from build.tei.maclaren_psalms_complete_prepare import convert
from ocd_kernel.reconstruction import SourceManifest,reconstruct
source=SourceManifest.load(sys.argv[2],repository_root=sys.argv[1])
print(reconstruct(source,sys.argv[3],convert).sha256)'''
        subprocess.run([sys.executable,'-I','-B','-c',script,str(ROOT),str(source.path),str(destination)],check=True,capture_output=True,text=True)
        replay=CandidatePackage.load(destination)
        if any(replay.member_bytes(name)!=package.member_bytes(name) for name in package.member_names):raise ValueError('Complete-work fresh replay bytes differ')
        replays.append(dict(path=destination.as_posix(),package_sha256=replay.sha256,all_six_members_byte_equal=True))
    try:closure('ocd_kernel.tei.writer')
    except ValueError as error:negative=dict(rejected=True,reason=str(error))
    else:raise ValueError('Independent closure negative admitted')
    receipt=dict(status='pass',complete_works=1,acquired_volumes=3,source_manifest_sha256=source.sha256,
        candidate_package_sha256=package.sha256,oracle_report_sha256=baseline.sha256,
        direct_review=check(source,package),mutations=mutations,replays=replays,closure_negative=negative,
        canonical_installation='not-performed')
    write(LOG/'candidate-completion-receipt.json',canonical(receipt))
    print(json.dumps(dict(status='pass',package_sha256=package.sha256,receipt_sha256=pin(LOG/'candidate-completion-receipt.json')['sha256']),sort_keys=True))

if __name__=='__main__':
    if '--resume-proofs' in sys.argv:
        source=SourceManifest.load(ROOT/SOURCE/'source-manifest.json',repository_root=ROOT)
        package=CandidatePackage.load(DESTINATION/'package')
    else:
        DESTINATION.mkdir(exist_ok=False)
        source=manifest();package=reconstruct(source,DESTINATION/'package',convert)
    prove(source,package)
