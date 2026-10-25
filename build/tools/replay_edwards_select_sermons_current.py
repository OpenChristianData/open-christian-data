"""Fresh-process exact accepted-header and body replay against a frozen Select Sermons stage."""
import argparse,json,os
from hashlib import sha256
from pathlib import Path
from build.tools.prepare_edwards_select_sermons_current import ROOT,WORK_ID,EDITION,ACQUISITION,canonical
from ocd_kernel.library._common import io_path
from ocd_kernel.reconstruction.contract import CandidatePackage
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("promoted","replay","output"):p.add_argument("--"+name,type=Path,required=True)
    args=p.parse_args();a=json.loads(io_path(args.promoted/EDITION/"acceptance.json").read_bytes());acq=json.loads(io_path(ROOT/ACQUISITION).read_bytes())
    package=CandidatePackage.load(args.replay/"package");raw=package.member_bytes("content.tei.xml")
    source={k:acq[k] for k in ("source_path","source_sha256","source_bytes","source_scope")}
    rebound=bind_reviewed_header(raw,expected_sha256=sha256(raw).hexdigest(),identity={k:a["identity"][k] for k in ("work_id","textual_form_id","edition_id","acquisition_id")},source=source,source_url=acq["url"],declared_scope=a["scope"]["declared"],revision=a["representation_revision"])
    installed_bytes=io_path(args.promoted/EDITION/"master.tei.xml").read_bytes()
    if rebound!=installed_bytes or rebound.split(b"</teiHeader>",1)[1]!=raw.split(b"</teiHeader>",1)[1]:raise ValueError("exact accepted replay/header/body differs")
    record=dict(status="pass",pid=os.getpid(),work_id=WORK_ID,method="Fresh process supported deterministic header binding over fresh complete source replay; exact full accepted bytes and unchanged post-header body+standOff",candidate_package_sha256=package.sha256,original_tei_sha256=sha256(raw).hexdigest(),accepted_master_sha256=sha256(installed_bytes).hexdigest(),rebound_sha256=sha256(rebound).hexdigest(),exact_bytes=True,post_header_bytes_unchanged=True)
    if args.output.exists():raise FileExistsError(args.output)
    args.output.write_bytes(canonical(record));print(json.dumps(record))
if __name__=="__main__":main()
