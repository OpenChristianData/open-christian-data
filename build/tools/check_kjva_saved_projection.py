"""Independently check saved KJVA rows with the Bible producer disabled."""
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
  for kind in ('verse-wording','verse-omission','source-book-label-loss'):
   rows=deepcopy(projected['rows'])
   if kind=='verse-wording':rows[0]['text']='Invented wording'
   elif kind=='verse-omission':rows.pop(0)
   else:rows[0]['locator']['book']='1'
   errors=bible.verify_accepted_bible(a.root,acceptance_path=a.acceptance,rows=rows,receipt=projected['receipt'])
   if not errors:raise ValueError('Independent saved checker accepted '+kind)
   cases.append(dict(mutation=kind,status='rejected',errors=errors))
 result=dict(status='pass',pid=os.getpid(),exit_code=0,producer_disabled=True,projection_sha256=sha256(raw).hexdigest(),baseline_errors=[],cases=cases)
 a.output.write_text(json.dumps(result,sort_keys=True,separators=(',',':'))+'\n',encoding='utf-8');print(json.dumps(dict(status='pass',producer_disabled=True,negative_cases=3,pid=os.getpid())))
if __name__=='__main__':main()
