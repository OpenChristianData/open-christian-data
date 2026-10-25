"""Run a fresh process candidate reconstruction and independent validation."""
import argparse
from pathlib import Path
import json
from build.tools.prepare_first_corinthians_collection import ROOT,BASE,canonical
from build.tei.first_corinthians_collection_reconstruction import _convert
from build.tei.first_corinthians_collection_oracle import _oracle
from ocd_kernel.reconstruction import SourceManifest,reconstruct,validate
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError(a.output)
    a.output.mkdir(parents=True)
    manifest=SourceManifest.load(ROOT/BASE/'source-manifest.json',repository_root=ROOT)
    candidate=reconstruct(manifest,a.output/'package',_convert)
    report=validate(manifest,candidate,_oracle)
    (a.output/'validation.json').write_bytes(canonical(dict(report.attestation)))
    print(json.dumps(dict(status=report.status,candidate_sha256=candidate.sha256,output=a.output.as_posix())))
    if report.status!='pass':raise ValueError(dict(report.attestation))
if __name__=='__main__':main()
