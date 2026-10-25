"""Append-only complete-work identity and derived acquisition proposal; no installation."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys
from build.tei.maclaren_psalms_complete_prepare import ROOT, WORK, MEMBERS, TITLE, canonical
from ocd_kernel.library.acquisitions import source_member_set_bytes
from ocd_kernel.library.identities import validate_record, validate_identity_update

SOURCE = Path('sources/commentaries/expositors-bible/maclaren-psalms-complete-20261003-v2')
LOG = Path('reports/_logs/maclaren-psalms-complete-20261003-v1')
FORM = WORK+'--maclaren-psalms-complete--retained-en'
EDITION = WORK+'--maclaren-psalms-complete--ccel-electronic'
ACQUISITION = WORK+'--maclaren-psalms-complete--retained-member-set'
SCOPE = ('Complete retained electronic authored work The Psalms in three source volumes: I (Psalms I-XXXVIII), '
    'II (XXXIX-LXXXIX), III (XC-CL). Each entire original XML source and its front/body/back, notes, printed/generated indexes, '
    'metadata, prolog, source URLs and reference context is included once in primary source-volume order. '
    'Distinct source publication statements remain per volume; no claim of one printed edition. '
    'Source-grouped Psalm headings remain literal. Colossians and Philemon is excluded as a separate complete work. '
    'Legacy volume masters, acceptances and identities remain unchanged as lineage. '
    'Human acceptance, print collation, rights clearance, CSS/pixel equivalence and publication remain separate.')

def write(path, record):
    destination=ROOT/path
    if destination.exists():raise FileExistsError('Preserve existing Maclaren identity proposal')
    destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(canonical(record))

def propose():
    parent=ROOT/'library/works'/WORK
    original=json.loads((parent/'work.json').read_bytes()); work=deepcopy(original)
    originals=[];retained=[]
    for ordinal,member in enumerate(MEMBERS,1):
        form=WORK+'--'+member+'--retained-en';edition=WORK+'--'+member+'--ccel-electronic'
        path=Path('library/works')/WORK/'forms'/form/'editions'/edition/'acquisitions'/(WORK+'--'+member+'--acquired.json')
        raw=(ROOT/path).read_bytes();record=json.loads(raw)
        if len(record['retained_files'])!=1:raise ValueError('Legacy source member denominator differs')
        source=record['retained_files'][0]
        retained.append(dict(source,scope='Complete original Maclaren Psalms source Volume '+str(ordinal)+' including all electronic regions and source metadata.'))
        originals.append(dict(member_id=member,position=ordinal,acquisition_path=path.as_posix(),acquisition_sha256=sha256(raw).hexdigest(),source_url=record['url']))
    acquisition=dict(schema_version='2.0',acquisition_id=ACQUISITION,edition_id=EDITION,provider='CCEL',route='born-digital',
        url=originals[0]['source_url'],source_kind='retained-member-set',source_path=(SOURCE/'psalms.retained-member-set.json').as_posix(),
        source_scope=SCOPE,retained_files=retained,rights='Unresolved; literal source statements and CCEL attribution and formatting restrictions require review.',
        warnings=['Derived manifest of three already acquired XML witnesses; no new source download.',
            'Entry URL is original Volume I acquired URL; all three original member URLs remain bound in boundary evidence.',
            'Author catalog compatibility route; no claim that inherited catalog identity represents one intellectual work.'])
    member_set=source_member_set_bytes(acquisition);acquisition.update(source_bytes=len(member_set),source_sha256=sha256(member_set).hexdigest())
    validate_record('acquisition',acquisition,context='Maclaren complete Psalms proposal')
    member_path=ROOT/acquisition['source_path']
    if member_path.exists():raise FileExistsError('Preserve prior Maclaren member-set authority')
    member_path.write_bytes(member_set)
    boundary_path=LOG/'complete-work-boundary-proposal.json'
    boundary=dict(status='proposed',complete_works=1,acquired_source_volumes=3,title=TITLE,ordered_members=list(MEMBERS),
        source_scope=SCOPE,original_acquisitions=originals,identity=dict(work_id=WORK,textual_form_id=FORM,edition_id=EDITION,acquisition_id=ACQUISITION),
        source_manifest_path=(SOURCE/'source-manifest.json').as_posix(),source_manifest_sha256=sha256((ROOT/SOURCE/'source-manifest.json').read_bytes()).hexdigest(),
        complete_source_receipt_path=(LOG/'candidate-completion-receipt.json').as_posix(),complete_source_receipt_sha256=sha256((ROOT/LOG/'candidate-completion-receipt.json').read_bytes()).hexdigest(),
        legacy_disposition='All existing volume IDs, masters, acceptances and states preserved. Derived complete-work edition added. Catalog migration is separate.',
        canonical_installation='not-performed')
    write(boundary_path,boundary)
    work['textual_forms'].append(dict(textual_form_id=FORM,title=TITLE,language='en',editions=[dict(edition_id=EDITION,title=TITLE,language='en',category='commentary',acquisition_ids=[ACQUISITION])]))
    work['evidence'].append(boundary_path.as_posix())
    validate_record('work',work,context='Maclaren append-only work proposal');validate_identity_update(original,work)
    write(LOG/'work-plus-psalms-proposal.json',work);write(LOG/'psalms-grouped-acquisition-proposal.json',acquisition)
    print(json.dumps(dict(status='schema-valid-proposal',work_sha256=sha256(canonical(work)).hexdigest(),acquisition_sha256=sha256(canonical(acquisition)).hexdigest(),member_set_sha256=acquisition['source_sha256']),sort_keys=True))

if __name__=='__main__':propose()
