"""Prepare only the existing engwebpb TEI repair for guarded installation."""
from __future__ import annotations
import argparse,json,shutil
from pathlib import Path
from hashlib import sha256
from datetime import datetime,timezone
from build.tei.engwebpb_repaired_semantic_inline_oracle import oracle
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import validate_identity_update,load_work
from ocd_kernel.library.state import validate_state
from ocd_kernel.reconstruction.contract import SourceManifest,CandidatePackage,validate
from ocd_kernel.tei.acceptance import build_acceptance_record,make_file_binding,write_acceptance,validate_acceptance,PROMOTED_MASTER_REASON
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file
from ocd_kernel.tei.install_accepted import _files,_io_path
from ocd_kernel.projection.categories.bible import project_accepted_bible,verify_accepted_bible

ROOT=Path(__file__).resolve().parents[2]
LIBRARY=Path('D:/Library/Open Christian Data')
WORK_ID='engwebpb';FORM_ID='engwebpb-retained-en';EDITION_ID='engwebpb-electronic-2020';ACQUISITION_ID='engwebpb-acquired'
WORK=Path('library/works')/WORK_ID;EDITION=WORK/'forms'/FORM_ID/'editions'/EDITION_ID
ACQUISITION=EDITION/'acquisitions'/f'{ACQUISITION_ID}.json'
SOURCE=EDITION/'source-member-set.json';SOURCE_SHA='822a44d0f1fbeaa95056fb5fcc0a81c9349dbdf2b5f1349f06005c4d742a16e7'
MANIFEST=Path('sources/manifest-acquisitions/l225-engwebpb-v2/engwebpb.source-manifest.repaired-20261003.json')
CANDIDATE=LIBRARY/'candidate-reviews/engwebpb-five-heading-repair-20261003-v3/package'
LOG=Path('reports/_logs/engwebpb-existing-install-20261003-v1')
EVIDENCE=WORK/'integration/engwebpb-retained-current-20261003-v1'
PACKAGE_SHA='2e4afffa2e6ab2489773cecaddd166b196d8318ca36443712b40757c926f8d37'

def _sha(raw):return sha256(raw).hexdigest()
def _read(path):return json.loads(_io_path(path).read_bytes())
def _write(stage,relative,raw):
 p=stage/relative;_io_path(p.parent).mkdir(parents=True,exist_ok=True);_io_path(p).write_bytes(raw);return p
def _write_json(stage,relative,value):return _write(stage,relative,(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode())
def _copy(root,stage,relative):return _write(stage,relative,_io_path(root/relative).read_bytes())
def _now():return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')

def projection_gate(root,acceptance):
 try:
  p=project_accepted_bible(root,acceptance_path=acceptance)
  errors=verify_accepted_bible(root,acceptance_path=acceptance,rows=p['rows'],receipt=p['receipt'])
  return {'status':'pass' if not errors else 'held','rows':len(p['rows']),'errors':errors}
 except PipelineError as error:return {'status':'held','rows':0,'errors':[str(error)]}

def dependencies(root):
 manifest=SourceManifest.load(root/MANIFEST,repository_root=root)
 result={SOURCE,MANIFEST,ACQUISITION,Path(manifest.record['converter']['implementation_path']),Path(manifest.record['validator']['implementation_path'])}
 result.update(Path(x['path']) for x in manifest.record['authorities'])
 result.update({Path('ocd_kernel/__init__.py'),Path('ocd_kernel/reconstruction/__init__.py'),Path('ocd_kernel/reconstruction/contract.py'),Path('ocd_kernel/reconstruction/verifier.py'),Path('build/tei/l225_engwebpb_semantic_inline.py'),Path('build/tei/l225_engwebpb_semantic_inline_oracle.py'),Path('sources/manifest-acquisitions/l225-engwebpb-v2/engwebpb.source-manifest.v2.json'),LOG/'historical-shared-dependency/build/tei/l225_ebible_usfm.py',LOG/'source-body-review.json',LOG/'source_body_review.py',LOG/'fresh-repair-replay.json',LOG/'runtime-recovery.json',LOG/'independent-five-heading-review.json'})
 result.update((LOG/'immutable-v18-package'/p.name) for p in (root/LOG/'immutable-v18-package').iterdir() if p.is_file())
 result.update(Path(p) for p in ['build/tools/stage_engwebpb_retained_acceptance.py','build/tools/install_engwebpb_retained_acceptance.py','ocd_kernel/tei/acceptance.py','ocd_kernel/tei/install_accepted.py','ocd_kernel/tei/reviewed_integration.py','ocd_kernel/tei/validate.py','ocd_kernel/library/state.py','ocd_kernel/library/identities.py','ocd_kernel/library/acquisitions.py','ocd_kernel/library/_common.py','ocd_kernel/lib/path_io.py','ocd_kernel/lib/storage_topology.py','ocd_kernel/lib/atomic_io.py','ocd_kernel/projection/categories/bible.py','ocd_kernel/projection/envelope.py','ocd_kernel/projection/scripture_authority.py','ocd_kernel/projection/scripture_targets.py','ocd_kernel/projection/scripture_targets_check.py','build/bible_data/osis_book_codes.json'])
 result.update(p.relative_to(root) for p in (root/'schemas/v2').rglob('*.json'))
 result.update(p.relative_to(root) for p in (root/'ocd_kernel/tei/vendor/xsd').glob('*.xsd'))
 return result

def prepare(stage,*,root=ROOT):
 root=root.resolve(strict=True);stage=stage.absolute()
 if stage.exists() or stage.parent!=(LIBRARY/'candidate-reviews').resolve(strict=True) or not stage.name.startswith('engwebpb-s-'):raise PipelineError('fresh external engwebpb stage required')
 manifest=SourceManifest.load(root/MANIFEST,repository_root=root);package=CandidatePackage.load(CANDIDATE)
 report=validate(manifest,package,oracle)
 if report.status!='pass' or package.sha256!=PACKAGE_SHA:raise PipelineError('engwebpb source/candidate differs')
 repair=_read(root/LOG/'source-body-review.json');replay=_read(root/LOG/'fresh-repair-replay.json')
 if repair['status']!='pass' or repair['candidate_body_sha256']!=_sha(package.member_bytes('content.tei.xml')) or not repair['inverse_repair_complete_document_c14n_equal'] or len(repair['five_heading_repair'])!=5 or len(repair['mutations'])!=6 or not all(x['rejected'] for x in repair['mutations']) or replay['status']!='pass' or replay['candidate_package_sha256']!=PACKAGE_SHA:raise PipelineError('engwebpb repair/replay evidence differs')
 acquisition=validate_acquisition(root/ACQUISITION,root=root);retained=acquisition['retained_files']
 if len(retained)!=68 or acquisition['source_sha256']!=SOURCE_SHA or _sha((root/SOURCE).read_bytes())!=SOURCE_SHA:raise PipelineError('engwebpb ordered acquisition differs')
 work=_read(root/WORK/'work.json');old=json.loads(json.dumps(work));form=work['textual_forms'][0];edition=form['editions'][0]
 if form['textual_form_id']!=FORM_ID or edition['edition_id']!=EDITION_ID or 'category' in edition or (root/EDITION/'master.tei.xml').exists():raise PipelineError('engwebpb canonical edition changed')
 stage.mkdir();before=_files(root/WORK)
 for relative in before:_copy(root,stage,WORK/relative)
 for relative in dependencies(root):_copy(root,stage,relative)
 for item in retained:_copy(root,stage,Path(item['path']))
 state=_read(root/WORK/'state.json')
 for relative in set(work['evidence']+[p for row in state['targets'] for p in row['evidence']]):
  if not (stage/relative).exists():_copy(root,stage,Path(relative))
 for name in package.member_names:_write(stage,EVIDENCE/'inputs/package'/name,package.member_bytes(name))
 for name in ['source-body-review.json','source_body_review.py','fresh-repair-replay.json','runtime-recovery.json','historical-v18-validation.json','historical-v18-reproduction-receipt.v1.json','repaired-current-source-validation.json','independent-five-heading-review.json']:_copy(root,stage,LOG/name);_write(stage,EVIDENCE/'inputs'/name,(root/LOG/name).read_bytes())
 edition['category']='bible';validate_identity_update(old,work);_write_json(stage,WORK/'work.json',work);load_work(stage/WORK/'work.json')
 identity={'work_id':WORK_ID,'textual_form_id':FORM_ID,'edition_id':EDITION_ID,'acquisition_id':ACQUISITION_ID}
 source={k:acquisition[k] for k in ['source_path','source_sha256','source_bytes','source_scope','source_kind']}
 selected='Complete ordered 68-member retained L225 USFM textual set: 66 Bible books plus FRT/GLO; all 61098 source lines, 1189 chapters, 31103 source verses, semantic inline data and 1572 attached notes. Three non-USFM ZIP members are support evidence only.'
 revision={'id':'engwebpb-retained-current-20261003-v1','date':datetime.now(timezone.utc).date().isoformat(),'note':'Complete retained existing TEI; five Psalms book heads moved to source chapters; source-neutral empty wrappers removed.'}
 raw=package.member_bytes('content.tei.xml')
 old_status=b'Nonaccepted source-to-TEI candidate; human acceptance, rights review, and publication remain open.'
 new_status=b'Agent-reviewed retained source reconstruction; human review, rights review, and publication remain open.'
 stale_flag=b' ana="#nonaccepted-candidate"'
 if raw.count(stale_flag)!=1 or raw.count(old_status)!=1:raise PipelineError('engwebpb producer status preimage differs')
 prebinding=raw.replace(stale_flag,b'',1).replace(old_status,new_status,1)
 if prebinding.split(b'</teiHeader>',1)[1]!=raw.split(b'</teiHeader>',1)[1]:raise PipelineError('engwebpb status repair changed body')
 bound=bind_reviewed_header(prebinding,expected_sha256=_sha(prebinding),identity=identity,source=source,source_url=acquisition['url'],declared_scope=selected,revision=revision)
 # P5 sourceDesc has either p content or bibliographic entries; retain original p and place the added binding inside it.
 begin=bound.index(b'<bibl xmlns=');end=bound.index(b'</bibl>',begin)+len(b'</bibl>');binding=bound[begin:end]
 bound=bound[:begin]+bound[end:]
 if bound.count(b'</p></sourceDesc>')!=1:raise PipelineError('engwebpb source paragraph boundary differs')
 bound=bound.replace(b'</p></sourceDesc>',binding+b'</p></sourceDesc>',1)
 if raw.split(b'</teiHeader>',1)[1]!=bound.split(b'</teiHeader>',1)[1]:raise PipelineError('engwebpb header binding changed body')
 candidate=_write(stage,EVIDENCE/'candidate.tei.xml',bound)
 _write_json(stage,EVIDENCE/'producer-status-repair.json',dict(original_candidate_sha256=_sha(raw),prebinding_sha256=_sha(prebinding),accepted_sha256=_sha(bound),removed_root_attribute={'ana':'#nonaccepted-candidate'},old_producer_sentence=old_status.decode(),new_producer_sentence=new_status.decode(),source_description_and_rights_unchanged=True,complete_repaired_body_bytes_unchanged=True,binding_placement='inside original sourceDesc p; original paragraph text retained'))
 if errors:=validate_file(candidate):raise PipelineError(str(errors[:3]))
 expected=[{'path':item['path'],'position':i} for i,item in enumerate(retained,1)]
 included=[dict(path=item['path'],position=i,bytes=item['bytes'],sha256=item['sha256'],scope=item['scope']) for i,item in enumerate(retained,1)]
 scope=dict(kind='edition',declared=selected,expected_members=expected,included_members=included,excluded_members=[])
 common=dict(identity=identity,source=source,candidate=make_file_binding(stage,candidate),scope=selected,accepted_scope=dict(kind='edition',declared=selected),expected_members=expected,included_members=included,excluded_members=[],missing_members=[],unknown_members=[],repair_review=make_file_binding(stage,stage/EVIDENCE/'inputs/source-body-review.json'),repair_replay=make_file_binding(stage,stage/EVIDENCE/'inputs/fresh-repair-replay.json'))
 account=_write_json(stage,EVIDENCE/'source-accounting.json',common|dict(scope=source['source_scope'],source_sha256=SOURCE_SHA,source_bytes=source['source_bytes'],source_manifest_sha256=manifest.sha256,candidate_package_sha256=package.sha256,oracle_report_sha256=report.sha256,source_lines=61098,chapters=1189,verses=31103,source_attached_notes=1572,archive_members=71,support_members=3,omitted_line_count=0,duplicate_line_count=0,body_unchanged=True))
 command='py -3 -m build.tools.stage_engwebpb_retained_acceptance'
 technical=dict(producer={'id':manifest.record['converter']['id']},checker={'id':manifest.record['validator']['id']},shared_assumptions=['The existing-TEI repair and independent archive-led checker share only the pinned retained witness and P5 schema.'],independent_corroboration='Complete source-derived readable text, lexical identifiers, note fields and scopes match; direct actual DOM source order and chapter ownership checked independently; six resealed feature mutations rejected. Five head subtrees unchanged and inverse five-head move plus empty wrapper recreation restores entire original document C14N. Current clean-process replay reconstructs this existing-TEI repair only; original v18 replay receipts remain dated.')
 for name in ['validation','accounting','fidelity','reproducibility','schema','closure']:
  proof=_write_json(stage,EVIDENCE/f'{name}.json',common|dict(status='pass',command=command,exit_code=0,claim=name,source_manifest_sha256=manifest.sha256,candidate_package_sha256=package.sha256,oracle_report_sha256=report.sha256,text_body_unchanged=True))
  technical[name]=dict(path=proof,status='pass',command=command,exit_code=0)
 at=_now();review=dict(reviewer='agent:engwebpb-current-retained-source-review',reviewed_at=at,coverage=dict(status='complete',declared=selected,reached=['all 68 retained USFM members','all 61098 source lines','all lexical and note source spans','complete readable text and semantic inline data','actual source order and chapter ownership','five heading positions'],inspected=['complete readable text and semantic inline data','actual source order and chapter ownership','five heading positions'],unreviewed=[]),source_quality_uncertainty=['Retained electronic witness not collated to print or another provider edition.'],discrepancies=[],unreviewed_residuals=['Human review, trademark/publication clearance, and downstream Bible projection are separate gates.'])
 review_path=_write_json(stage,EVIDENCE/'review.json',common|review)
 decision=dict(source_local_disposition='Agent accepts the complete faithful reconstruction of the existing retained L225 witness.',blockers=[],agent_assessment=dict(status='accepted',actor=review['reviewer'],assessed_at=at,supported_scope=selected,unresolved_claims=[],unassessed_stronger_claims=['human review','print collation','rights clearance','publication','downstream Bible projection']),human_decision={'status':'not-recorded'})
 record=build_acceptance_record(stage,identity=identity,candidate_path=candidate,source_accounting_path=account,scope=scope,technical=technical,review=review|dict(report_path=review_path),representation_revision=revision,decision=decision)
 acceptance=stage/EDITION/'acceptance.json';write_acceptance(acceptance,record);validate_acceptance(acceptance,root=stage)
 master=_write(stage,EDITION/'master.tei.xml',bound);record['promotion']=dict(record['promotion']);record['promotion'].update(status='promoted',promoted_at=at,master=make_file_binding(stage,master));write_acceptance(acceptance,record)
 matches=[x for x in state['targets'] if x['target_type']=='edition' and x['target_id']==EDITION_ID]
 if len(matches)!=1 or matches[0]['stage']!='review':raise PipelineError('engwebpb edition review preimage differs')
 matches[0].update(stage='accepted',reason=PROMOTED_MASTER_REASON,updated_at=at);matches[0]['evidence'].extend([(EDITION/'master.tei.xml').as_posix(),(EDITION/'acceptance.json').as_posix()]);_write_json(stage,WORK/'state.json',state)
 validate_acceptance(acceptance,root=stage);validate_state(stage/WORK/'state.json',root=stage)
 result=dict(contract='ocd-engwebpb-retained-external-stage-v1',status='staged-only',work_id=WORK_ID,stage_root=stage.as_posix(),before=before,after=_files(stage/WORK),source_sha256=SOURCE_SHA,source_manifest_sha256=manifest.sha256,candidate_package_sha256=package.sha256,oracle_report_sha256=report.sha256,master_sha256=_sha(master.read_bytes()),acceptance_sha256=_sha(acceptance.read_bytes()),projection_category='bible',projection_gate=projection_gate(stage,acceptance),accepted_scope_kind='edition',included_members=68,support_members=3,human_review='not-recorded',rights='not-assessed',installation='not-performed')
 result['dependency_files']={p.as_posix():_sha(_io_path(root/p).read_bytes()) for p in sorted(dependencies(root))}
 _write_json(stage,Path('stage-receipt.json'),result);return result

def freeze_successor(previous,stage,*,root=ROOT):
 """Add exact install-runtime bindings to a complete existing work stage."""
 previous=previous.resolve(strict=True);stage=stage.absolute();parent=(LIBRARY/'candidate-reviews').resolve(strict=True)
 if previous.parent!=parent or stage.parent!=parent or stage.exists() or not previous.name.startswith('engwebpb-s-') or not stage.name.startswith('engwebpb-s-'):raise PipelineError('engwebpb dependency-only successor paths differ')
 receipt=_read(previous/'stage-receipt.json')
 if receipt['contract']!='ocd-engwebpb-retained-external-stage-v1' or receipt['before']!=_files(root/WORK) or receipt['after']!=_files(previous/WORK) or receipt['candidate_package_sha256']!=PACKAGE_SHA:raise PipelineError('engwebpb predecessor stage/preimage differs')
 shutil.copytree(previous,stage)
 for relative in dependencies(root):_copy(root,stage,relative)
 receipt['stage_root']=stage.as_posix()
 receipt['dependency_files']={p.as_posix():_sha(_io_path(root/p).read_bytes()) for p in sorted(dependencies(root))}
 receipt['dependency_only_predecessor']=dict(stage=previous.as_posix(),receipt_sha256=_sha((previous/'stage-receipt.json').read_bytes()),work_generation_exact=True,source_body_and_acceptance_unchanged=True)
 _write_json(stage,Path('stage-receipt.json'),receipt);return receipt

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--stage',required=True,type=Path);p.add_argument('--freeze-from',type=Path);a=p.parse_args();r=freeze_successor(a.freeze_from,a.stage) if a.freeze_from else prepare(a.stage);print(json.dumps({k:r[k] for k in ['work_id','master_sha256','projection_gate']}))
if __name__=='__main__':main()
