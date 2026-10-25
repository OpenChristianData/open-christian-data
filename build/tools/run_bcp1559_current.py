"""Fresh-process complete BCP1559 native candidate and independent validation."""
import argparse,json,os
from pathlib import Path
from hashlib import sha256
from ocd_kernel.reconstruction.contract import SourceManifest,reconstruct,validate
from build.tei.bcp1559_current_reconstruction import _convert
from build.tei.bcp1559_current_oracle import _oracle
from build.tools.prepare_bcp1559_current import ROOT,BASE,canonical


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
 args.output.mkdir(parents=True,exist_ok=False)
 manifest=SourceManifest.load(ROOT/BASE/'source-manifest.json',repository_root=ROOT)
 package=reconstruct(manifest,args.output/'package',_convert)
 result=validate(manifest,package,_oracle)
 (args.output/'validation.json').write_bytes(canonical(dict(contract='ocd-validation-report-v1',status=result.status,candidate_sha256=result.candidate_sha256,source_manifest_sha256=result.source_manifest_sha256,attestation=dict(result.attestation),findings=list(result.findings))))
 if result.status!='pass':raise ValueError(result.findings)
 (args.output/'process.json').write_bytes(canonical(dict(pid=os.getpid(),exit_code=0,candidate_sha256=package.sha256,tei_sha256=sha256(package.member_bytes('content.tei.xml')).hexdigest())))
 print(json.dumps(dict(status='pass',candidate_sha256=package.sha256,tei_sha256=sha256(package.member_bytes('content.tei.xml')).hexdigest())))


if __name__=='__main__':main()
