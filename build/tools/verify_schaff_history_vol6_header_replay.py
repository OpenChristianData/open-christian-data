"""Fresh-process exact source-package plus acceptance-header replay, without writes to authority."""
from hashlib import sha256
import json,os
from pathlib import Path
from build.tools.prepare_schaff_history_vol6_current import ROOT,BASE,EDITION,ACQUISITION,SCOPE,canonical
from ocd_kernel.library._common import io_path
from ocd_kernel.reconstruction.contract import SourceManifest,CandidatePackage
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header

def main():
    SourceManifest.load(ROOT/BASE/'source-manifest.json',repository_root=ROOT).verify()
    acceptance=json.loads(io_path(ROOT/EDITION/'acceptance.json').read_bytes());acq=json.loads(io_path(ROOT/ACQUISITION).read_bytes())
    expected=io_path(ROOT/EDITION/'master.tei.xml').read_bytes();outputs=[]
    for root in ('D:/Library/Open Christian Data/candidate-reviews/schaff-history-vol6-current-20261001-v1','D:/Library/Open Christian Data/candidate-reviews/schaff-history-vol6-current-20261001-replay-v1'):
        package=CandidatePackage.load(Path(root)/'package');raw=package.member_bytes('content.tei.xml')
        source={k:acq[k] for k in ('source_path','source_sha256','source_bytes','source_scope')}
        # Reproduce the original caller's declared key order. JSON acceptance
        # is sorted; the byte-preserving binder emits identity fields in input
        # order, so feeding its serialized order does not reproduce old bytes.
        identity={k:acceptance['identity'][k] for k in ('work_id','textual_form_id','edition_id','acquisition_id')}
        bound=bind_reviewed_header(raw,expected_sha256=sha256(raw).hexdigest(),identity=identity,source=source,source_url=acq['url'],declared_scope=SCOPE,revision=acceptance['representation_revision'])
        if bound!=expected or bound.split(b'</teiHeader>',1)[1]!=raw.split(b'</teiHeader>',1)[1]:raise ValueError('exact master/header replay or body conservation failed')
        outputs.append(dict(root=root,source_process=json.loads((Path(root)/'process.json').read_bytes()),candidate_sha256=package.sha256,tei_sha256=sha256(raw).hexdigest(),master_sha256=sha256(bound).hexdigest(),entire_master_byte_equal=True,text_and_standoff_byte_unchanged=True))
    receipt=dict(status='pass',pid=os.getpid(),authoritative_exit_code=0,identity_key_order=list(identity),outputs=outputs)
    io_path(ROOT/'reports/_logs/schaff-history-vol-6-reconciliation-20261001-v1/exact-promoted-header-replay.json').write_bytes(canonical(receipt))
    print(json.dumps(receipt))
if __name__=='__main__':main()
