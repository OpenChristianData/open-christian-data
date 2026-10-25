"""Independently check saved ASV rows with the Bible producer disabled."""
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
  for kind in ('verse-wording','verse-omission','native-book-key-change','source-whitespace-loss','source-blank-filling','source-blank-omission'):
   rows=deepcopy(projected['rows'])
   if kind=='verse-wording':rows[0]['text']='Invented wording'
   elif kind=='verse-omission':rows.pop()
   elif kind=='native-book-key-change':rows[0]['locator']['book']='INVENTED'
   elif kind=='source-whitespace-loss':rows[0]['text']=rows[0]['text'].strip()
   elif kind=='source-blank-filling':next(r for r in rows if r['text']!='' and not r['text'].strip())['text']='Invented filling'
   else:
    index=next(i for i,r in enumerate(rows) if r['text']!='' and not r['text'].strip());rows.pop(index)
   errors=bible.verify_accepted_bible(a.root,acceptance_path=a.acceptance,rows=rows,receipt=projected['receipt'])
   empty_index=next(i for i,r in enumerate(projected['rows']) if r['text']!='' and not r['text'].strip())
   expected_diagnostic={'verse-wording':'row 1 text mismatch','verse-omission':'row count mismatch: 31101 != 31102','native-book-key-change':'row 1 locator mismatch','source-whitespace-loss':'row 1 text mismatch','source-blank-filling':f'row {empty_index+1} text mismatch','source-blank-omission':'row count mismatch: 31101 != 31102'}[kind]
   if expected_diagnostic not in errors:raise ValueError('Independent saved checker missed intended rejection '+kind+': '+str(errors))
   cases.append(dict(mutation=kind,status='rejected',required_diagnostic=expected_diagnostic,errors=errors))
 result=dict(status='pass',pid=os.getpid(),exit_code=0,producer_disabled=True,projection_sha256=sha256(raw).hexdigest(),baseline_errors=[],cases=cases)
 a.output.write_text(json.dumps(result,sort_keys=True,separators=(',',':'))+'\n',encoding='utf-8');print(json.dumps(dict(status='pass',producer_disabled=True,negative_cases=6,pid=os.getpid())))
if __name__=='__main__':main()
