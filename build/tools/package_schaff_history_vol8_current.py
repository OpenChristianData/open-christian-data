"""Whole HCC8 exact replay and meaningful source/evidence challenges."""
import argparse,json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from lxml import etree
from ocd_kernel.reconstruction.contract import SourceManifest,CandidatePackage
from build.tools.prepare_schaff_history_vol8_current import ROOT,BASE,canonical
from build.tei.schaff_history_vol8_current_oracle import check,_parse_xml
NS="{http://www.tei-c.org/ns/1.0}"
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for n in ("candidate","replay","output"):parser.add_argument("--"+n,type=Path,required=True)
    parser.add_argument("--resume",action="store_true")
    args=parser.parse_args();a=CandidatePackage.load(args.candidate/"package");b=CandidatePackage.load(args.replay/"package")
    if a.sha256!=b.sha256 or any(a.member_bytes(n)!=b.member_bytes(n) for n in a.member_names) or (args.candidate/"validation.json").read_bytes()!=(args.replay/"validation.json").read_bytes():raise ValueError("fresh exact replay differs")
    m=SourceManifest.load(ROOT/BASE/"source-manifest.json",repository_root=ROOT);raw=a.member_bytes("content.tei.xml");baseline=check(m,raw);cases=[]
    names=("wording","chapter-omission","chapter-order","index-omission","duplication","note-attachment","literal-head","heading-class","italic-style","note-number","scripture-target","index-generator-carrier","ledger-omission","ledger-order","ledger-attribute","ledger-parent","ledger-ordinal","ledger-target","ledger-duplicate-key","header-credit","prolog-comment","language","verse-type","verse-line","list-item","line-break","unclear-reading","unclear-omission","opaque-label-loss","opaque-label-change","opaque-invented-target")
    if args.resume:
        partial=json.loads((args.output/"partial-result.json").read_bytes())
        if partial["candidate_sha256"]!=a.sha256 or partial["replay_sha256"]!=b.sha256:raise ValueError("partial mutation binding differs")
        cases=partial["cases"]
        for c in cases:
            if c["status"]!="rejected" or sha256((args.output/(c["name"]+".tei.xml")).read_bytes()).hexdigest()!=c["mutated_sha256"]:raise ValueError("partial mutation evidence drifted")
    else:args.output.mkdir(parents=True,exist_ok=False)
    for name in names:
        if any(c["name"]==name for c in cases):continue
        tree=_parse_xml(raw,"mutation");doc=tree.getroot();body=doc.find(NS+"text/"+NS+"body");first=body[3];ps=list(first.iter(NS+"p"));p=next(n for n in ps if n.text and n.text.strip());chapters=[n for n in first if n.get("subtype")=="Chapter"];ledger=doc.find(NS+"standOff/"+NS+"list")
        if name=="wording":p.text="Invented text"
        elif name=="chapter-omission":first.remove(chapters[0])
        elif name=="chapter-order":first.remove(chapters[1]);first.insert(first.index(chapters[0]),chapters[1])
        elif name=="index-omission":body.remove(body[5])
        elif name=="duplication":p.addnext(deepcopy(p))
        elif name=="note-attachment":notes=list(first.iter(NS+"note"));notes[1].append(notes[0][0])
        elif name=="literal-head":next(body.iter(NS+"head")).text="Normalized title"
        elif name=="heading-class":next(n for n in body.iter(NS+"p") if (n.get("rend") or "").startswith("MsoHeading")).set("rend","invented")
        elif name=="italic-style":next(first.iter(NS+"hi")).set("rend","bold")
        elif name=="note-number":next(first.iter(NS+"note")).set("n","99999")
        elif name=="scripture-target":next(n for n in first.iter(NS+"ref") if n.get("type")=="scripture-reference").set("target","Bible:Invented")
        elif name=="unclear-reading":next(n for n in first.iter(NS+"unclear")).text="Corrected reading"
        elif name=="index-generator-carrier":next(body.iter(NS+"anchor")).getparent().remove(next(body.iter(NS+"anchor")))
        elif name=="ledger-omission":ledger.remove(ledger[-1])
        elif name=="ledger-order":ledger.insert(0,ledger[-1])
        elif name in ("ledger-attribute","ledger-parent","ledger-ordinal"):
            item=ledger[200];v=json.loads(item.text)
            if name=="ledger-attribute":v["source_attributes"].append(["invented","yes"])
            elif name=="ledger-parent":v["source_parent_key"]="hcc8-n000001"
            else:v["source_ordinal"]=999
            item.text=json.dumps(v)
        elif name=="ledger-target":ledger[200].set("corresp","#invented")
        elif name=="ledger-duplicate-key":ledger[200].text=ledger[200].text[:-1]+',"source_ordinal":999}'
        elif name=="header-credit":doc.find(NS+"teiHeader").find('.//'+NS+"resp").text="Invented role"
        elif name=="bold-style":next(n for n in first.iter(NS+"hi") if n.get("rend")=="bold").set("rend","italic")
        elif name=="language":next(n for n in first.iter() if n.get("{http://www.w3.org/XML/1998/namespace}lang")).set("{http://www.w3.org/XML/1998/namespace}lang","invented")
        elif name=="verse-type":next(first.iter(NS+"lg")).set("type","invented")
        elif name=="verse-line":next(first.iter(NS+"l")).text="Invented line"
        elif name=="list-item":next(body.iter(NS+"item")).getparent().remove(next(body.iter(NS+"item")))
        elif name=="line-break":next(first.iter(NS+"lb")).getparent().remove(next(first.iter(NS+"lb")))
        elif name=="unclear-reading":next(first.iter(NS+"unclear")).text="Corrected reading"
        elif name=="unclear-omission":next(first.iter(NS+"unclear")).getparent().remove(next(first.iter(NS+"unclear")))
        elif name=="opaque-label-loss":next(n for n in first.iter(NS+"ref") if n.get("type")=="ThML-scripRef-opaque").attrib.pop("n")
        elif name=="opaque-label-change":next(n for n in first.iter(NS+"ref") if n.get("type")=="ThML-scripRef-opaque").set("n","John 17:12")
        elif name=="opaque-invented-target":next(n for n in first.iter(NS+"ref") if n.get("type")=="ThML-scripRef-opaque").set("target","https://example.invalid/inferred")
        elif name=="prolog-comment":doc.getprevious().text="Invented rights"
        altered=etree.tostring(tree,encoding="UTF-8",xml_declaration=True)
        (args.output/(name+".tei.xml")).write_bytes(altered)
        if altered==raw:raise ValueError("inert mutation "+name)
        try:check(m,altered)
        except (ValueError,etree.DocumentInvalid,etree.XMLSyntaxError) as e:cases.append(dict(name=name,status="rejected",reason=str(e),mutated_sha256=sha256(altered).hexdigest()));print("Rejected "+name+": "+str(e),flush=True)
        else:raise ValueError("accepted mutation "+name)
        (args.output/"partial-result.json").write_bytes(canonical(dict(candidate_sha256=a.sha256,replay_sha256=b.sha256,cases=cases)))
    if len(cases)!=len(names):raise ValueError("mutation case coverage differs")
    (args.output/"result.json").write_bytes(canonical(dict(status="pass",baseline=baseline,cases=cases,candidate_sha256=a.sha256,replay_sha256=b.sha256,validation_equal=True,candidate_root=args.candidate.as_posix(),replay_root=args.replay.as_posix())))
if __name__=="__main__":main()
