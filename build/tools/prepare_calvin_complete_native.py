"""Fresh work-local binding of an unchanged complete source mapper and reversible envelope."""
from pathlib import Path
from hashlib import sha256
import json,shutil
from build.tei import calvin_institutes_complete_native as producer,calvin_institutes_complete_native_oracle as checker
from ocd_kernel.library._common import io_path
ROOT=Path(__file__).resolve().parents[2]
WORK_ID='calvins-institutes';FORM_ID=WORK_ID+'-retained-text';EDITION_ID=WORK_ID+'-retained-electronic-witness';ACQUISITION_ID=WORK_ID+'-retained-source'
WORK=Path('library/works')/WORK_ID;EDITION=WORK/'forms'/FORM_ID/'editions'/EDITION_ID;ACQUISITION=EDITION/'acquisitions'/(ACQUISITION_ID+'.json')
BASE=Path('sources/calvins-institutes/current-two-volume-20261001')
NOTICE_BASE=Path('sources/private-pg-allen-calvin')/WORK_ID
DATA_NOTICE=Path('data/prose')/WORK_ID/'README.md'
LOGS=Path('reports/_logs/calvin-institutes-current-reconciliation-20261001-v1')
canonical=producer.canonical
SCOPE='Complete already-retained two physical-volume John Allen Sixth American Edition witness, Project Gutenberg 45001 then 64392. Four logical books, 80 complete chapters, five physical book headings with Book III continuing across the volume boundary, front/title/contents/advertisements/prefaces/dedication/syllabus, 3,506 notes and 3,505 attached note-reference occurrences including the explicitly unreferenced volume-II note 1473, principal-matters and Scripture indexes, transcriber context and retained provider wrappers/licenses. All 69,897 physical source lines and exact blank/spacing payloads accounted without omission, duplication or invented newline. One existing work identity, one teiCorpus with exactly two ordered physical-volume TEI documents; no new treatise/work IDs. Authored text, source editorial apparatus, and Project Gutenberg provider/license evidence remain explicitly distinguished. No human/print/rights/publication completion claim.'
def put(path,payload):
    p=io_path(ROOT/path);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(payload)
def binding(name,path,role):
    p=io_path(ROOT/path);b=p.read_bytes();return dict(name=name,path=Path(path).as_posix(),role=role,bytes=len(b),sha256=sha256(b).hexdigest())
def main():
    original=Path('D:/Library/Open Christian Data/candidate-reviews/calvin-institutes-complete-native-20261001-v1/baseline-package')
    snapshot=LOGS/'retained-source-mapping-package'
    for member in original.iterdir():
        target=io_path(ROOT/snapshot/member.name)
        if target.exists():
            if target.read_bytes()!=member.read_bytes():raise ValueError('retained baseline snapshot changed')
        else:put(snapshot/member.name,member.read_bytes())
    from ocd_kernel.reconstruction.contract import CandidatePackage
    package=CandidatePackage.load(io_path(ROOT/snapshot));package.verify_integrity()
    proof=json.loads(io_path(ROOT/LOGS/'baseline-validation.json').read_bytes())
    if proof['status']!='pass' or proof['attestation']['candidate_sha256']!=package.sha256:raise ValueError('baseline source validation missing')
    proposed=json.loads(io_path(ROOT/LOGS/'acquisition-proposed.json').read_bytes())
    member_set=json.loads((ROOT/BASE/'retained-member-set.json').read_bytes())
    new,inventory=producer.adapt(package.member_bytes('content.tei.xml'))
    checker.inverse_and_compare(new,package.member_bytes('content.tei.xml'),inventory)
    profile=dict(contract='ocd-calvin-complete-native-profile-v1',work_id=WORK_ID,edition_id=EDITION_ID,acquisition_id=ACQUISITION_ID,
        source_scope=proposed['source_scope'],scope=SCOPE,source_sha256=proposed['source_sha256'],retained_members=member_set['members'],
        baseline_package_sha256=package.sha256,baseline_tei_sha256=sha256(package.member_bytes('content.tei.xml')).hexdigest(),
        source_backed_headers=[__import__('lxml.etree',fromlist=['etree']).tostring(checker.expected_header(v),encoding='unicode') for v in (None,1,2)],
        alias_contract='ocd-calvin-reversible-native-envelope-v1',interpretation='none; exact reversible annotations on generated scaffolding, not editorial source changes')
    put(BASE/'profile.json',canonical(profile))
    policy=dict(contract='ocd-calvin-complete-native-policy-v1',source_pair_order=['PG45001 Volume I','PG64392 Volume II'],scope=SCOPE,
        rules=['all old full independent source oracle checks run on explicit inverse; no disabled old shape checks','exact three source-backed fresh headers','exact TEI namespace and no unaccounted leading/tail envelope payload','exact two ordered physical-volume records','all blank payloads retained; whitespace type only for wholly whitespace source blocks','all namespace/attribute values/text/tails/IDs/ancestry conserved; XML attribute serialization order not claimed','exact reversible generated ab type/subtype, c underscore→seg, book part→ana, table dimensions→ana, row role→ana aliases','all four original column slices preserved including leading spaces and first-cell lb','meaningful source/header/envelope/alias negative challenges and exact fresh-process byte replay'],source_interpretation='none')
    put(BASE/'validation-policy.json',canonical(policy))
    notice='# Institutes of the Christian Religion: retained source and data credit\n\nThe complete retained witness combines [Project Gutenberg Volume I, 45001](https://www.gutenberg.org/ebooks/45001) and [Volume II, 64392](https://www.gutenberg.org/ebooks/64392), in that reading order. The source title identifies John Calvin and John Allen’s translation from the original Latin, collated with the author’s last French edition. It names the Sixth American Edition, Revised and Corrected, Philadelphia, Presbyterian Board of Publication. This is the retained John Allen witness.\n\nThe Volume I title page prints 1813; the appended Scripture index credits S. T. Livermore, University of Rochester, and prints 1852. Both literal labels are retained; their relation is unresolved. Volume I provider release/update labels are February 24, 2014 and May 15, 2022. Volume II labels are January 26, 2021 and October 18, 2024; its production credit names Richard Hulse, Heather Clark, David King and the Online Distributed Proofreading Team, and credits Internet Archive images. The retained textual members do not independently establish matching print pixels or exact print collation.\n\n'+SCOPE+'\n\nThe provider states a United States public-domain basis and directs users elsewhere to check local law. Project Gutenberg license and trademark requirements are distinct from underlying-text copyright; worldwide status and publication authorization remain unresolved. Both retained provider license notices follow verbatim, including their source wording.\n\nCarry visible source and data credit to `'+DATA_NOTICE.as_posix()+'`.\n\n'
    for i,member in enumerate(proposed['retained_files'],1):
        source=io_path(ROOT/member['path']).read_bytes().decode('utf-8-sig')
        anchor='*** END OF THE PROJECT GUTENBERG EBOOK'
        offset=source.find(anchor)
        if offset<0:raise ValueError('provider end marker missing')
        notice+='Volume '+str(i)+' retained provider notice\n\n'+source[offset:].replace('\r\n','\n')+'\n'
    payload=notice.encode('utf-8')
    if len(payload)>65536:raise ValueError('visible paired notice exceeds maintained gate')
    put(NOTICE_BASE/'README.source.md',payload);put(DATA_NOTICE,payload)
    authorities=[binding('primary-source',BASE/'retained-member-set.json','primary-source'),binding('profile',BASE/'profile.json','complete-source-feature-profile'),binding('validation-policy',BASE/'validation-policy.json','independent-validation-policy'),binding('source-readme',NOTICE_BASE/'README.source.md','source-attribution'),binding('baseline-source-manifest',BASE/'baseline.source-manifest.json','complete-source-mapping-manifest'),binding('baseline-profile',BASE/'baseline.reconstruction-profile.json','original-complete-source-feature-profile'),binding('baseline-policy',Path('sources/calvins-institutes/calvins-institutes.validation-policy.json'),'original-independent-validation-policy'),binding('baseline-schema',Path('sources/calvins-institutes/calvins-institutes.source-accountability.schema.json'),'original-complete-accountability-schema'),binding('baseline-validation',LOGS/'baseline-validation.json','fresh-full-source-attestation'),binding('proposed-acquisition',LOGS/'acquisition-proposed.json','as-found-source-association'),binding('retained-volume-1',Path('raw/gutenberg/pg45001.txt'),'retained-original-source-member'),binding('retained-volume-2',Path('raw/gutenberg/pg64392.txt'),'retained-original-source-member'),binding('tei-p5-xsd',Path('ocd_kernel/tei/vendor/xsd/tei_all.xsd'),'tei-validation-schema'),binding('candidate-package-schema',Path('ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json'),'candidate-package-schema')]
    for member in sorted(original.iterdir()):authorities.append(binding('baseline-package-manifest' if member.name=='manifest.json' else 'baseline-package-'+member.name,snapshot/member.name,'sealed-complete-source-mapping-member'))
    record=dict(contract='ocd-source-manifest-v1',source_id='calvin-allen-complete-retained-two-volume-native-v1',work_id=WORK_ID,textual_form_id=FORM_ID,edition_id=EDITION_ID,acquisition_id=ACQUISITION_ID,scope=SCOPE,authorities=authorities,
        converter=dict(id=producer.CONVERTER_ID,version='1',callable='_convert',implementation_path='build/tei/calvin_institutes_complete_native.py',implementation_sha256=sha256(Path(producer.__file__).read_bytes()).hexdigest()),
        validator=dict(id=checker.ORACLE_ID,version='1',callable='_oracle',implementation_path='build/tei/calvin_institutes_complete_native_oracle.py',implementation_sha256=sha256(Path(checker.__file__).read_bytes()).hexdigest(),import_closure_sha256=checker.closure_sha(ROOT)),
        package_schema=dict(path='ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json',sha256=sha256((ROOT/'ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json').read_bytes()).hexdigest()))
    put(BASE/'source-manifest.json',canonical(record));print(json.dumps(dict(status='prepared',source_sha256=proposed['source_sha256'],baseline_package_sha256=package.sha256,native_tei_sha256=sha256(new).hexdigest(),notice_bytes=len(payload))))
if __name__=='__main__':main()
