"""Challenge the scoped Donne proof and retain exact replay evidence."""
from __future__ import annotations
import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
from build.tools.prepare_donne_devotions import ROOT, BASE, canonical
from build.tei.donne_devotions_scoped_oracle import check
from ocd_kernel.reconstruction.contract import SourceManifest, CandidatePackage

NS = "{http://www.tei-c.org/ns/1.0}"


def challenge(manifest, raw):
    baseline = check(manifest, raw)
    cases = []
    for name in ("wording", "omission", "duplication", "order", "movement-attachment", "movement-flattening",
                 "note-target", "source-underscore", "dedication-role", "license-omission",
                 "walton-attribution", "front-verse-flattening", "front-placeholder", "embedded-document-role"):
        doc = etree.fromstring(raw)
        line = next(n for n in doc.iter(NS + "seg") if n.get("n") == "1620")
        if name == "wording":
            line.text = "Invented opening"
        elif name == "omission":
            line.getparent().remove(line)
        elif name == "duplication":
            line.addnext(deepcopy(line))
        elif name == "order":
            following = line.getnext()
            line.getparent().remove(following)
            line.addprevious(following)
        elif name == "movement-attachment":
            movement = next(n for n in doc.iter(NS + "div") if n.get("type") == "prayer")
            next(n for n in doc.iter(NS + "div") if n.get("type") == "station" and n.get("n") == "1747").append(movement)
        elif name == "movement-flattening":
            next(n for n in doc.iter(NS + "div") if n.get("type") == "meditation").tag = NS + "ab"
        elif name == "note-target":
            ref = next(n for n in doc.iter(NS + "ref") if n.get("target", "").endswith("footnote-1"))
            ref.set("target", ref.get("target")[:-1] + "2")
        elif name == "source-underscore":
            hi = next(n for n in doc.iter(NS + "hi") if n.get("rend") == "source-underscore")
            hi.set("rend", "italic")
        elif name == "dedication-role":
            dedication = next(n for n in doc.iter(NS + "div") if n.get("n") == "1508")
            next(dedication.iter(NS + "signed")).tag = NS + "p"
        elif name == "license-omission":
            back = doc.find(NS + "text/" + NS + "back")
            back.remove(back[0])
        elif name == "walton-attribution":
            next(n for n in doc.iter(NS + "seg") if n.get("n") == "95").clear()
        elif name == "front-verse-flattening":
            next(doc.find(NS + "text/" + NS + "front").iter(NS + "lg")).tag = NS + "p"
        elif name == "front-placeholder":
            placeholder = next(n for n in doc.iter(NS + "seg") if "[Illustration" in "".join(n.itertext()))
            placeholder.clear()
        elif name == "embedded-document-role":
            next(doc.find(NS + "text/" + NS + "front").iter(NS + "floatingText")).set("type", "letter")
        altered = etree.tostring(doc, encoding="UTF-8", xml_declaration=True)
        if altered == raw:
            raise ValueError("mutation did not change candidate")
        try:
            check(manifest, altered)
        except (ValueError, etree.DocumentInvalid) as error:
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
