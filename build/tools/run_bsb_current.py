"""Fresh-process BSB candidate replay and independent source validation."""
import argparse,json,os
from pathlib import Path
from hashlib import sha256
from ocd_kernel.reconstruction.contract import SourceManifest,reconstruct,validate
from build.tei.bsb_current_reconstruction import _convert
from build.tei.bsb_current_oracle import _oracle
from build.tools.prepare_bsb_current import ROOT,BASE,canonical
def main():
 a=argparse.ArgumentParser(description=__doc__);a.add_argument('--output',type=Path,required=True);p=a.parse_args().output;p.mkdir(parents=True,exist_ok=False)
 m=SourceManifest.load(ROOT/BASE/'source-manifest.json',repository_root=ROOT);c=reconstruct(m,p/'package',_convert);v=validate(m,c,_oracle)
 (p/'validation.json').write_bytes(canonical(dict(contract='ocd-validation-report-v1',status=v.status,candidate_sha256=v.candidate_sha256,source_manifest_sha256=v.source_manifest_sha256,attestation=dict(v.attestation),findings=list(v.findings))))
 if v.status!='pass':raise ValueError(v.findings)
 (p/'process.json').write_bytes(canonical(dict(pid=os.getpid(),exit_code=0,candidate_sha256=c.sha256,tei_sha256=sha256(c.member_bytes('content.tei.xml')).hexdigest())))
 print(json.dumps(dict(status=v.status,candidate_sha256=c.sha256,tei_sha256=sha256(c.member_bytes('content.tei.xml')).hexdigest())))
if __name__=='__main__':main()
