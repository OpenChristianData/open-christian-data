"""Fresh-process exact full promoted-corpus byte replay, no canonical writes."""
import argparse,json,os
from pathlib import Path
from hashlib import sha256
from build.tools.prepare_calvin_complete_native import ROOT,WORK,EDITION,ACQUISITION,canonical
from build.tools.stage_calvin_complete_native import bind_corpus,EVIDENCE
from ocd_kernel.library._common import io_path
from ocd_kernel.tei.validate import validate_file
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--promoted',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    acceptance=json.loads(io_path(args.promoted/EDITION/'acceptance.json').read_bytes());acq=json.loads(io_path(args.promoted/ACQUISITION).read_bytes())
    raw=io_path(args.promoted/EVIDENCE/'original-package/content.tei.xml').read_bytes()
    # Acceptance JSON is canonical-key-sorted; replay the explicitly declared
    # header idno order rather than deriving insertion order from that JSON.
    identity={k:acceptance['identity'][k] for k in ('work_id','textual_form_id','edition_id','acquisition_id')}
    result=bind_corpus(raw,identity,acceptance['source'],acq['url'],acceptance['representation_revision'])
    target=args.output/'fresh-promoted-master.tei.xml';target.write_bytes(result)
    expected=io_path(args.promoted/EDITION/'master.tei.xml').read_bytes()
    if result!=expected or validate_file(target):raise ValueError('fresh exact entire promoted header replay differs')
    proof=dict(status='pass',pid=os.getpid(),exit_code=0,master_sha256=sha256(result).hexdigest(),candidate_tei_sha256=sha256(raw).hexdigest(),output_path=target.as_posix(),entire_promoted_file_byte_identical=True,member_documents_byte_conserved=True)
    (args.output/'proof.json').write_bytes(canonical(proof));print(json.dumps(proof))
if __name__=='__main__':main()
