"""Bind existing successful six-case source mutations and fresh complete baseline."""
from pathlib import Path
from hashlib import sha256
import json
from build.tei.bcp1662_current_oracle import check
from build.tools.prepare_bcp1662_current import ROOT,BASE,LOG,canonical
from ocd_kernel.reconstruction.contract import SourceManifest,CandidatePackage
from ocd_kernel.library._common import io_path

def main():
    candidate=CandidatePackage.load(Path('D:/Library/Open Christian Data/candidate-reviews/bcp1662-current-candidate-20261002-v4/package'))
    replay=CandidatePackage.load(Path('D:/Library/Open Christian Data/candidate-reviews/bcp1662-current-replay-20261002-v4/package'))
    if candidate.sha256!=replay.sha256 or any(candidate.member_bytes(n)!=replay.member_bytes(n) for n in candidate.member_names):
        raise ValueError('Exact complete package replay differs')
    evidence=ROOT/'reports/_logs/bcp1662-liturgies-support-20261002-v1'
    proof=json.loads(io_path(evidence/'focused-freeze.json').read_bytes())
    for path,h in proof['bindings'].items():
        if sha256(io_path(ROOT/path).read_bytes()).hexdigest()!=h:
            raise ValueError('Focused mutation binding changed: '+path)
    log=io_path(evidence/'unexecuted-tests-v2.log').read_text()
    cases=[]
    for kind in ('wording','role','heading','break','member-omit','link-target'):
        node=f'test_whole_historical_inverse_and_source_proof_rejects_mutations[{kind}]'
        if not any(node in line and 'PASSED' in line for line in log.splitlines()):
            raise ValueError('Executed source mutation missing: '+kind)
        cases.append(dict(id=kind,status='rejected',executed_proof=(evidence/'unexecuted-tests-v2.log').relative_to(ROOT).as_posix(),pytest_node=node))
    manifest=SourceManifest.load(ROOT/BASE/'source-manifest.json',repository_root=ROOT)
    baseline=check(manifest,candidate.member_bytes('content.tei.xml'))
    result=dict(status='pass',candidate_sha256=candidate.sha256,replay_sha256=replay.sha256,source_manifest_sha256=manifest.sha256,baseline=baseline,cases=cases,qualified_reuse='Existing executed source mutation proof reused without repeating six successful cases; current exact candidate/master and test/runtime/input hashes checked.',test_sha256=proof['bindings']['tests/test_bcp1662_native_liturgies.py'])
    dest=io_path(ROOT/LOG/'mutations-v4'); dest.mkdir(exist_ok=False)
    (dest/'result.json').write_bytes(canonical(result))
    print(json.dumps(result))

if __name__=='__main__':
    main()
