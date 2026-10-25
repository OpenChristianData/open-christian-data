"""Fresh-process complete Calvin corpus candidate and independent validation."""
import argparse,json,os
from hashlib import sha256
from pathlib import Path
from ocd_kernel.reconstruction.contract import SourceManifest,reconstruct,validate
from build.tei.calvin_institutes_complete_native import _convert
from build.tei.calvin_institutes_complete_native_oracle import _oracle
from build.tools.prepare_calvin_complete_native import ROOT,BASE,canonical
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    manifest=SourceManifest.load(ROOT/BASE/'source-manifest.json',repository_root=ROOT)
    candidate=reconstruct(manifest,args.output/'package',_convert);result=validate(manifest,candidate,_oracle)
    (args.output/'validation.json').write_bytes(canonical(dict(contract='ocd-validation-report-v1',status=result.status,candidate_sha256=result.candidate_sha256,source_manifest_sha256=result.source_manifest_sha256,attestation=dict(result.attestation),findings=list(result.findings))))
    if result.status!='pass':raise ValueError(result.findings)
    receipt=dict(pid=os.getpid(),exit_code=0,candidate_sha256=candidate.sha256,tei_sha256=sha256(candidate.member_bytes('content.tei.xml')).hexdigest(),source_manifest_sha256=manifest.sha256)
    (args.output/'process.json').write_bytes(canonical(receipt));print(json.dumps(receipt))
if __name__=='__main__':main()
