"""Fresh exact-source replay through the reviewed accepted-header binder."""
import argparse,json,os
from hashlib import sha256
from build.tools.prepare_anderson_current import *
from build.tei.anderson_current_reconstruction import _convert
from ocd_kernel.reconstruction.contract import SourceManifest
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--promoted',type=Path,required=True);a=p.parse_args()
 m=SourceManifest.load(ROOT/BASE/'source-manifest.json',repository_root=ROOT);candidate=_convert(m)['content.tei.xml'];acq=json.loads(io_path(ROOT/ACQUISITION).read_bytes());source={k:acq[k] for k in ('source_path','source_sha256','source_bytes','source_scope','source_kind')}
 identity=dict(work_id=WORK_ID,textual_form_id=FORM_ID,edition_id=EDITION_ID,acquisition_id=ACQUISITION_ID)
 revision=dict(id=REVISION,date='2026-10-02',note='Technical agent acceptance of complete retained Anderson USFM electronic witness, all30 textual members/27books/260chapters/7946verses and2489public context carriers; original body/features and IDs preserved through exact reversible scaffold aliases. Human, print, rights and publication decisions remain separate.')
 bound=bind_reviewed_header(candidate,expected_sha256=sha256(candidate).hexdigest(),identity=identity,source=source,source_url=acq['url'],declared_scope=SCOPE,revision=revision)
 accepted=io_path(a.promoted/EDITION/'master.tei.xml').read_bytes()
 if bound!=accepted or bound.split(b'</teiHeader>',1)[1]!=candidate.split(b'</teiHeader>',1)[1]:raise ValueError('Exact full accepted source replay differs')
 out=ROOT/LOG/'exact-accepted-byte-replay.tei.xml';io_path(out).write_bytes(bound)
 proof=dict(status='pass',pid=os.getpid(),exit_code=0,source_manifest_sha256=m.sha256,source_sha256=SOURCE_SHA,source_derived_candidate_sha256=sha256(candidate).hexdigest(),accepted_master_sha256=sha256(accepted).hexdigest(),output_sha256=sha256(bound).hexdigest(),exact_bytes=True,post_header_bytes_unchanged=True,scope=SCOPE,converter_sha256=sha256(Path(__import__('build.tei.anderson_current_reconstruction',fromlist=['x']).__file__).read_bytes()).hexdigest())
 put(LOG/'exact-accepted-byte-replay.json',canonical(proof));print(json.dumps(proof))
if __name__=='__main__':main()
