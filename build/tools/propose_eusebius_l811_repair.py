"""Prepare bounded L811 metadata/source-binding drafts; no package production."""
from pathlib import Path
from hashlib import sha256
import ast,json,sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from ocd_kernel.library.acquisitions import source_member_set_bytes
from ocd_kernel.library.identities import validate_record

LOG=ROOT/'reports/_logs/eusebius-l811-existing-install-20261004-v1'
def encode(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
def pin(p):return sha256(p.read_bytes()).hexdigest()
def save(name,value):
    p=LOG/name
    if p.exists():raise FileExistsError('Preserve L811 proposal '+name)
    p.write_bytes(encode(value));return dict(path=p.relative_to(ROOT).as_posix(),sha256=pin(p))

def propose():
    report=json.loads((LOG/'whole-retained-assessment-v1.json').read_bytes())
    route=json.loads((ROOT/'plans/2026-09-23-acquisition-manifest-source-to-tei/PTA_L811_L812_TECHNICAL_CLOSEOUT_20260929.json').read_bytes())['routes']['L811']
    work=json.loads((ROOT/'library/works/eusebius-commentarii-in-psalmos/work.json').read_bytes());old_work=json.loads(json.dumps(work))
    acquisition=json.loads((ROOT/route['sidecars']['acquisition']['path']).read_bytes())
    form='pta-greek';edition='pta-ef861ab3-commentarii-psalmos-greek';acq_id='pta-l811-retained-greek-ef861ab3'
    if any(f['textual_form_id']==form for f in work['textual_forms']):raise ValueError('Existing Greek form collision')
    work['textual_forms'].append(dict(textual_form_id=form,language='grc',title='PTA Greek critical text with retained German prefaces',editions=[dict(edition_id=edition,language='grc',title='Commentarii in Psalmos, retained PTA Greek Tomes I-III',acquisition_ids=[acq_id])]))
    acquisition['edition_id']=edition;acquisition['acquisition_id']=acq_id
    acquisition['source_path']='library/works/eusebius-commentarii-in-psalmos/integration/eusebius-l811-retained-install-20261004-v1/source-member-set.json'
    acquisition['source_scope']='Complete retained three-tome digital edition of one Greek authored work, with German prefaces and original annotations/variants. All 150 Psalm divisions are present; the source calls Tomes I-II work in progress. No finished printed critical edition, translation, print collation, rights clearance or publication claim.'
    members=source_member_set_bytes(acquisition);acquisition['source_bytes']=len(members);acquisition['source_sha256']=sha256(members).hexdigest()
    validate_record('work',work,context='L811 Greek proposal');validate_record('acquisition',acquisition,context='L811 retained alias proposal')
    proposal=dict(status='proposal-only',identity=dict(work_id=work['work_id'],textual_form_id=form,edition_id=edition,acquisition_id=acq_id),work=work,acquisition=acquisition,source_member_set=json.loads(members),legacy_work=old_work,legacy_canonical_five=report['canonical_before'],preserved_original_fields='Existing form/edition/acquisition and all five canonical files unchanged until root review; new acquisition is an identity alias over exact previously downloaded witnesses, not a download or new source.',body_language_evidence=[dict(tome=m['tome'],root_language=m['root_language'],edition_language=m['edition_language'],preface_language=m['preface_language']) for m in report['members']],source_quality_qualifications=[dict(tome=m['tome'],source_statements=m['source_quality_statements']) for m in report['members']],source_assessment_sha256=pin(LOG/'whole-retained-assessment-v1.json'))
    identity=save('greek-form-identity-proposal-v1.json',proposal)
    retained=LOG/'retained-original-package'
    if retained.exists():raise FileExistsError('Preserve old L811 six-member package')
    retained.mkdir()
    for name,row in route['candidate']['members'].items():
        data=(Path(route['candidate']['package_path'])/name).read_bytes()
        if sha256(data).hexdigest()!=row['sha256']:raise ValueError('Original L811 package pin differs')
        (retained/name).write_bytes(data)
    old_profile=json.loads((LOG/'retained-authorities/sources/manifest-acquisitions/manifest-acquisition-pta-l811-eusebius-commentarii-psalmos-tomes-i-iii-ef861ab3-v5/complete-source-feature-profile.json').read_bytes())
    scoped=save('scoped-source-version-proposal-v1.json',dict(row='L811',work_id=work['work_id'],pinned_source_commit='ef861ab391ea35c5d85b41dd8d7ba2bf65530b21',original_manifest_row=old_profile['manifest_row_text'],current_worklist_row=next(v for v in (ROOT/'plans/2026-09-23-acquisition-manifest-source-to-tei/WORKLIST.md').read_text(encoding='utf-8').splitlines() if '**L811**' in v),source_members=route['source_members'],old_whole_file_context='Historical full-file manifest/worklist hashes remain preserved in the exact old profile; only the immutable L811 scoped row and primary source version will govern current fidelity.'))
    producer=ROOT/'build/tei/eusebius_l811_retained_repair.py';ast.parse(producer.read_bytes())
    packet=dict(status='source-repair-and-identity-draft-for-root-review',producer=dict(path=producer.relative_to(ROOT).as_posix(),sha256=pin(producer)),assessor=dict(path='build/tools/assess_eusebius_l811_retained.py',sha256=pin(ROOT/'build/tools/assess_eusebius_l811_retained.py')),assessment=dict(path='reports/_logs/eusebius-l811-existing-install-20261004-v1/whole-retained-assessment-v1.json',sha256=pin(LOG/'whole-retained-assessment-v1.json')),identity_proposal=identity,scoped_binding_proposal=scoped,exact_recovery_receipt_sha256=pin(LOG/'local-authority-recovery-v1.json'),canonical_five=report['canonical_before'],original_package_members=route['candidate']['members'],intended_delta='One exact structural-locus witness @wit trailing-space restoration via Expat byte offsets (the literal value occurs twice, so no global replacement); three appended readable source-envelope bibls. Whole original TEI byte inverse; remaining body bytes conserved.',URI_disposition='Source/ref labels remain literal; no fabricated base or HTTP links. Record all three exact acquisition source/final/reader contexts and original source ambiguity. Bare witDetail target IDs and corresp bibliographic labels are not silently corrected.',profile_policy_oracle='Current full source oracle/profile/runtime closure still to be prepared after root mapping/identity review; no package generation or fresh producer/proof run yet.',no_download=True,no_canonical_change=True,no_L812_or_shared_PTA_change=True)
    p=save('source-repair-review-packet-v1.json',packet);return dict(packet=p,producer=packet['producer'],identity=identity,scoped_binding=scoped)

if __name__=='__main__':print(json.dumps(propose(),sort_keys=True))
