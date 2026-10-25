"""Independently check saved Anderson rows with the Bible producer disabled."""
import argparse,json,os
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from ocd_kernel.library.identities import cached_edition_lookups
import ocd_kernel.projection.categories.bible as bible
def unavailable(*args,**kwargs):raise AssertionError('Bible producer invoked during independent saved-output verification')
def main():
 p=argparse.ArgumentParser(description=__doc__)
 for name in ('root','acceptance','projection','output'):p.add_argument('--'+name,type=Path,required=True)
 a=p.parse_args();raw=a.projection.read_bytes();projected=json.loads(raw)
 bible._projection=unavailable;bible._render=unavailable;bible.project_bible_document=unavailable;bible.project_accepted_bible=unavailable
 with cached_edition_lookups():
  errors=bible.verify_accepted_bible(a.root,acceptance_path=a.acceptance,rows=projected['rows'],receipt=projected['receipt'])
  if errors:raise ValueError(errors)
  cases=[]
  for kind in ('verse-wording','verse-omission','source-book-label-loss','source-whitespace-loss','supplied-annotation-loss','key-annotation-loss','raw-source-accounting-label'):
   rows=deepcopy(projected['rows']);index=0
   if kind=='verse-wording':rows[0]['text']='Invented wording'
   elif kind=='verse-omission':rows.pop()
   elif kind=='source-book-label-loss':rows[0]['locator']['book']='INVENTED'
   elif kind=='source-whitespace-loss':
    index=next(i for i,r in enumerate(rows) if r['text'].strip()!=r['text']);rows[index]['text']=rows[index]['text'].strip()
   else:
    wanted={'supplied-annotation-loss':'Generated annotation: source-supplied span (not an authored footnote)','key-annotation-loss':'Generated annotation: source glossary keyword (not an authored footnote)','raw-source-accounting-label':'Generated source accounting (not an authored footnote): '}[kind]
    index=next(i for i,r in enumerate(rows) if any(n['label'].startswith(wanted) for n in r['notes']))
    nindex=next(j for j,n in enumerate(rows[index]['notes']) if n['label'].startswith(wanted))
    if kind=='raw-source-accounting-label':rows[index]['notes'][nindex]['label']='Authored footnote'
    else:rows[index]['notes'].pop(nindex)
   errors=bible.verify_accepted_bible(a.root,acceptance_path=a.acceptance,rows=rows,receipt=projected['receipt'])
   required=('row count mismatch: 7945 != 7946' if kind=='verse-omission' else f'row {index+1} '+('locator mismatch' if kind=='source-book-label-loss' else 'notes mismatch' if kind in ('supplied-annotation-loss','key-annotation-loss','raw-source-accounting-label') else 'text mismatch'))
   if required not in errors:raise ValueError('Independent saved checker missed intended rejection '+kind+': '+str(errors))
   cases.append(dict(mutation=kind,status='rejected',required_diagnostic=required,errors=errors))
 result=dict(status='pass',pid=os.getpid(),exit_code=0,producer_disabled=True,projection_sha256=sha256(raw).hexdigest(),baseline_errors=[],cases=cases)
 a.output.write_text(json.dumps(result,sort_keys=True,separators=(',',':'))+'\n',encoding='utf-8');print(json.dumps(dict(status='pass',producer_disabled=True,negative_cases=7,pid=os.getpid())))
if __name__=='__main__':main()
