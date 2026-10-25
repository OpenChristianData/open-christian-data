"""Prepare the bounded John Wesley acceptance header; never install canonically.

The source proof and its execution environment remain separate from the future
accepted reader closure. This module does not import a source producer/checker.
"""
from pathlib import Path
from hashlib import sha256
from datetime import datetime,timezone
from copy import deepcopy
import argparse,json
from lxml import etree
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.library.identities import validate_record
from ocd_kernel.tei.acceptance import PROMOTED_MASTER_REASON

ROOT=Path(__file__).resolve().parents[2]
LOG=Path('reports/_logs/tyerman-john-wesley-existing-install-20261004-v1')
PROPOSAL=LOG/'identity-proposal-v1'
SOURCE=Path('sources/manifest-acquisitions/tyerman-life-times-john-wesley-complete-20261004-v2')
PACKAGE=Path('D:/Library/Open Christian Data/candidate-reviews/tyerman-john-wesley-complete-20261004-v2/package')
WORK_ID='tyerman-life-times-john-wesley'
FORM=WORK_ID+'--retained-en';EDITION=WORK_ID+'--gutenberg-electronic';ACQUISITION=WORK_ID+'--retained-three-volumes'
WORK=Path('library/works')/WORK_ID
EDITION_PATH=WORK/'forms'/FORM/'editions'/EDITION
ACQUISITION_PATH=EDITION_PATH/'acquisitions'/(ACQUISITION+'.json')
EVIDENCE=WORK/'integration/tyerman-john-wesley-current-20261004-v1'
PINS={
 (LOG/'source-review-packet-v2.json').as_posix():'444b592bc5a8abb2975c8cb2ebdd957652922c93b5b3ff6a0221839cfe5fd32e',
 (LOG/'source-proof-v2.json').as_posix():'9d03550920a7a3ec398e01ffb64e1e33f489707187ad1b2521a78a3fff4dbd96',
 (LOG/'root-final-source-identity-review-v2.json').as_posix():'1f8275851eb5fb28355c5d9e61d863bf6e1d5d012a04f414b505d4b80154252e',
 (SOURCE/'source-manifest.json').as_posix():'b4423071db6f4d039312e6c77f1eea093a9fe8214732c5ebb121602a0eaa9a9a',
 (PROPOSAL/'work.json').as_posix():'3b6960167b1b86357f725ea6dd6013bdc4ef42fda9f7ade7ac6a142453d2a91f',
 (PROPOSAL/'acquisition.json').as_posix():'a201d43d1efa11cfc8368e5dc70dbe771bf980beae4ca555a73f025a6580d9f4',
 (PROPOSAL/'retained-member-set.json').as_posix():'84bcfb4926d70a447cbc4ec31baedeb23052574524d839fa593c5014e54aebad',
 (PROPOSAL/'lineage.json').as_posix():'a19ce792a6efd2521147950211b07f8cf735f8a60e4cc8f38159dfcd4eb87c23',
 (PROPOSAL/'proposal-validation.json').as_posix():'b04acd1a089a02166ab311552b1ff0bf10d8a034792c57397a5337c9db0b24af',
}
N='{http://www.tei-c.org/ns/1.0}'
def enc(value):return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode('utf-8')
def sha(value):return sha256(value).hexdigest()
def read(root,path):return json.loads((root/path).read_bytes())
def fields(tree):return [(n.tag,dict(n.attrib),n.text,n.tail,len(n)) for n in tree.iter()]

def assert_sources(root=ROOT):
    for relative,digest in PINS.items():
        if sha((root/relative).read_bytes())!=digest:raise ValueError('Reviewed Wesley source/identity pin drifted: '+relative)
    packet=read(root,LOG/'source-review-packet-v2.json');proof=read(root,LOG/'source-proof-v2.json')
    if packet['status']!='source-ready-identity-proposed-acceptance-not-started' or proof['status']!='pass' or proof['baseline']['complete_work_count']!=1 or proof['baseline']['source_volume_count']!=3:raise ValueError('Reviewed complete-work proof scope differs')
    for relative,digest in proof['source_authority_files'].items():
        if sha((root/relative).read_bytes())!=digest:raise ValueError('Frozen source authority drifted: '+relative)
    if {p.name for p in PACKAGE.iterdir()}!=set(packet['candidate_package_pins']):raise ValueError('Complete six-member source package differs')
    for name,binding in packet['candidate_package_pins'].items():
        raw=(PACKAGE/name).read_bytes()
        if len(raw)!=binding['bytes'] or sha(raw)!=binding['sha256']:raise ValueError('Reviewed source package drifted: '+name)
    return packet,proof

def metadata(root=ROOT,*,at):
    assert_sources(root)
    if (root/WORK).exists():raise ValueError('Canonical John Wesley title home already exists')
    work=deepcopy(read(root,PROPOSAL/'work.json'));acquisition=read(root,PROPOSAL/'acquisition.json')
    if work['work_id']!=WORK_ID or acquisition['edition_id']!=EDITION or acquisition['acquisition_id']!=ACQUISITION:raise ValueError('Approved John Wesley identity differs')
    work['evidence']+=[(EVIDENCE/'source-review-packet-v2.json').as_posix(),(EVIDENCE/'title-identity-review.json').as_posix()]
    state=dict(schema_version='2.0',work_id=WORK_ID,targets=[
      dict(target_id=ACQUISITION,target_type='acquisition',stage='acquired',updated_at=at,reason='Derived ordered metadata binds three already downloaded retained Gutenberg archives; no new acquisition occurred.',evidence=[ACQUISITION_PATH.as_posix(),acquisition['source_path'],(EVIDENCE/'lineage.json').as_posix()]),
      dict(target_id=EDITION,target_type='edition',stage='accepted',updated_at=at,reason=PROMOTED_MASTER_REASON,evidence=[(EDITION_PATH/'master.tei.xml').as_posix(),(EDITION_PATH/'acceptance.json').as_posix(),(EVIDENCE/'source-review-packet-v2.json').as_posix()])])
    validate_record('work',work,context='Complete John Wesley proposed work');validate_record('acquisition',acquisition,context='Existing ordered Wesley archives');validate_record('state',state,context='Complete John Wesley staged state')
    return work,acquisition,state

def bound_header(root=ROOT,*,at):
    packet,proof=assert_sources(root);original=(PACKAGE/'content.tei.xml').read_bytes();acquisition=read(root,PROPOSAL/'acquisition.json')
    identity=dict(work_id=WORK_ID,textual_form_id=FORM,edition_id=EDITION,acquisition_id=ACQUISITION)
    source={key:acquisition[key] for key in ('source_path','source_sha256','source_bytes','source_scope','source_kind')}
    declared=acquisition['source_scope']+' Original electronic contributors and license notices, all three literal source head/prolog/support contexts and existing media pixels remain source-bound. Source-attested abbreviation expansions are alternative expan readings; abbr remains the retained default. IDs and local references are reversibly namespaced by volume. The original volume packages remain historical component evidence; their separate-work assertions are not adopted. Source proof and acceptance reader runtime are separately bound.'
    revision=dict(id=WORK_ID+'--accepted-retained-20261004-v1',date=at[:10],note='Agent-reviewed complete three-volume retained Wesley biography; source readable text and all three source envelopes conserved exactly. Human review, print collation, rights and publication remain separate.')
    old_tree=etree.fromstring(original);header=old_tree.find(N+'teiHeader');ns={'t':N[1:-1]}
    historical=dict(pointers=header.xpath('.//t:sourceDesc//t:ptr/@target',namespaces=ns),sha256=header.xpath('.//t:idno[@type="sha256"]/text()',namespaces=ns))
    bound=bind_reviewed_header(original,expected_sha256=sha(original),identity=identity,source=source,source_url=acquisition['url'],declared_scope=declared,revision=revision,historical_source_description=historical)
    old=b'Nonaccepted retained electronic reconstruction of the complete three-volume work. Human verification, print collation, rights and publication remain separate.'
    new=b'Agent-accepted faithful complete retained electronic work in three volumes. Human verification: not_recorded; print collation: not_recorded; rights: unresolved; publication: not_ready.'
    if bound.count(old)!=1:raise ValueError('Reviewed publication statement preimage differs')
    bound=bound.replace(old,new,1)
    if bound.split(b'</teiHeader>',1)[1]!=original.split(b'</teiHeader>',1)[1]:raise ValueError('Acceptance header changed complete text bytes')
    tree=etree.fromstring(bound)
    if fields(tree.find(N+'text'))!=fields(old_tree.find(N+'text')):raise ValueError('Acceptance header changed actual group fields')
    declared_ids={n.get('type'):n.text for n in tree.find(N+'teiHeader').iter(N+'idno')}
    expected=dict(identity,source_sha256=source['source_sha256'],source_bytes=str(source['source_bytes']),representation_revision=revision['id'],source_kind='retained-member-set',sha256=source['source_sha256'])
    if declared_ids!=expected or list(declared_ids)!=list(expected):raise ValueError('Ordered recomputed acceptance identity differs')
    source_schema=json.loads((root/SOURCE/'source-manifest.json').read_bytes())
    xsd=next(a['path'] for a in source_schema['authorities'] if a['name']=='tei-validation-schema');schema=etree.XMLSchema(etree.parse(str(root/xsd)))
    if not schema.validate(tree):raise ValueError('Header-bound complete work fails P5: '+str(schema.error_log.last_error))
    delta=dict(status='header-only-derived-candidate-not-installed',source_tei_sha256=sha(original),bound_tei_sha256=sha(bound),ordered_binding_fields=list(expected),complete_text_bytes_unchanged=True,full_group_parsed_fields_unchanged=True,source_header_sha256=sha(etree.tostring(header)),bound_header_sha256=sha(etree.tostring(tree.find(N+'teiHeader'))),publication_statement_preimage=old.decode(),publication_statement_after=new.decode(),identity=identity,source=source,representation_revision=revision,source_proof_sha256=PINS[(LOG/'source-proof-v2.json').as_posix()],source_packet_sha256=PINS[(LOG/'source-review-packet-v2.json').as_posix()],installation='not_performed',human_verification='not_recorded',rights='unresolved',publication='not_ready')
    return bound,delta

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--draft',type=Path,required=True);args=parser.parse_args()
    draft=args.draft.absolute();home=(ROOT/LOG).resolve(strict=True)
    if draft.exists() or draft.parent.resolve(strict=True)!=home or not draft.name.startswith('acceptance-header-draft-'):raise ValueError('Fresh task-local header draft directory required')
    at=datetime.now(timezone.utc).isoformat().replace('+00:00','Z');raw,delta=bound_header(at=at);work,acquisition,state=metadata(at=at)
    draft.mkdir();(draft/'candidate.tei.xml').write_bytes(raw)
    for name,value in [('header-delta.json',delta),('work.json',work),('acquisition.json',acquisition),('state.json',state)]:(draft/name).write_bytes(enc(value))
    print(json.dumps(dict(status='draft-only-not-installed',directory=draft.as_posix(),files={p.name:sha(p.read_bytes()) for p in draft.iterdir()}),sort_keys=True))
