"""Exact fresh replay and twenty-eight retained-source challenges for volume VI."""
import argparse,json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from lxml import etree
from ocd_kernel.reconstruction.contract import SourceManifest,CandidatePackage
from build.tools.prepare_schaff_history_vol6_current import ROOT,BASE,canonical
from build.tei.schaff_history_vol6_current_oracle import check,_parse_xml
NS="{http://www.tei-c.org/ns/1.0}"
XML="{http://www.w3.org/XML/1998/namespace}"

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for n in ("candidate","replay","output"):parser.add_argument("--"+n,type=Path,required=True)
    args=parser.parse_args();a=CandidatePackage.load(args.candidate/"package");b=CandidatePackage.load(args.replay/"package")
    if a.sha256!=b.sha256 or any(a.member_bytes(n)!=b.member_bytes(n) for n in a.member_names) or (args.candidate/"validation.json").read_bytes()!=(args.replay/"validation.json").read_bytes():raise ValueError("fresh exact replay differs")
    m=SourceManifest.load(ROOT/BASE/"source-manifest.json",repository_root=ROOT);raw=a.member_bytes("content.tei.xml");baseline=check(m,raw);cases=[]
    names=("wording","chapter-omission","chapter-order","index-omission","duplication","note-attachment","literal-head","heading-class-omission","heading-class-change","heading-style-omission","heading-style-change","heading-style-invention","heading-class-invention","paragraph-style-omission","paragraph-style-change","span-style-omission","span-style-change","italic-style","note-number","scripture-target","unclear-reading","empty-index-carrier","ledger-attribute","ledger-parent","ledger-order","header-credit","prolog-comment","language")
    args.output.mkdir(parents=True,exist_ok=False)
    for name in names:
        tree=_parse_xml(raw,"mutation");doc=tree.getroot();body=doc.find(NS+"text/"+NS+"body");first=body[2];ledger=doc.find(NS+"standOff/"+NS+"list")
        p=next(n for n in first.iter(NS+"p") if n.text and n.text.strip());chapters=[n for n in first if n.get("subtype")=="Chapter"]
        title_heading=next(n for n in body.iter() if n.get(XML+"id")=="i-p0.11")
        paragraph_css=next(n for n in body.iter(NS+"p") if n.get("style"))
        span_css=next(n for n in body.iter(NS+"seg") if n.get("style"))
        if name=="wording":p.text="Invented text"
        elif name=="chapter-omission":first.remove(chapters[0])
        elif name=="chapter-order":first.remove(chapters[1]);first.insert(first.index(chapters[0]),chapters[1])
        elif name=="index-omission":body.remove(body[3])
        elif name=="duplication":p.addnext(deepcopy(p))
        elif name=="note-attachment":p.append(next(first.iter(NS+"note")))
        elif name=="literal-head":next(body.iter(NS+"head")).text="Normalized title"
        elif name=="heading-class-omission":del title_heading.attrib["rend"]
        elif name=="heading-class-change":title_heading.set("rend","invented")
        elif name=="heading-style-omission":del title_heading.attrib["ana"]
        elif name=="heading-style-change":title_heading.set("ana","source-css:text-indent:1in")
        elif name=="heading-style-invention":next(n for n in body.iter(NS+"head") if not n.get("ana")).set("ana","source-css:invented")
        elif name=="heading-class-invention":next(n for n in body.iter(NS+"head") if not n.get("rend")).set("rend","invented")
        elif name=="paragraph-style-omission":del paragraph_css.attrib["style"]
        elif name=="paragraph-style-change":paragraph_css.set("style","invented")
        elif name=="span-style-omission":del span_css.attrib["style"]
        elif name=="span-style-change":span_css.set("style","invented")
        elif name=="italic-style":next(first.iter(NS+"hi")).set("rend","bold")
        elif name=="note-number":next(first.iter(NS+"note")).set("n","99999")
        elif name=="scripture-target":next(n for n in first.iter(NS+"ref") if n.get("type")=="scripture-reference").set("target","Bible:Invented")
        elif name=="unclear-reading":next(first.iter(NS+"unclear")).text="Corrected reading"
        elif name=="empty-index-carrier":marker=next(first.iter(NS+"index"));marker.getparent().remove(marker)
        elif name in ("ledger-attribute","ledger-parent"):
            item=ledger[200];v=json.loads(item.text)
            if name=="ledger-attribute":v["source_attributes"].append(["invented","yes"])
            else:v["source_parent_key"]="hcc6-n000001"
            item.text=json.dumps(v)
        elif name=="ledger-order":ledger.insert(0,ledger[-1])
        elif name=="header-credit":doc.find(NS+"teiHeader").find('.//'+NS+"resp").text="Invented role"
        elif name=="prolog-comment":doc.getprevious().text="Invented rights"
        elif name=="language":next(n for n in first.iter() if n.get(XML+"lang")).set(XML+"lang","invented")
        altered=etree.tostring(tree,encoding="UTF-8",xml_declaration=True)
        (args.output/(name+".tei.xml")).write_bytes(altered)
        if altered==raw:raise ValueError("inert mutation "+name)
        try:check(m,altered)
        except (ValueError,etree.DocumentInvalid,etree.XMLSyntaxError) as e:
            cases.append(dict(name=name,status="rejected",reason=str(e),mutated_sha256=sha256(altered).hexdigest()));print("Rejected "+name+": "+str(e),flush=True)
        else:raise ValueError("accepted mutation "+name)
    (args.output/"result.json").write_bytes(canonical(dict(status="pass",baseline=baseline,cases=cases,candidate_sha256=a.sha256,replay_sha256=b.sha256,validation_equal=True,candidate_root=args.candidate.as_posix(),replay_root=args.replay.as_posix())))
if __name__=="__main__":main()
