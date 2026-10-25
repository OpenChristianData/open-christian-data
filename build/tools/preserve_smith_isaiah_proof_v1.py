"""Preserve the source-proof harness's rejected non-P5 tail challenge."""
from pathlib import Path
from hashlib import sha256
import json
from ocd_kernel.reconstruction import CandidatePackage
ROOT=Path(__file__).resolve().parents[2]
def main():
    log=ROOT/'reports/_logs/smith-isaiah-complete-20261003-v1';target=log/'aborted-proof-v1.py';raw=(ROOT/'build/tools/prove_smith_isaiah_complete.py').read_bytes()
    if target.exists():raise FileExistsError('Preserve previous source harness')
    target.write_bytes(raw)
    proof=Path('D:/Library/Open Christian Data/candidate-reviews/smith-isaiah-complete-20261003-v3/proof-v1')
    artifacts=[dict(label=p.name.removeprefix('challenge-'),path=p.as_posix(),candidate_package_sha256=CandidatePackage.load(p).sha256) for p in sorted(proof.glob('challenge-*'))]
    if len(artifacts)!=26:raise ValueError('Exactly26 completed valid challenge artifacts expected')
    report=dict(status='aborted-harness-case',preserved_harness_sha256=sha256(raw).hexdigest(),completed_schema_valid_rejected_challenges=26,artifacts=artifacts,failure='Last outer-header-tail mutation added nonwhitespace to element-only TEI. P5 rightly rejected it before source oracle. Successor changes that harness case to unexpected valid whitespace; source/package/oracle unchanged.',canonical_changes=False)
    (log/'aborted-proof-v1.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n',encoding='utf-8')
if __name__=='__main__':main()
