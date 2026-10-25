"""Challenge source-defined second Georgius epitaph fidelity with resealed changed payloads."""
from __future__ import annotations
import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
from lxml import etree
from build.tei.georgii_aliud_oracle import _oracle,TEI
from build.tei.georgii_aliud_reconstruction import canonical
from ocd_kernel.reconstruction.contract import SourceManifest,CandidatePackage

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate",type=Path,required=True); parser.add_argument("--output",type=Path,required=True); args=parser.parse_args()
    root=Path(__file__).resolve().parents[2]
    manifest=SourceManifest.load(root/"sources/manifest-acquisitions/georgii-aliud-bsb720/source-manifest.json",repository_root=root)
    package=CandidatePackage.load(args.candidate/"package"); baseline=_oracle(manifest,package)
    if baseline["status"]!="pass":raise ValueError(baseline["findings"])
    args.output.mkdir(parents=True,exist_ok=False); results=[]
    cases=["omit-verse-line","verse-order","invent-text","page-attribute","native-line-id","aliud-heading","include-first-poem","include-third-poem","include-numbered19"]
    for name in cases:
        target=args.output/name; shutil.copytree(package.path,target)
        tree=etree.fromstring(package.member_bytes("content.tei.xml")); ns={"t":TEI}
        work=tree.find("{http://www.tei-c.org/ns/1.0}text/{http://www.tei-c.org/ns/1.0}body")[0]
        ab=work[0]
        if name=="omit-verse-line":ab.remove(ab[1])
        elif name=="verse-order":
            n=ab[2]; ab.remove(n); ab.insert(1,n)
        elif name=="invent-text":ab[1].tail=(ab[1].tail or "")+" invented"
        elif name=="page-attribute":ab.xpath(".//t:pb",namespaces=ns)[0].set("n","999")
        elif name=="native-line-id":ab[1].set("{http://www.w3.org/XML/1998/namespace}id","wrong-line")
        elif name=="aliud-heading":ab[0].tail="TERTIUM\n"
        else:
            from copy import deepcopy
            source=etree.fromstring(manifest.authority_path("retained-source").read_bytes())
            carrier=source.find("{http://www.tei-c.org/ns/1.0}text/{http://www.tei-c.org/ns/1.0}body")[0][2][0]
            ab.append(deepcopy(carrier[{"include-first-poem":90,"include-third-poem":105,"include-numbered19":111}[name]]))
        raw=etree.tostring(tree,encoding="UTF-8",xml_declaration=True)
        if raw==package.member_bytes("content.tei.xml"):raise ValueError("mutation did not alter payload")
        (target/"content.tei.xml").write_bytes(raw)
        record=json.loads((target/"manifest.json").read_bytes())
        next(r for r in record["members"] if r["name"]=="content.tei.xml").update(bytes=len(raw),sha256=sha256(raw).hexdigest())
        (target/"manifest.json").write_bytes(canonical(record))
        result=_oracle(manifest,CandidatePackage.load(target))
        if result["status"]!="fail" or not any("mismatch" in f for f in result["findings"]):raise ValueError("mutation not rejected for intended source mismatch: "+name)
        results.append(dict(mutation=name,status="rejected",candidate_sha256=sha256(raw).hexdigest(),findings=result["findings"])); print(name+": rejected",flush=True)
    (args.output/"result.json").write_bytes(canonical(dict(status="pass",baseline=baseline,cases=results)))

if __name__=="__main__":main()
