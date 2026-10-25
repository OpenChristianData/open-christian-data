"""Review final Watson authoring bytes without full mutation/replay generation."""
from pathlib import Path
import json
from build.tei.watson_retained_native_prepare import ROOT,LOG,MEMBERS,convert,canonical,sha
from build.tei.watson_retained_native_oracle import check,import_closure,expected_profile,expected_policy
def main():
 rows=[]
 for member in MEMBERS:
  out=ROOT/LOG/'refined-payloads'/member
  if out.exists():raise FileExistsError('Preserve refined Watson source review')
  out.mkdir(parents=True)
  for name,data in convert(member).items():(out/name).write_bytes(data)
  direct=check(member,out);profile=expected_profile(member,direct);policy=expected_policy(member,direct)
  rows.append(dict(member_id=member,source_review=direct,expected_profile=profile,expected_policy=policy))
 paths=('build/tei/watson_retained_native_emitter.py','build/tei/watson_retained_native_prepare.py','build/tei/watson_retained_native_oracle.py','build/tei/watson_original_scope.py','build/tools/watson_retained_assess.py','build/tools/watson_boundary_review.py','build/tools/prepare_watson_retained_candidates.py')
 report=dict(status='pass',members=rows,oracle_closure_sha256=import_closure(),producer_closure_sha256=import_closure('build.tei.watson_retained_native_prepare'),code_sha256={p:sha((ROOT/p).read_bytes()) for p in paths})
 (ROOT/LOG/'final-authoring-source-review.json').write_bytes(canonical(report))
 print(json.dumps(dict(status='pass',members=[dict(member_id=r['member_id'],tei_sha256=r['source_review']['tei_sha256']) for r in rows],code_sha256=report['code_sha256'],review_sha256=sha((ROOT/LOG/'final-authoring-source-review.json').read_bytes())),sort_keys=True))
if __name__=='__main__':main()
