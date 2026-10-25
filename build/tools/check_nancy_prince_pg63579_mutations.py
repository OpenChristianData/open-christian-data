"""Exercise source-feature mutations against the independent PG63579 checker."""
from __future__ import annotations
import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
from lxml import etree

from build.tei.nancy_prince_pg63579_oracle import _oracle, TEI, XML_ID
from ocd_kernel.reconstruction.contract import SourceManifest, CandidatePackage


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    source = SourceManifest.load(root/"sources/manifest-acquisitions/nancy-prince-pg63579/source-manifest.json", repository_root=root)
    baseline = CandidatePackage.load(args.candidate / "package")
    baseline_result = _oracle(source, baseline)
    if baseline_result["status"] != "pass":
        raise ValueError(baseline_result["findings"])
    args.output.mkdir(parents=True, exist_ok=False)
    cases = ["omit-paragraph", "paragraph-order", "invent-text", "note-target", "poem-role", "contents-cell", "image-target", "raw-prefix-image-target", "appendix-boundary"]
    results = []
    for name in cases:
        path = args.output / name
        shutil.copytree(baseline.path, path)
        tree = etree.fromstring(baseline.member_bytes("content.tei.xml"))
        ns = {"t": TEI}
        if name == "omit-paragraph":
            n = tree.xpath(".//t:div[@xml:id='pg63579-narrative']//t:p", namespaces=ns)[0]
            n.getparent().remove(n)
        elif name == "paragraph-order":
            parent = tree.xpath(".//t:div[@xml:id='pg63579-narrative']", namespaces=ns)[0]
            a,b = parent[2], parent[3]
            parent.remove(b)
            parent.insert(parent.index(a),b)
        elif name == "invent-text":
            tree.xpath(".//t:div[@xml:id='pg63579-narrative']//t:p", namespaces=ns)[0].text += " invented"
        elif name == "note-target":
            tree.xpath(".//t:ref[@target='#Footnote_A_1']", namespaces=ns)[0].set("target", "#FNanchor_A_1")
        elif name == "poem-role":
            tree.xpath(".//t:lg[@type='stanza']", namespaces=ns)[0].set("type", "poem")
        elif name == "contents-cell":
            tree.xpath(".//t:table/t:row/t:cell", namespaces=ns)[0].text = "wrong contents"
        elif name == "image-target":
            tree.xpath(".//t:graphic", namespaces=ns)[0].set("url", "images/cover.jpg")
        elif name == "raw-prefix-image-target":
            tree.xpath(".//t:graphic", namespaces=ns)[0].set("url", "raw/gutenberg/63579/html/images/front.jpg")
        elif name == "appendix-boundary":
            units = tree.xpath("./t:text/t:body/t:div", namespaces=ns)
            moved = units[2][0]
            units[2].remove(moved)
            units[1].append(moved)
        payload = etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=False)
        if payload == baseline.member_bytes("content.tei.xml"):
            raise ValueError("mutation did not change claimed property: " + name)
        (path / "content.tei.xml").write_bytes(payload)
        manifest = json.loads((path / "manifest.json").read_bytes())
        member = next(m for m in manifest["members"] if m["name"] == "content.tei.xml")
        member.update(bytes=len(payload), sha256=sha256(payload).hexdigest())
        (path/"manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))+"\n", encoding="utf-8")
        result = _oracle(source, CandidatePackage.load(path))
        if result["status"] != "fail":
            raise ValueError("independent oracle accepted mutation: " + name)
        results.append(dict(mutation=name, status="rejected", candidate_sha256=sha256(payload).hexdigest(), findings=result["findings"]))
        print(name + ": rejected", flush=True)
    (args.output/"result.json").write_text(json.dumps(dict(status="pass", baseline=baseline_result, cases=results),ensure_ascii=False,sort_keys=True,indent=2)+"\n", encoding="utf-8")


if __name__ == "__main__":
    main()
