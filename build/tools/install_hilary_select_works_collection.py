"""Apply only pinned prose metadata, then unchanged shared guarded installer."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
from build.tools.prepare_hilary_select_works_collection import ROOT,WORK,EDITION,WORK_ID,TITLE,canonical
from ocd_kernel.library._common import io_path
from ocd_kernel.library.identities import validate_identity_update
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files,install_accepted_work
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--promoted',type=Path,required=True);p.add_argument('--receipt-sha256',required=True);p.add_argument('--evidence',type=Path,required=True);a=p.parse_args()
    promoted=a.promoted.absolute();b=(promoted/'stage-receipt.json').read_bytes()
    if sha256(b).hexdigest()!=a.receipt_sha256:raise ValueError('receipt pin differs')
    record=json.loads(b)
    if record['status']!='pass' or record['rows']!=1 or _files(ROOT/WORK)!=record['before']:raise ValueError('stage/current preimage differs')
    validate_acceptance(promoted/EDITION/'acceptance.json',root=promoted)
    original_bytes=io_path(ROOT/WORK/'work.json').read_bytes();original=json.loads(original_bytes)
    revised_bytes=io_path(promoted/WORK/'work.json').read_bytes();revised=json.loads(revised_bytes)
    expected=json.loads(original_bytes)
    if original['title']!=TITLE or original['textual_forms'][0]['language']!='en' or original['textual_forms'][0]['editions'][0]['language']!='en':raise ValueError('pinned title/language differs')
    expected['textual_forms'][0]['editions'][0]['category']='prose'
    if expected!=revised:raise ValueError('metadata exceeds category-only prerequisite')
    validate_identity_update(original,revised)
    a.evidence.mkdir(parents=True,exist_ok=False);(a.evidence/'original-work.json').write_bytes(original_bytes);(a.evidence/'stage-receipt.json').write_bytes(b)
    (a.evidence/'metadata-prerequisite.json').write_bytes(canonical(dict(status='pass',changed_fields=['textual_forms[0].editions[0].category'],before_sha256=sha256(original_bytes).hexdigest(),after_sha256=sha256(revised_bytes).hexdigest(),scope_decision='Coordinator independently verified exact complete retained Hilary Select Works collection ii and authorized category-only prose prerequisite; original title, language, IDs, source, acquisition and containing-source locator unchanged.')))
    temp=ROOT/WORK/'.hilary_select_works_collection-work-metadata.tmp'
    if temp.exists():raise FileExistsError(temp)
    temp.write_bytes(revised_bytes);temp.replace(ROOT/WORK/'work.json')
    try:result=install_accepted_work(ROOT,promoted,work_id=WORK_ID)
    except Exception:
        if not io_path(ROOT/EDITION/'master.tei.xml').exists() and io_path(ROOT/WORK/'work.json').read_bytes()==revised_bytes:
            temp.write_bytes(original_bytes);temp.replace(ROOT/WORK/'work.json');(a.evidence/'metadata-rollback.json').write_bytes(canonical(dict(status='rolled-back')))
        raise
    validate_acceptance(ROOT/EDITION/'acceptance.json',root=ROOT)
    (a.evidence/'installation.json').write_bytes(canonical(result));print(json.dumps(result))
if __name__=='__main__':main()
