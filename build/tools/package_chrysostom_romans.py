"""Challenge the complete Romans proof and retain exact replay evidence."""
from __future__ import annotations
import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
from build.tools.prepare_chrysostom_romans import ROOT, BASE, canonical
from build.tei.chrysostom_romans_oracle import check
from ocd_kernel.reconstruction.contract import SourceManifest, CandidatePackage

NS = "{http://www.tei-c.org/ns/1.0}"


def challenge(manifest, raw):
    baseline = check(manifest, raw)
    cases = []
    for name in ("wording","omission","duplication","order","homily-attachment","homily-flattening","literal-head","source-class","greek-language","italic-id","note-number","scripture-target","root-tail","header-credit"):
        doc = etree.fromstring(raw)
        selected = doc.find(NS+"text/"+NS+"body")[0][0]
        p = next(n for n in selected.iter(NS+"p") if n.text and n.text.strip())
        homilies = [n for n in selected if n.tag==NS+"div"][2:]
        if name=="wording": p.text="Invented opening"
        elif name=="omission": p.getparent().remove(p)
        elif name=="duplication": p.addnext(deepcopy(p))
        elif name=="order":
            selected.remove(homilies[1]);selected.insert(selected.index(homilies[0]),homilies[1])
        elif name=="homily-attachment": homilies[1].append(next(homilies[0].iter(NS+"p")))
        elif name=="homily-flattening": homilies[0].tag=NS+"ab"
        elif name=="literal-head": selected[0].text="Normalized title"
        elif name=="source-class": next(n for n in selected.iter(NS+"seg") if n.get("rend")).set("rend","normalized")
        elif name=="greek-language": next(n for n in selected.iter() if n.get("{http://www.w3.org/XML/1998/namespace}lang")).set("{http://www.w3.org/XML/1998/namespace}lang","en")
        elif name=="italic-id": next(selected.iter(NS+"hi")).set("{http://www.w3.org/XML/1998/namespace}id","invented-italic")
        elif name=="note-number": next(selected.iter(NS+"note")).set("n","99999")
        elif name=="scripture-target": next(selected.iter(NS+"ref")).set("target","Bible:Invented")
        elif name=="root-tail": selected.tail="Invented tail"
        elif name=="header-credit": doc.find(NS+"teiHeader").find('.//'+NS+"name").text="Invented translator"
        altered = etree.tostring(doc, encoding="UTF-8", xml_declaration=True)
        if altered == raw:
            raise ValueError("mutation did not change candidate")
        try:
            check(manifest, altered)
        except (ValueError, etree.DocumentInvalid, etree.XMLSyntaxError) as error:
            cases.append(dict(name=name, status="rejected", reason=str(error), mutated_sha256=sha256(altered).hexdigest()))
            print("Rejected " + name + ": " + str(error), flush=True)
        else:
            raise ValueError("oracle accepted mutation: " + name)
    return dict(status="pass", baseline=baseline, cases=cases)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--replay", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    a = CandidatePackage.load(args.candidate / "package")
    b = CandidatePackage.load(args.replay / "package")
    if a.sha256 != b.sha256 or any(a.member_bytes(n) != b.member_bytes(n) for n in a.member_names):
        raise ValueError("clean-process six-member replay differs")
    if (args.candidate / "validation.json").read_bytes() != (args.replay / "validation.json").read_bytes():
        raise ValueError("clean-process validation bytes differ")
    manifest = SourceManifest.load(ROOT / BASE / "source-manifest.json", repository_root=ROOT)
    proof = challenge(manifest, a.member_bytes("content.tei.xml"))
    proof.update(candidate_sha256=a.sha256, replay_sha256=b.sha256, validation_equal=True,
                 candidate_root=args.candidate.as_posix(), replay_root=args.replay.as_posix())
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "result.json").write_bytes(canonical(proof))
    print(json.dumps(dict(status="pass", cases=len(proof["cases"]), candidate_sha256=a.sha256)))


if __name__ == "__main__":
    main()
