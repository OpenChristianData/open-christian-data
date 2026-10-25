"""Challenge source-defined Hexaemeron fidelity with resealed changed payloads."""
from __future__ import annotations
import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
from lxml import etree
from build.tei.basil_hexaemeron_oracle import _oracle,TEI
from build.tei.basil_hexaemeron_reconstruction import canonical
from ocd_kernel.reconstruction.contract import SourceManifest,CandidatePackage

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate",type=Path,required=True); parser.add_argument("--output",type=Path,required=True); args=parser.parse_args()
    root=Path(__file__).resolve().parents[2]
    manifest=SourceManifest.load(root/"sources/manifest-acquisitions/basil-hexaemeron-npnf208/source-manifest.json",repository_root=root)
    package=CandidatePackage.load(args.candidate/"package"); baseline=_oracle(manifest,package)
    if baseline["status"]!="pass":raise ValueError(baseline["findings"])
    args.output.mkdir(parents=True,exist_ok=False); results=[]
    cases=["omit-paragraph","homily-order","invent-text","note-attachment","foreign-language","page-link","reference-target","neutral-column-role","work-boundary"]
    for name in cases:
        target=args.output/name; shutil.copytree(package.path,target)
        tree=etree.fromstring(package.member_bytes("content.tei.xml")); ns={"t":TEI}
        work=tree.find("{http://www.tei-c.org/ns/1.0}text/{http://www.tei-c.org/ns/1.0}body")[0]
        if name=="omit-paragraph":
            n=work.xpath(".//t:p",namespaces=ns)[0]; n.getparent().remove(n)
        elif name=="homily-order":
            n=work[3]; work.remove(n); work.insert(2,n)
        elif name=="invent-text":
            work.xpath(".//t:p",namespaces=ns)[0].text+=" invented"
        elif name=="note-attachment":
            n=work.xpath(".//t:note",namespaces=ns)[0]; n.getparent().remove(n); work[2].append(n)
        elif name=="foreign-language":work.xpath(".//t:foreign",namespaces=ns)[0].set("{http://www.w3.org/XML/1998/namespace}lang","la")
        elif name=="page-link":work.xpath(".//t:pb",namespaces=ns)[0].set("facs","wrong-page.html")
        elif name=="reference-target":work.xpath(".//t:ref[@type='scripture']",namespaces=ns)[0].set("target","Bible:Gen.1.1")
        elif name=="neutral-column-role":work.xpath(".//t:ref[@type='source-reference']",namespaces=ns)[0].set("type","scripture")
        elif name=="work-boundary":work.set("subtype","basil-of-caesarea-letters")
        raw=etree.tostring(tree,encoding="UTF-8",xml_declaration=True)
        if raw==package.member_bytes("content.tei.xml"):raise ValueError("mutation did not alter payload")
        (target/"content.tei.xml").write_bytes(raw)
        record=json.loads((target/"manifest.json").read_bytes())
        next(r for r in record["members"] if r["name"]=="content.tei.xml").update(bytes=len(raw),sha256=sha256(raw).hexdigest())
        (target/"manifest.json").write_bytes(canonical(record))
        result=_oracle(manifest,CandidatePackage.load(target))
        if result["status"]!="fail":raise ValueError("mutation accepted: "+name)
        results.append(dict(mutation=name,status="rejected",candidate_sha256=sha256(raw).hexdigest(),findings=result["findings"])); print(name+": rejected",flush=True)
    (args.output/"result.json").write_bytes(canonical(dict(status="pass",baseline=baseline,cases=results)))

if __name__=="__main__":main()
