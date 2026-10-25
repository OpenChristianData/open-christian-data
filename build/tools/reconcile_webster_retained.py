"""Bounded retained-only Webster source/candidate/receipt reconciliation."""
from pathlib import Path
from hashlib import sha256
import json
from datetime import datetime,timezone
from ocd_kernel.library._common import io_path,io_glob
ROOT=Path(__file__).resolve().parents[2];LOG=ROOT/'reports/_logs/webster-current-reconciliation-20261002-v1'
def binding(p):
 b=io_path(p).read_bytes();return dict(path=p.as_posix(),bytes=len(b),sha256=sha256(b).hexdigest())
def main():
 receipt_path=ROOT/'plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-08-ticket37/reviews/37c-319-receipt.json';receipt=json.loads(receipt_path.read_bytes());declared=Path(receipt['candidate']['root']);durable=Path('D:/Library/Open Christian Data/candidate-reviews')
 roots=[declared];scan=[]
 try:
  for p in durable.iterdir():
   if 'webster' in p.name.lower():roots.append(p);scan.append(p.as_posix())
 except PermissionError as e:scan.append(dict(status='PermissionError',detail=str(e)))
 probes=[];available=[]
 for root in roots:
  for package in (root/'package',root):
   path=package/'manifest.json'
   try:
    raw=io_path(path).read_bytes();m=json.loads(raw)
    if not isinstance(m,dict) or m.get('work_id') not in (None,'webster') or not any(a['name']=='content.tei.xml' for a in m.get('members',[])):raise ValueError('Not a Webster candidate package')
    rows=[]
    for a in m['members']:
     if a['name'] not in ('content.tei.xml','README.source.md','source-accountability.json','provenance.json','unresolved.jsonl'):raise ValueError('Unexpected retained member')
     b=io_path(package/a['name']).read_bytes()
     if sha256(b).hexdigest()!=a['sha256'] or len(b)!=a['bytes']:raise ValueError('Retained package member mismatch')
     rows.append(dict(name=a['name'],bytes=len(b),sha256=a['sha256']))
    available.append((package,raw,m));probes.append(dict(path=path.as_posix(),status='verified-package',package_sha256=sha256(raw).hexdigest(),members=rows))
   except (FileNotFoundError,PermissionError) as e:probes.append(dict(path=path.as_posix(),status=type(e).__name__,detail=str(e)))
 source=ROOT/'raw/bible_databases/formats/json/Webster.json';source_b=io_path(source).read_bytes();s=json.loads(source_b);profile=json.loads((ROOT/'sources/bible-text/webster/webster.reconstruction-profile.json').read_bytes());books=s['books'];verses=[v for b in books for c in b['chapters'] for v in c['verses']]
 if sha256(source_b).hexdigest()!='12b70533fcc01b5bad9d704af348617208a525f4ed2fbaf869736e83ef352f6a':raise ValueError('Retained source differs')
 log=io_path(LOG);log.mkdir(parents=True,exist_ok=True)
 if (log/'preflight.json').exists():raise FileExistsError('Preserve previous preflight')
 if available:
  selected=available[0];target=log/'historical-package';target.mkdir(exist_ok=False)
  for a in selected[2]['members']:(target/a['name']).write_bytes(io_path(selected[0]/a['name']).read_bytes())
  (target/'manifest.json').write_bytes(selected[1])
 inputs=[receipt_path,source,ROOT/'build/tei/webster_reconstruction.py',ROOT/'build/tei/webster_oracle.py',ROOT/'sources/bible-text/webster/webster.source-manifest.json',ROOT/'sources/bible-text/webster/webster.reconstruction-profile.json',ROOT/'sources/bible-text/webster/webster.validation-policy.json']+[p for p in io_glob(ROOT/'library/works/webster','**/*') if io_path(p).is_file()]
 result=dict(status='pass',checked_at=datetime.now(timezone.utc).isoformat(),work_id='webster',canonical_authority_files=[binding(p) for p in inputs if 'library' in p.parts],current_stage='acquired-only',source=binding(source),literal_translation=s['translation'],books=len(books),chapters=sum(len(b['chapters']) for b in books),verses=len(verses),empty=sum(v['text']=='' for v in verses),opening_text=verses[0]['text'],closing_text=verses[-1]['text'],source_scope='Complete single retained electronic JSON, all ordered books/chapters/verses, no printed-edition or universal versification inference.',historical_declared_candidate_root=declared.as_posix(),bounded_top_level_durable_names=scan,probes=probes,retained_candidate_available=bool(available),selected_candidate_root=available[0][0].as_posix() if available else None,prior_report_disposition=receipt['disposition'],prior_private_completion='No canonical publication/master/acceptance and no named work report folder before this task; historic37c319 explicitly nonaccepted/nonpublication. Not a claim about unsearched external records.',profile_example_disposition=dict(historical_example=profile['source_text_example'],actual_primary_opening=verses[0]['text'],example_matches_source=False,handling='Copied example is not adopted; original profile preserved. Producer and independent oracle derive actual full source, and expected zero leading/trailing whitespace reflects this source.'),input_bindings=[binding(p) for p in inputs],rights='ExactJSON has no individual translator/editor/date/license fields.1833/NoahWebster/PublicDomain config claims are historical support; repository MIT software license separately visible; underlying translation rights remain unassessed.',new_acquisition=False,canonical_mutations=False)
 (log/'preflight.json').write_text(json.dumps(result,sort_keys=True,ensure_ascii=True,indent=2)+'\n',encoding='utf-8');print(json.dumps(dict(status='pass',candidate_available=bool(available),selected=result['selected_candidate_root'],counts=(len(books),result['chapters'],len(verses)),probes=probes),ensure_ascii=True)[:8500])
if __name__=='__main__':main()
