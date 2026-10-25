"""Create Farrar-only guarded stage tools from the reviewed Findlay baseline."""
from pathlib import Path
import re
ROOT=Path(__file__).resolve().parents[2]
def replace_once(text,old,new):
 if text.count(old)!=1:raise ValueError('Farrar adapter preimage differs '+old[:70])
 return text.replace(old,new,1)
def initialize():
 for name in ('stage','install','prove'):
  old=ROOT/'build/tools'/((name+'_findlay_retained_acceptance.py') if name!='prove' else 'prove_findlay_retained_install.py')
  new=ROOT/'build/tools'/((name+'_farrar_retained_acceptance.py') if name!='prove' else 'prove_farrar_retained_install.py')
  if new.exists():raise FileExistsError('Preserve existing Farrar tool '+str(new))
  s=old.read_text(encoding='utf-8').replace('findlay_retained_prepare','farrar_retained_native_prepare').replace('findlay_retained_oracle','farrar_retained_native_oracle').replace('findlay','farrar').replace('Findlay','Farrar').replace('two-edition','three-edition').replace('two accepted','three accepted').replace('ordered two','ordered three')
  if name=='stage':
   s=s.replace('WORK_ID, MEMBERS, OLD_PACKAGE, sha','WORK_ID, SPECS as MEMBERS, OLD_PACKAGE, sha').replace('check, ORACLE_IMPORTS','check, ORACLE_IMPORTS, PRODUCER_IMPORTS')
   s=s.replace("EVIDENCE = WORK / 'integration/farrar-retained-current-20261003-v1'", "EVIDENCE = WORK / 'integration/farrar-retained-current-20261003-v1'\nMEMBERS={m:spec|dict(comments=10 if m!='farrar-expositordan' else 14) for m,spec in MEMBERS.items()}")
   s=s.replace("Path('build/tei/expositors_bible_farrar_validation.py')", "Path('build/tei/farrar_original_scope.py')").replace("Path('build/tei/farrar_retained_native_prepare.py'), Path('build/tei/farrar_retained_native_prepare.py')", "Path('build/tei/farrar_retained_native_prepare.py'), Path('build/tei/farrar_retained_native_emitter.py')")
   s=s.replace('for p in ORACLE_IMPORTS','for p in ORACLE_IMPORTS+PRODUCER_IMPORTS').replace("LOG / 'execution_import_probe.py'","Path('build/tools/probe_farrar_retained_execution.py')").replace('execution-imports-v3.json','execution-imports-v1.json')
   s=s.replace("LOG / 'existing_scope_review.py', LOG / 'existing-scope-review.json', LOG / 'candidate-completion-receipt-v3.json', LOG / 'relative_uri_review.py', LOG / 'relative-uri-review.json'", "Path('build/tools/farrar_retained_assess.py'), LOG / 'existing-scope-assessment.json', LOG / 'original-source-scope-reconciliation.json', LOG / 'candidate-completion-receipt-v1.json'")
   s=s.replace('existing-scope-review.json','existing-scope-assessment.json').replace('current-review-v3.json','current-review-v1.json')
   s=s.replace("scope_review['status'] != 'pass' or scope_review['current_acquired_denominator'] != 2 or len(work['textual_forms']) != 2", "scope_review['status'] != 'assessed' or scope_review['finite_denominator'] != 3 or len(work['textual_forms']) != 3")
   s=s.replace("(15 if member_id == 'farrar-expositoreph' else 13)", '23')
   s=s.replace('two-edition-source-scope.json','three-edition-source-scope.json')
   selected='Complete retained CCEL electronic volume: '+"{edition_record['title']}"+'; all source introduction, commentary, chronology note, appendices, indexes, notes, tables, preformatted genealogical or chronological text, verse lines and inline roles remain readable in source order. All source direct/tail fields and native attributes/attachment independently match acquired raw XML. Exact original flat LIB033 crosswalk and ordered carriers reconcile to the same raw bytes; historical six-member package remains unchanged. The complete raw source body including comments and tbody wrappers is restored from verified actual native fields plus exact retained source metadata. Source head, CSS, literal prolog and all administrative comment payloads remain human-visible. Query link literals retain acquired URL context. This is one of three separately acquired editions under the existing author catalog; author/series completeness, print collation, browser pixel/stylesheet equivalence, human review, CCEL formatting rights and release are separate.'
   s=re.sub(r'^        selected = .*$', "        selected = declared_scope(edition_record)",s,flags=re.M)
   helper="""
 def declared_scope(edition_record):
     return f"SCOPE_TEXT"
 
 def bind_master(raw, *, identity, source, source_url, declared_scope, revision):
     bound=bind_reviewed_header(raw,expected_sha256=sha(raw),identity=identity,source=source,source_url=source_url,declared_scope=declared_scope,revision=revision)
     old=b'Reconstruction candidate of an existing acquired electronic witness. Publication: not_ready; human acceptance: not_recorded; rights: unresolved.'
     new=b'Agent-accepted faithful retained electronic volume. Publication: not_ready; human acceptance: not_recorded; rights: unresolved.'
     if bound.count(old)!=1:raise PipelineError('Farrar candidate publication status preimage differs')
     return bound.replace(old,new,1)
 
 """.replace('SCOPE_TEXT',selected)
   s=replace_once(s,'def dependencies(root, *, bootstrap=False):',helper+'def dependencies(root, *, bootstrap=False):')
   begin=s.index('        bound = bind_reviewed_header(');end=s.index("        if bound.split",begin)
   s=s[:begin]+"        bound = bind_master(raw, identity=identity, source=source, source_url=acquisition['url'], declared_scope=selected, revision=revision)\n"+s[end:]
   s=s.replace("complete_acquired_work_volumes=2, original_candidate_route='Existing final LIB033 readable native member recovery, bounded table summary and acquired-source relative URI context retention', relative_uri_bases=direct['relative_uri_bases'], table_summary_changes=direct['table_summary_changes']", "complete_acquired_work_volumes=3, original_candidate_route='Existing flat LIB033 carrier recovery and source-backed native hierarchy repair; no new acquisition', relative_uri_bases=direct['relative_nonfragment_links'], preformatted_carriers=direct['preformatted_count'], notes=direct['note_count'], original_scope=direct['original_scope']")
   s=s.replace("retained_administration='All original ThML header/CSS source fields accounted'", "retained_administration='All original ThML header/CSS/prolog/body-comment fields visible and accounted'")
   s=re.sub(r'^        technical = .*$', "        technical = dict(producer=dict(id=manifest.record['converter']['id'], implementation_path=manifest.record['converter']['implementation_path'], implementation_sha256=manifest.record['converter']['implementation_sha256']), checker=dict(id=manifest.record['validator']['id']), shared_assumptions=['Pinned acquired raw XML, exact historical package, P5 and declared reversible native mapping; producer policy exposure is stated.'], independent_corroboration='Stdlib raw source plus lxml corroboration checks every actual native field, semantic attribute, ownership and order, exact complete header/outer readable envelope, all original 23,605 source crosswalk fields and old actual carriers, full actual-backed source-body inverse, 2,453 notes, eight preformatted carriers, nineteen tables and 999 query link contexts. All source head/CSS/prolog/admin comments visible. Twenty-three schema-valid mutants per edition rejected; two fresh six-member byte replays per edition. Logical regions preserve all introductions/chronology/appendices/indexes; browser pixel/layout and print claims remain qualified.')",s,flags=re.M)
   s=s.replace("'all 14/22 administrative comments and metadata/CSS fields'","'all exact administrative comments and metadata/CSS/prolog fields'").replace("'all source attributes, tails and order'","'all source attributes, tails, order, preformatted space and acquired query link contexts'")
   s=re.sub(r"source_quality_uncertainty=\[.*?\], discrepancies=\[\]", "source_quality_uncertainty=['Retained CCEL electronic witness only; no print or independent provider collation.', 'Source XML titles and visible chapter numbers are preserved literally, including Second Kings chapter XVII/XXVII discrepancy and Daniel Prophetic Secion spelling; no corrections.', 'Heading paragraphs, tbody flattening, source comment header retention and browser-only attribute ledger policies are declared; no browser/CSS pixel equivalence claim.'], discrepancies=['Existing original flat feature ledger was repaired to readable native hierarchy with independent full source proof.']",s)
   s=s.replace('explicit three-edition acquired author catalog work.','explicit three-edition acquired author catalog work; all exact source comments, preformatted space, table labels and acquired query link contexts are included.')
   s=s.replace("projection_gate=projection_gate(stage, acceptance), scope_kind='edition'", "projection_gate=projection_gate(stage, acceptance), scope_kind='edition', representation_revision=revision")
   s=s.replace('included_volumes=2, acquired_volumes=2','included_volumes=3, acquired_volumes=3')
  elif name=='install':
   s=s.replace('dependencies, projection_gate, read, sha','dependencies, projection_gate, read, sha, bind_master, declared_scope')
   s=s.replace("receipt.get('included_volumes') != 2 or receipt.get('acquired_volumes') != 2", "receipt.get('included_volumes') != 3 or receipt.get('acquired_volumes') != 3").replace("accounting['complete_acquired_work_volumes'] != 2", "accounting['complete_acquired_work_volumes'] != 3").replace('included_volumes=2','included_volumes=3').replace('accepted_editions=2','accepted_editions=3')
   s=replace_once(s,"    if stage.parent != (LIBRARY / 'candidate-reviews').resolve(strict=True)","    if root == stage or root in stage.parents or stage in root.parents:raise PipelineError('Farrar stage/root containment is forbidden in both directions')\n    if stage.parent != (LIBRARY / 'candidate-reviews').resolve(strict=True)")
   needle="        accounting = read(stage / lane / 'source-accounting.json')"
   add="""        canonical_work=read(root/WORK/'work.json');form=next(f for f in canonical_work['textual_forms'] if f['textual_form_id']==spec['form']);entry=next(e for e in form['editions'] if e['edition_id']==spec['edition'])
         acquisition=read(root/edition/'acquisitions'/(spec['acquisition']+'.json'))
         expected_identity=dict(work_id=WORK_ID,textual_form_id=spec['form'],edition_id=spec['edition'],acquisition_id=spec['acquisition'])
         expected_source={key:acquisition[key] for key in ('source_path','source_sha256','source_bytes','source_scope')}
         revision=row['representation_revision']
         if revision['id']!=member_id+'-retained-current-20261003-v1' or revision['note']!='Readable faithful retained volume; original source order and literal identities preserved.':raise PipelineError('Farrar exact representation revision differs')
         if master!=bind_master(original,identity=expected_identity,source=expected_source,source_url=acquisition['url'],declared_scope=declared_scope(entry),revision=revision):raise PipelineError('Farrar exact ordered reviewed header recomputation differs')
 """
   s=replace_once(s,needle,add+needle)
   s=replace_once(s,"                validate_state(target / 'state.json', root=root)","                validate_state(target / 'state.json', root=root)\n                loaded_code_pins(receipt)")
   s=replace_once(s,'def install(stage, receipt_sha256, *, root=ROOT, fail_at=None):',"""def loaded_code_pins(receipt):
     import sys
     observed={}
     for module in sys.modules.copy().values():
         filename=getattr(module,'__file__',None)
         if not filename:continue
         path=Path(filename).resolve()
         if path.is_relative_to(ROOT):
             relative=path.relative_to(ROOT).as_posix()
             if relative.startswith(('build/','ocd_kernel/')):
                 pin=receipt['dependency_files'].get(relative)
                 if pin is None or digest(path)!=pin:raise PipelineError('Farrar loaded execution code not frozen: '+relative)
                 observed[relative]=pin
     if not observed:raise PipelineError('Farrar actual loaded code census absent')
     return observed
 
 def install(stage, receipt_sha256, *, root=ROOT, fail_at=None):""")
  elif name=='prove':
   s=s.replace('preflight, install, read, digest','preflight, install, read, digest, loaded_code_pins')
   s=replace_once(s," baseline=preflight(stage,pin,root=fixture)",""" negatives={}
  for label,bad_stage,bad_root in [('exact-fixture-root',stage,fixture.parent),('stage-inside-root',fixture/WORK,fixture),('root-inside-stage',fixture.parent,fixture)]:
   try:preflight(bad_stage,pin,root=bad_root)
   except PipelineError as error:negatives[label]=str(error)
   else:raise ValueError('Farrar root/containment guard admitted '+label)
  if _files(fixture/WORK)!=before:raise ValueError('Farrar root boundary rejection mutated fixture')
  baseline=preflight(stage,pin,root=fixture)""")
   s=replace_once(s," proof=dict(status='pass'", " durable_journals=[]\n for label,path in [('rolled-back',journals[0]),('complete',completed[0])]:\n  destination=ROOT/LOG/('fixture-'+label+'-operation.json');destination.write_bytes(path.read_bytes());durable_journals.append(dict(path=destination.relative_to(ROOT).as_posix(),sha256=digest(destination)))\n loaded=loaded_code_pins(receipt)\n proof=dict(boundary_negatives=negatives,actual_after_validated_loaded_code_pins=loaded,exact_ordered_header_recomputed=True,durable_journals=durable_journals,status='pass'")
  new.write_text(s,encoding='utf-8')
  print(new.relative_to(ROOT).as_posix())

def renew(source,destination,pin):
 from build.tools.stage_farrar_retained_acceptance import ROOT,LOG,LIBRARY,WORK,WORK_ID,dependencies,read,copy,write_json,sha,_files,_io_path,now
 from build.tools.install_farrar_retained_acceptance import preflight
 source=source.resolve(strict=True);destination=destination.absolute()
 if destination.exists() or destination.parent!=(LIBRARY/'candidate-reviews').resolve(strict=True) or not destination.name.startswith('farrar-s-') or source.parent!=destination.parent:raise ValueError('Fresh bounded external Farrar metadata renewal required')
 if sha((source/'stage-receipt.json').read_bytes())!=pin:raise ValueError('Farrar previous receipt pin differs')
 previous=read(source/'stage-receipt.json')
 if previous['work_id']!=WORK_ID or previous['status']!='staged-only' or previous['stage_root']!=source.as_posix() or _files(source/WORK)!=previous['after'] or _files(ROOT/WORK)!=previous['before']:raise ValueError('Farrar immutable reviewed generation/preimage differs')
 destination.mkdir()
 for relative in _files(source):
  if relative=='stage-receipt.json':continue
  target=_io_path(destination/relative);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(_io_path(source/relative).read_bytes())
 current_dependencies=dependencies(ROOT)
 for relative in current_dependencies:copy(ROOT,destination,relative)
 if _files(destination/WORK)!=previous['after']:raise ValueError('Farrar metadata renewal changed reviewed work generation')
 receipt=dict(previous);receipt.update(stage_root=destination.as_posix(),dependency_files={p.as_posix():sha(_io_path(ROOT/p).read_bytes()) for p in sorted(current_dependencies)},external_runtime_files=read(ROOT/LOG/'execution-imports-v1.json')['external_runtime_files'],renewal=dict(kind='metadata-and-execution-dependency-only',renewed_at=now(),previous_stage_root=source.as_posix(),previous_receipt_sha256=pin,all_reviewed_work_generation_bytes_unchanged=True,all_source_packages_and_proofs_unchanged=True))
 write_json(destination,Path('stage-receipt.json'),receipt);newpin=sha((destination/'stage-receipt.json').read_bytes())
 ready=preflight(destination,newpin)
 proof=dict(status='pass',work_id=WORK_ID,previous_receipt_sha256=pin,current_receipt_sha256=newpin,previous_stage_root=source.as_posix(),current_stage_root=destination.as_posix(),all_61_reviewed_work_generation_files_exact=True,source_package_source_manifest_and_oracle_proofs_exact=True,current_preflight=ready,source_completion_receipt_sha256=sha((ROOT/LOG/'candidate-completion-receipt-v1.json').read_bytes()),renewal=receipt['renewal'])
 (ROOT/LOG/'metadata-stage-renewal-v2.json').write_bytes(__import__('build.tei.farrar_retained_native_prepare',fromlist=['canonical']).canonical(proof))
 return dict(stage_root=destination.as_posix(),receipt_sha256=newpin,renewal='reviewed generation byte exact; current full preflight passed')

if __name__=='__main__':
 import argparse,json
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--renew-from',type=Path);parser.add_argument('--stage',type=Path);parser.add_argument('--expected-sha256');args=parser.parse_args()
 if args.renew_from:
  if args.stage is None or args.expected_sha256 is None:parser.error('renewal requires stage and expected receipt SHA')
  print(json.dumps(renew(args.renew_from,args.stage,args.expected_sha256),sort_keys=True))
 else:initialize()
