"""Challenge source-defined Ludewic reply fidelity with resealed changed payloads."""
from __future__ import annotations
import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
from lxml import etree
from build.tei.ludewic_oracle import _oracle,TEI
from build.tei.ludewic_reconstruction import canonical
from ocd_kernel.reconstruction.contract import SourceManifest,CandidatePackage

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate",type=Path,required=True); parser.add_argument("--output",type=Path,required=True); args=parser.parse_args()
    root=Path(__file__).resolve().parents[2]
    manifest=SourceManifest.load(root/"sources/manifest-acquisitions/ludewic-bsb829/source-manifest.json",repository_root=root)
    package=CandidatePackage.load(args.candidate/"package"); baseline=_oracle(manifest,package)
    if baseline["status"]!="pass":raise ValueError(baseline["findings"])
    args.output.mkdir(parents=True,exist_ok=False); results=[]
    cases=["omit-line","inline-order","invent-text","word-link","style-rendition","page-marker","fill-empty-word","omit-full-closing","include-attribution-narrative","include-walram-neighbor"]
    for name in cases:
        target=args.output/name; shutil.copytree(package.path,target)
        tree=etree.fromstring(package.member_bytes("content.tei.xml")); ns={"t":TEI}
        work=tree.find("{http://www.tei-c.org/ns/1.0}text/{http://www.tei-c.org/ns/1.0}body")[0]
        ab=work[0]
        if name=="omit-line":
            n=ab.xpath("./t:lb",namespaces=ns)[5]; ab.remove(n)
        elif name=="inline-order":
            n=ab[8]; ab.remove(n); ab.insert(3,n)
        elif name=="invent-text":ab[0].tail=(ab[0].tail or "")+" invented"
        elif name=="word-link":ab.xpath(".//t:w",namespaces=ns)[0].set("corresp","#wrong-word")
        elif name=="style-rendition":ab.xpath(".//t:hi",namespaces=ns)[0].set("rend","BOLD")
        elif name=="page-marker":ab.xpath(".//t:pb",namespaces=ns)[0].set("n","999")
        elif name=="fill-empty-word":ab.xpath(".//t:w[@xml:id='w5041']",namespaces=ns)[0].text="thesauro"
        elif name=="omit-full-closing":ab.remove(ab[-1])
        elif name=="include-attribution-narrative":
            from copy import deepcopy
            source=etree.fromstring(manifest.authority_path("retained-source").read_bytes())
            carrier=source.find("{http://www.tei-c.org/ns/1.0}text/{http://www.tei-c.org/ns/1.0}body")[0][3][0]
            ab.append(deepcopy(carrier[90]))
        elif name=="include-walram-neighbor":
            from copy import deepcopy
            source=etree.fromstring(manifest.authority_path("retained-source").read_bytes())
            carrier=source.find("{http://www.tei-c.org/ns/1.0}text/{http://www.tei-c.org/ns/1.0}body")[0][3][0]
            ab.insert(0,deepcopy(carrier[15]))
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
