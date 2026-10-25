"""Pin the complete staged generation and accepted-header byte replay."""
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path
from build.tools.prepare_bcp1559_current import ROOT,BASE,WORK,EDITION,LOG,canonical
from ocd_kernel.library._common import io_path
from ocd_kernel.tei.install_accepted import _files

def main():
    promoted=Path('D:/Library/Open Christian Data/candidate-reviews/bcp1559-current-promoted-20261002-v1')
    path=promoted/'stage-receipt.json';raw=path.read_bytes();receipt=json.loads(raw)
    if receipt['status']!='pass' or receipt['before']!=_files(ROOT/WORK) or receipt['after']!=_files(promoted/WORK):raise ValueError('Frozen generations differ')
    if any(sha256((ROOT/p).read_bytes()).hexdigest()!=h for p,h in receipt['schema_pins'].items()):raise ValueError('Frozen stage inputs changed')
    original=Path('D:/Library/Open Christian Data/candidate-reviews/bcp1559-current-20261002-v2/package/content.tei.xml').read_bytes()
    accepted=io_path(promoted/EDITION/'master.tei.xml').read_bytes()
    if original.split(b'</teiHeader>',1)[1]!=accepted.split(b'</teiHeader>',1)[1]:raise ValueError('Reviewed complete text changed')
    accepted_record=json.loads(io_path(promoted/EDITION/'acceptance.json').read_bytes())
    replay=dict(status='pass',source_candidate_sha256=sha256(original).hexdigest(),accepted_master_sha256=sha256(accepted).hexdigest(),
                accepted_header_sha256=sha256(accepted.split(b'</teiHeader>',1)[0]+b'</teiHeader>').hexdigest(),body_exactly_unchanged=True,
                deterministic_header_replay='Stage bound current candidate and independent fresh-process package replay separately; exact whole-byte equality required.',
                bound_acceptance_sha256=sha256(io_path(promoted/EDITION/'acceptance.json').read_bytes()).hexdigest(),
                coordinator_body_review=dict(path=(LOG/'coordinator-current-body-review.json').as_posix(),sha256=sha256((ROOT/LOG/'coordinator-current-body-review.json').read_bytes()).hexdigest()))
    (ROOT/LOG/'exact-accepted-header-replay.json').write_bytes(canonical(replay))
    pin=dict(status='pass',utc=datetime.now(timezone.utc).isoformat(),receipt=path.as_posix(),receipt_sha256=sha256(raw).hexdigest(),master_sha256=receipt['master_sha256'],
             acceptance_sha256=replay['bound_acceptance_sha256'],before=receipt['before'],after=receipt['after'],dependency_bindings=receipt['schema_pins'])
    (ROOT/BASE/'stage-pin.json').write_bytes(canonical(pin))
    print(json.dumps(pin))

if __name__=='__main__':main()
