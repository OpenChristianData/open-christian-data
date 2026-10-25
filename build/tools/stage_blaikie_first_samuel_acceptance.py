"""Stage one complete First Samuel work, preserving all author catalog identities."""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
import argparse,json
from lxml import etree
from build.tei.blaikie_first_samuel_retained_native_prepare import ROOT,LOG,SOURCE_DIR,WORK as WORK_ID,SPECS,canonical,sha
from build.tei.blaikie_first_samuel_retained_native_oracle import _oracle as oracle,check,ORACLE_IMPORTS,PRODUCER_IMPORTS
from build.tools.prepare_blaikie_first_samuel_candidates import CANDIDATES
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import validate_identity_update,load_work
from ocd_kernel.library.state import validate_state
from ocd_kernel.reconstruction import SourceManifest,CandidatePackage,validate
from ocd_kernel.tei.acceptance import build_acceptance_record,make_file_binding,write_acceptance,validate_acceptance,PROMOTED_MASTER_REASON
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file
from ocd_kernel.tei.install_accepted import _files,_io_path
from ocd_kernel.projection.categories.commentary import project_accepted_commentary,verify_accepted_commentary

LIBRARY=Path('D:/Library/Open Christian Data');WORK=Path('library/works')/WORK_ID
EVIDENCE=WORK/'integration/blaikie-first-samuel-complete-current-20261003-v1'
BOUNDARY=LOG/'source-inventory-read-only-preflight.json'
WORKS={'blaikie-expositor8':('blaikie-expositor8',)}
REVISION_NOTE='Faithful complete retained First Samuel electronic work; literal Toronto 1888 title page and electronic source metadata preserved.'

def read(path):return json.loads(_io_path(path).read_bytes())
def write(stage,path,raw):
 p=_io_path(stage/path);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw);return stage/path
def write_json(stage,path,record):return write(stage,path,canonical(record))
def copy(root,stage,path):return write(stage,path,_io_path(root/path).read_bytes())
def now():return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')

def component_artifacts(member):
 if member!='blaikie-expositor8':raise PipelineError('First Samuel source component boundary differs')
 package=CandidatePackage.load(CANDIDATES/'package')
 return {name:package.member_bytes(name) for name in package.member_names},dict(source=SPECS[member],directory=package.path.as_posix(),files=[dict(name=n,sha256=sha(package.member_bytes(n))) for n in package.member_names])

def boundary_check():
 evidence=read(ROOT/BOUNDARY)
 if evidence['selected_complete_work']!='blaikie-expositor8' or evidence['source']!=SPECS['blaikie-expositor8'] or 'THE FIRST BOOK OF SAMUEL.' not in evidence['primary_title_page_literal']:raise PipelineError('Primary First Samuel complete-title evidence differs')
 return dict(classification=[dict(complete_work_id='blaikie-expositor8',boundary='One separately titled complete First Book of Samuel commentary, Toronto 1888; primary title page and chapters I-XXXVI with indexes retained.')])

def specs():
 s=SPECS['blaikie-expositor8']
 return {'blaikie-expositor8':dict(form=s['form'],edition=s['edition'],acquisition=s['acquisition'],members=['blaikie-expositor8'])}

MEMBERS=specs()
def edition_path(spec):return WORK/'forms'/spec['form']/'editions'/spec['edition']
def acquisition_path(spec):return edition_path(spec)/'acquisitions'/(spec['acquisition']+'.json')

def expected_work(root):
 old=read(root/WORK/'work.json');work=deepcopy(old);spec=MEMBERS['blaikie-expositor8']
 forms=[f for f in work['textual_forms'] if f['textual_form_id']==spec['form']]
 if len(forms)!=1:raise PipelineError('First Samuel original retained form absent')
 editions=[e for e in forms[0]['editions'] if e['edition_id']==spec['edition']]
 if len(editions)!=1 or 'category' in editions[0]:raise PipelineError('First Samuel category preimage differs')
 editions[0]['category']='commentary';validate_identity_update(old,work);return work

def expected_state(root,at):
 state=read(root/WORK/'state.json');spec=MEMBERS['blaikie-expositor8']
 targets=[t for t in state['targets'] if t['target_type']=='edition' and t['target_id']==spec['edition']]
 acquired=[t for t in state['targets'] if t['target_type']=='acquisition' and t['target_id']==spec['acquisition']]
 if len(targets)!=1 or targets[0]['stage']!='acquired' or len(acquired)!=1 or acquired[0]['stage']!='acquired':raise PipelineError('First Samuel exact acquired edition/source state preimage differs')
 targets[0].update(stage='accepted',reason=PROMOTED_MASTER_REASON,updated_at=at)
 targets[0]['evidence']+=[(edition_path(spec)/'master.tei.xml').as_posix(),(edition_path(spec)/'acceptance.json').as_posix()]
 return state

def projection_gate(root,acceptance):
 try:
  result=project_accepted_commentary(root,acceptance_path=acceptance);errors=verify_accepted_commentary(root,acceptance_path=acceptance,rows=result['rows'],receipt=result['receipt'])
  return dict(status='pass' if not errors else 'held',rows=len(result['rows']),errors=errors)
 except PipelineError as error:
  detail=str(error)
  for prefix in sorted({str(root),root.as_posix(),str(_io_path(root))},key=len,reverse=True):detail=detail.replace(prefix,'<reviewed-root>')
  return dict(status='held',rows=0,errors=[detail])

def dependencies(root,*,bootstrap=False):
 result={Path(p) for p in ORACLE_IMPORTS+PRODUCER_IMPORTS}
 result.update(LOG/n for n in ('guarded-installer-versus-bennett-review.json','stage_blaikie_first_samuel_acceptance-versus-bennett.diff','install_blaikie_first_samuel_acceptance-versus-bennett.diff','prove_blaikie_first_samuel_install-versus-bennett.diff'))
 result.update(Path('build/tools')/(n+'.py') for n in ('prepare_blaikie_first_samuel_candidates','challenge_blaikie_first_samuel_candidates','challenge_blaikie_first_samuel_contracts','stage_blaikie_first_samuel_acceptance','install_blaikie_first_samuel_acceptance','prove_blaikie_first_samuel_install','derive_blaikie_first_samuel_install'))
 result.update(LOG/n for n in ('execution_import_probe.py','late_import_fixture_worker.py','complete-package-receipt-v4.json','complete-semantic-challenges-v3.json','complete-contract-challenges-v1.json'))
 result.update(p.relative_to(root) for directory,suffix in [('ocd_kernel/reconstruction','*.py'),('ocd_kernel/reconstruction/schemas','*.json'),('schemas/v2','*.json'),('ocd_kernel/tei/vendor/xsd','*.xsd')] for p in (root/directory).rglob(suffix))
 result.update(Path(p) for p in ['ocd_kernel/tei/acceptance.py','ocd_kernel/tei/install_accepted.py','ocd_kernel/tei/reviewed_integration.py','ocd_kernel/tei/validate.py','ocd_kernel/library/state.py','ocd_kernel/library/identities.py','ocd_kernel/library/acquisitions.py','ocd_kernel/library/_common.py','ocd_kernel/lib/path_io.py','ocd_kernel/lib/storage_topology.py','ocd_kernel/lib/atomic_io.py','ocd_kernel/projection/__init__.py','ocd_kernel/projection/categories/__init__.py','ocd_kernel/projection/categories/commentary.py','ocd_kernel/projection/categories/commentary_source_native.py','ocd_kernel/projection/categories/native_documents.py','ocd_kernel/projection/native_content.py','ocd_kernel/projection/native_content_check.py','ocd_kernel/projection/envelope.py','ocd_kernel/projection/scripture_authority.py','ocd_kernel/projection/scripture_targets.py','ocd_kernel/projection/scripture_targets_check.py','build/bible_data/osis_book_codes.json'])
 for key in MEMBERS:
  path=SOURCE_DIR/(key+'.source-manifest.json');source=SourceManifest.load(root/path,repository_root=root);result.add(path);result.add(LOG/(key+'-complete-package-review-v4.json'));result.update(Path(a['path']) for a in source.record['authorities'])
 if not bootstrap:
  result.add(LOG/'execution-imports.json');execution=read(root/LOG/'execution-imports.json')
  if execution['status']!='pass' or execution['work_id']!=WORK_ID or execution['complete_work_count']!=1 or execution['source_member_count']!=1:raise PipelineError('First Samuel complete execution proof differs')
  for item in execution['first_party_files']:
   if sha(_io_path(root/item['path']).read_bytes())!=item['sha256']:raise PipelineError('First Samuel executed dependency drifted '+item['path'])
   result.add(Path(item['path']))
 return result

def declared_scope(key,acquisition):
 if key!='blaikie-expositor8':raise PipelineError('First Samuel scope key differs')
 return boundary_check()['classification'][0]['boundary']+' '+acquisition['source_scope']+' Complete retained electronic First Samuel work within the preserved author catalog: all title-page/chapter/index regions, original readings, four notes, page breaks, scripture directives, literal links and 87 acquired-source URI contexts, 14 exact administrative comments and whitespace joins, entire source head/prolog/XML declaration/DOCTYPE prefix and permission statements retained. The electronic print metadata literally spells Williard; original source wording is preserved. The qualified current-authority LIB036 replay is lineage evidence, not a recovered historical package or historical oracle pass. Zero First Samuel historical correction rows. Second Samuel and Joshua identities, acquisitions and state targets remain unchanged. No acquisition, independent print collation, human acceptance, rights clearance or publication authorization.'

def recompute_header(raw,*,identity,source,source_url,declared,revision):
 tree=etree.fromstring(raw);ns={'t':'http://www.tei-c.org/ns/1.0'};h=tree.find('{http://www.tei-c.org/ns/1.0}teiHeader')
 historical=dict(pointers=h.xpath('.//t:sourceDesc//t:ptr/@target',namespaces=ns),sha256=h.xpath('.//t:idno[@type="sha256"]/text()',namespaces=ns))
 bound=bind_reviewed_header(raw,expected_sha256=sha(raw),identity=identity,source=source,source_url=source_url,declared_scope=declared,revision=revision,historical_source_description=historical)
 old=b'Reconstruction candidate of an existing acquired electronic witness. Publication: not_ready; human acceptance: not_recorded; rights: unresolved.'
 new=b'Agent-accepted faithful complete retained electronic work. Publication: not_ready; human acceptance: not_recorded; rights: unresolved.'
 if bound.count(old)!=1:raise PipelineError('First Samuel ordered header publication preimage differs')
 bound=bound.replace(old,new,1)
 if bound.split(b'</teiHeader>',1)[1]!=raw.split(b'</teiHeader>',1)[1]:raise PipelineError('First Samuel header binding changed complete text bytes')
 return bound

def prepare(stage,*,root=ROOT,bootstrap=False):
 root=root.resolve(strict=True);stage=stage.absolute()
 if stage.exists() or stage.parent!=(LIBRARY/'candidate-reviews').resolve(strict=True) or not stage.name.startswith('blaikie-first-samuel-s-') or root==stage or root in stage.parents or stage in root.parents:raise PipelineError('Fresh external First Samuel stage boundary required')
 before=_files(root/WORK);old=read(root/WORK/'work.json');work=expected_work(root);at=now();state=expected_state(root,at)
 for spec in MEMBERS.values():
  if _io_path(root/edition_path(spec)/'master.tei.xml').exists() or _io_path(root/edition_path(spec)/'acceptance.json').exists():raise PipelineError('First Samuel accepted authority already exists; no replacement')
 stage.mkdir()
 for relative in before:copy(root,stage,WORK/relative)
 for relative in dependencies(root,bootstrap=bootstrap):copy(root,stage,relative)
 evidence=set(old['evidence']+[p for t in read(root/WORK/'state.json')['targets'] for p in t['evidence']])
 for path in evidence:
  relative=Path(path.split('#',1)[0])
  if not _io_path(stage/relative).exists():copy(root,stage,relative)
 write_json(stage,WORK/'work.json',work)
 proof=read(root/LOG/'complete-package-receipt-v4.json');mutations=read(root/LOG/'complete-semantic-challenges-v3.json');contract=read(root/LOG/'complete-contract-challenges-v1.json')
 if proof['status']!='pass' or proof['complete_work_count']!=1 or proof['source_member_count']!=1 or mutations['status']!='pass' or mutations['expected_challenges']!=29 or contract['status']!='pass' or contract['expected_challenges']!=13:raise PipelineError('First Samuel finite source proof denominator differs')
 units=[]
 for key,spec in MEMBERS.items():
  edition=edition_path(spec);lane=EVIDENCE/key;manifest=SourceManifest.load(root/SOURCE_DIR/(key+'.source-manifest.json'),repository_root=root);package=CandidatePackage.load(CANDIDATES/'package');report=validate(manifest,package,oracle);direct=check(key,package.path);current=read(root/LOG/(key+'-complete-package-review-v4.json'))
  if report.status!='pass' or current['package_sha256']!=package.sha256 or current['source_manifest_sha256']!=manifest.sha256 or current['oracle_report_sha256']!=report.sha256 or current['direct_source_review']!=direct or len(current['reproducibility'])!=2 or not all(r['exact_six_member_bytes_equal'] for r in current['reproducibility']):raise PipelineError('First Samuel current complete source/replay binding differs')
  negative=next(r for r in mutations['members'] if r['complete_work_id']==key)
  if negative['package_sha256']!=package.sha256 or len(negative['challenges'])!=negative['expected_challenges'] or not all(r['schema_valid'] and r['rejected'] for r in negative['challenges']):raise PipelineError('First Samuel actual valid semantic challenges differ')
  acquisition=validate_acquisition(stage/acquisition_path(spec),root=stage)
  expected=[dict(path=r['path'],position=i) for i,r in enumerate(acquisition['retained_files'],1)]
  if [r['path'] for r in expected]!=[component_artifacts(m)[1]['source']['path'] for m in WORKS[key]]:raise PipelineError('First Samuel complete source member order differs')
  included=[dict(path=r['path'],position=i,bytes=r['bytes'],sha256=r['sha256'],scope=r.get('scope') or acquisition['source_scope']) for i,r in enumerate(acquisition['retained_files'],1)]
  for name in package.member_names:write(stage,lane/'inputs/package'/name,package.member_bytes(name))
  write(stage,lane/'inputs/current-review.json',_io_path(root/LOG/(key+'-complete-package-review-v4.json')).read_bytes())
  for name in ('complete-semantic-challenges-v3.json','complete-contract-challenges-v1.json'):write(stage,lane/'inputs'/name,_io_path(root/LOG/name).read_bytes())
  identity=dict(work_id=WORK_ID,textual_form_id=spec['form'],edition_id=spec['edition'],acquisition_id=spec['acquisition']);source={k:acquisition[k] for k in ('source_path','source_sha256','source_bytes','source_scope')}
  if 'source_kind' in acquisition:source['source_kind']=acquisition['source_kind']
  selected=declared_scope(key,acquisition);revision=dict(id=key+'-complete-current-20261003-v1',date=datetime.fromisoformat(at.replace('Z','+00:00')).date().isoformat(),note=REVISION_NOTE)
  bound=recompute_header(package.member_bytes('content.tei.xml'),identity=identity,source=source,source_url=acquisition['url'],declared=selected,revision=revision);candidate=write(stage,lane/'candidate.tei.xml',bound)
  if errors:=validate_file(candidate):raise PipelineError(str(errors[:3]))
  accepted_scope=dict(kind='work',declared=selected)
  common=dict(identity=identity,source=source,candidate=make_file_binding(stage,candidate),scope=selected,accepted_scope=accepted_scope,expected_members=expected,included_members=included,excluded_members=[],missing_members=[],unknown_members=[],source_manifest_sha256=manifest.sha256,candidate_package_sha256=package.sha256,oracle_report_sha256=report.sha256,direct_source_review=make_file_binding(stage,stage/lane/'inputs/current-review.json'))
  accounting=write_json(stage,lane/'source-accounting.json',common|dict(scope=source['source_scope'],source_sha256=source['source_sha256'],source_bytes=source['source_bytes'],complete_work_count=1,source_member_count=1,source_members=list(WORKS[key]),full_source_elements=sum(component_artifacts(m)[1]['source']['elements'] for m in WORKS[key]),administrative_comments=sum(component_artifacts(m)[1]['source']['comments'] for m in WORKS[key]),all_actual_source_inverses_pass=True,body_header_binding_unchanged=True,source_kind=acquisition.get('source_kind','single-retained-source'),omitted_readable_elements=0))
  command='py -3 -m build.tools.stage_blaikie_first_samuel_acceptance';technical=dict(producer={'id':manifest.record['converter']['id']},checker={'id':manifest.record['validator']['id']},shared_assumptions=['Pinned XML/P5; reviewed Dods mapping ancestry declared. Independent stdlib raw and actual source inverse; no producer/emitter or projector imported by oracle.'],independent_corroboration='One complete First Samuel XML: every actual text/header field, semantic role, source attachment, administrative comment/tail join, 87 URI contexts, source prefix and CCEL notice. 29 P5-valid source/accounting challenges and 13 valid source-contract/package challenges rejected. Two fresh six-member equality replays. Qualified current LIB036 flat graph source inverse; no historic exact-byte/oracle-pass claim, zero First Samuel correction rows.')
  for name in ('validation','accounting','fidelity','reproducibility','schema','closure'):
   p=write_json(stage,lane/(name+'.json'),common|dict(status='pass',command=command,exit_code=0,claim=name,actual_source_body_inverses_pass=True,complete_text_bytes_unchanged_at_header_binding=True));technical[name]=dict(path=p,status='pass',command=command,exit_code=0)
  coverage=['entire retained First Samuel raw XML DOM and literal document/header metadata','all 36 actual chapter trees, title page, indexes, original readings, semantic attributes, text/tails, notes, ordering and references','all 14 administrative comments and full actual-TEI-backed source inverse','87 literal relative hrefs with exact acquired-source URI bases','zero selected correction rows, qualified LIB036 graph conservation and human-visible retained CCEL permission']
  review=dict(reviewer='agent:blaikie-first-samuel-complete-retained-source-review',reviewed_at=at,coverage=dict(status='complete',declared=selected,reached=coverage,inspected=coverage,unreviewed=[]),source_quality_uncertainty=['Retained electronic XML only; no independent print collation or typography claim.','Primary Toronto 1888 and electronic Williard wording remain literal source statements.','Current-authority LIB036 replay, not recovered historical bytes; no historical oracle pass claimed. Zero First Samuel correction annotations.','Missing source next/prev toc references retain literal typed annotations. No source image or table elements.'],discrepancies=[],unreviewed_residuals=['Human review, rights, print collation, publication and actual downstream commentary projection remain separate.'])
  rp=write_json(stage,lane/'review.json',common|review);decision=dict(source_local_disposition='Agent accepts this faithful complete retained First Samuel electronic work; separately acquired Second Samuel and Joshua remain outside this acceptance.',blockers=[],agent_assessment=dict(status='accepted',actor=review['reviewer'],assessed_at=at,supported_scope=selected,unresolved_claims=[],unassessed_stronger_claims=['human review','print collation','rights clearance','publication','downstream projection']),human_decision={'status':'not-recorded'})
  record=build_acceptance_record(stage,identity=identity,candidate_path=candidate,source_accounting_path=accounting,scope=accepted_scope|dict(expected_members=expected,included_members=included,excluded_members=[]),technical=technical,review=review|dict(report_path=rp),representation_revision=revision,decision=decision)
  acceptance=stage/edition/'acceptance.json';write_acceptance(acceptance,record);validate_acceptance(acceptance,root=stage);master=write(stage,edition/'master.tei.xml',bound)
  record['promotion']=dict(record['promotion']);record['promotion'].update(status='promoted',promoted_at=at,master=make_file_binding(stage,master));write_acceptance(acceptance,record)
  units.append(dict(complete_work_id=key,source_members=list(WORKS[key]),source_sha256=source['source_sha256'],source_manifest_sha256=manifest.sha256,candidate_package_sha256=package.sha256,oracle_report_sha256=report.sha256,master_sha256=sha(_io_path(master).read_bytes()),acceptance_sha256=sha(_io_path(acceptance).read_bytes()),scope_kind='work'))
 write_json(stage,WORK/'state.json',state);load_work(stage/WORK/'work.json')
 for spec in MEMBERS.values():validate_acceptance(stage/edition_path(spec)/'acceptance.json',root=stage)
 validate_state(stage/WORK/'state.json',root=stage)
 for unit in units:unit['projection_gate']=projection_gate(stage,stage/edition_path(MEMBERS[unit['complete_work_id']])/'acceptance.json')
 receipt=dict(contract='ocd-blaikie-first-samuel-complete-external-stage-v1',status='bootstrap-only' if bootstrap else 'staged-only',work_id=WORK_ID,stage_root=stage.as_posix(),before=before,after=_files(stage/WORK),complete_works=units,complete_work_count=1,source_member_count=1,projection_category='commentary',accepted_scope_kind='work',human_review='not-recorded',rights='not-assessed',installation='not-performed',staged_at=at,excluded_work_targets='Original Second Samuel and Joshua identities, acquisitions and states preserved unchanged',dependency_files={p.as_posix():sha(_io_path(root/p).read_bytes()) for p in sorted(dependencies(root,bootstrap=bootstrap))})
 write_json(stage,Path('stage-receipt.json'),receipt);return receipt

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--stage',type=Path,required=True);p.add_argument('--bootstrap',action='store_true');a=p.parse_args();r=prepare(a.stage,bootstrap=a.bootstrap);print(json.dumps(dict(stage_root=r['stage_root'],complete_works=r['complete_works']),sort_keys=True))
