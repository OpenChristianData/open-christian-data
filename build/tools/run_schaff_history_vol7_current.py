"""Fresh-process complete Schaff volume 7 candidate and independent validation."""
import argparse,json,os
from ocd_kernel.reconstruction.contract import SourceManifest,reconstruct,validate
from build.tei.schaff_history_vol7_current_reconstruction import _convert
from build.tei.schaff_history_vol7_current_oracle import _oracle
from build.tools.prepare_schaff_history_vol7_current import ROOT,BASE,canonical
from pathlib import Path
from hashlib import sha256
def main():
    a=argparse.ArgumentParser(description=__doc__);a.add_argument("--output",type=Path,required=True);args=a.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    m=SourceManifest.load(ROOT/BASE/"source-manifest.json",repository_root=ROOT);p=reconstruct(m,args.output/"package",_convert);v=validate(m,p,_oracle)
    (args.output/"validation.json").write_bytes(canonical(dict(contract="ocd-validation-report-v1",status=v.status,candidate_sha256=v.candidate_sha256,source_manifest_sha256=v.source_manifest_sha256,attestation=dict(v.attestation),findings=list(v.findings))))
    if v.status!="pass":raise ValueError(v.findings)
    (args.output/"process.json").write_bytes(canonical(dict(pid=os.getpid(),exit_code=0,candidate_sha256=p.sha256,tei_sha256=sha256(p.member_bytes("content.tei.xml")).hexdigest())))
    print(json.dumps(dict(status=v.status,candidate_sha256=p.sha256,tei_sha256=sha256(p.member_bytes("content.tei.xml")).hexdigest())))
if __name__=="__main__":main()
