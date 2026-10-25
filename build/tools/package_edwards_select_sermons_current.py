"""Challenge complete Select Sermons native source conservation and exact replay."""
import argparse,json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from lxml import etree
from ocd_kernel.reconstruction.contract import SourceManifest,CandidatePackage
from build.tools.prepare_edwards_select_sermons_current import ROOT,BASE,canonical
from build.tei.edwards_select_sermons_current_oracle import check,_parse_xml
NS="{http://www.tei-c.org/ns/1.0}"
XML_ID="{http://www.w3.org/XML/1998/namespace}id"

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("candidate","replay","output"):parser.add_argument("--"+name,type=Path,required=True)
    args=parser.parse_args();a=CandidatePackage.load(args.candidate/"package");b=CandidatePackage.load(args.replay/"package")
    if a.sha256!=b.sha256 or any(a.member_bytes(n)!=b.member_bytes(n) for n in a.member_names) or (args.candidate/"validation.json").read_bytes()!=(args.replay/"validation.json").read_bytes():raise ValueError("fresh-process exact replay differs")
    manifest=SourceManifest.load(ROOT/BASE/"source-manifest.json",repository_root=ROOT);raw=a.member_bytes("content.tei.xml");baseline=check(manifest,raw);cases=[]
    names=("wording","sermon-omission","sermon-order","index-omission","duplication","note-attachment","head-label","head-type","italic-style","bold-style","note-number","scripture-target","audio-target","icon-target","icon-alt","icon-omission","marker-label","marker-type","anchor-label","index-link","list-order","list-item","linebreak","language","css-style","ledger-omission","ledger-order","ledger-attribute","ledger-parent","ledger-ordinal","header-credit","prolog-comment")
    args.output.mkdir(parents=True,exist_ok=False)
    for name in names:
        tree=_parse_xml(raw,"mutation");doc=tree.getroot();body=doc.find(NS+"text/"+NS+"body");ledger=doc.find(NS+"standOff/"+NS+"list")
        def find(tag,predicate=lambda n:True):return next(n for n in body.iter(NS+tag) if predicate(n))
        p=find("p",lambda n:n.text and n.text.strip());icon=find("graphic");marker=find("anchor",lambda n:n.get("type")=="ThML-scripCom")
        if name=="wording":p.text="Invented wording"
        elif name=="sermon-omission":body.remove(body[1])
        elif name=="sermon-order":body.insert(1,body[2])
        elif name=="index-omission":body.remove(body[-1])
        elif name=="duplication":p.addnext(deepcopy(p))
        elif name=="note-attachment":find("p",lambda n:n is not p).append(find("note"))
        elif name=="head-label":find("head").text="Invented heading"
        elif name=="head-type":find("head").set("type","source-h6")
        elif name=="italic-style":find("hi",lambda n:n.get("rend")=="italic").set("rend","bold")
        elif name=="bold-style":find("hi",lambda n:n.get("rend")=="bold").set("rend","italic")
        elif name=="note-number":find("note").set("n","999")
        elif name=="scripture-target":find("ref",lambda n:n.get("type")=="scripture-reference").set("target","Bible:Invented")
        elif name=="audio-target":find("ref",lambda n:(n.get("target") or "").endswith(".mp3")).set("target","https://example.invalid/audio.mp3")
        elif name=="icon-target":icon.set("url","https://example.invalid/icon.png")
        elif name=="icon-alt":icon.set("n","invented")
        elif name=="icon-omission":icon.getparent().remove(icon)
        elif name=="marker-label":marker.set("n","Invented passage")
        elif name=="marker-type":marker.set("subtype","Invented")
        elif name=="anchor-label":find("ref",lambda n:n.get("type")=="ThML-anchor" and n.text).text="Invented label"
        elif name=="index-link":next(body[-1].iter(NS+"ref")).set("target","#invented-target")
        elif name=="list-order":ls=find("list",lambda n:n.get("type")=="ordered");ls.insert(0,ls[1])
        elif name=="list-item":n=find("item");n.getparent().remove(n)
        elif name=="linebreak":n=find("lb");n.getparent().remove(n)
        elif name=="language":next(n for n in body.iter() if n.get("{http://www.w3.org/XML/1998/namespace}lang")).set("{http://www.w3.org/XML/1998/namespace}lang","grc")
        elif name=="css-style":find("p",lambda n:"margin" in (n.get("rend") or "")).set("rend","margin:0")
        elif name=="ledger-omission":ledger.remove(ledger[-1])
        elif name=="ledger-order":ledger.insert(0,ledger[-1])
        elif name in ("ledger-attribute","ledger-parent","ledger-ordinal"):
            item=next(n for n in ledger if json.loads(n.text)["source_element"]=="scripCom");value=json.loads(item.text)
            if name=="ledger-attribute":value["source_attributes"]= [[k,"Bible:Invented" if k=="osisRef" else v] for k,v in value["source_attributes"]]
            elif name=="ledger-parent":value["source_parent_key"]="edwards-select-sermons-n000001"
            else:value["source_ordinal"]=999
            item.text=json.dumps(value)
        elif name=="header-credit":doc.find(NS+"teiHeader").find('.//'+NS+"resp").text="Invented role"
        elif name=="prolog-comment":doc.getprevious().text="Invented rights"
        altered=etree.tostring(tree,encoding="UTF-8",xml_declaration=True);(args.output/(name+".tei.xml")).write_bytes(altered)
        if altered==raw:raise ValueError("inert mutation "+name)
        try:check(manifest,altered)
        except (ValueError,etree.DocumentInvalid,etree.XMLSyntaxError) as exc:
            cases.append(dict(name=name,status="rejected",reason=str(exc),mutated_sha256=sha256(altered).hexdigest()));print("Rejected "+name+": "+str(exc),flush=True)
        else:raise ValueError("mutation escaped "+name)
        (args.output/"partial-result.json").write_bytes(canonical(dict(candidate_sha256=a.sha256,replay_sha256=b.sha256,cases=cases)))
    if len(cases)!=32:raise ValueError("mutation coverage differs")
    (args.output/"result.json").write_bytes(canonical(dict(status="pass",baseline=baseline,cases=cases,candidate_sha256=a.sha256,replay_sha256=b.sha256,validation_equal=True,candidate_root=args.candidate.as_posix(),replay_root=args.replay.as_posix())))

if __name__=="__main__":main()
