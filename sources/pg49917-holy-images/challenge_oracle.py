"""Challenge the bound Holy Images oracle without changing the sealed candidate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from lxml import etree

from build.tei.pg49917_holy_images_oracle import _oracle
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest


TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


class MutatedCandidate:
    """Present one synthetic changed member to the source oracle."""

    def __init__(self, sealed: CandidatePackage, xml: bytes) -> None:
        self.sealed = sealed
        self.xml = xml
        self.manifest = sealed.manifest
        self.sha256 = sealed.sha256

    def verify_integrity(self) -> None:
        self.sealed.verify_integrity()

    def member_bytes(self, name: str) -> bytes:
        return self.xml if name == "content.tei.xml" else self.sealed.member_bytes(name)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate", type=Path)
    options = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    manifest = SourceManifest.load(root / "sources/pg49917-holy-images/source-manifest.json", repository_root=root)
    candidate = CandidatePackage.load(options.candidate / "package")
    baseline = _oracle(manifest, candidate)
    if baseline["status"] != "pass":
        raise ValueError("baseline oracle failed")
    original = candidate.member_bytes("content.tei.xml")
    results: list[dict[str, str]] = []
    for name in ("change-source-word", "drop-index-note", "misattach-forward-note", "drop-page-marker"):
        tree = etree.fromstring(original)
        ns = {"t": TEI}
        if name == "change-source-word":
            elements = tree.xpath(".//t:seg[contains(text(),'Adoration is a token')]", namespaces=ns)
            if len(elements) != 1:
                raise ValueError("source word challenge locus changed")
            elements[0].text = elements[0].text.replace("Adoration is a token", "Adoration was a token", 1)
        elif name == "drop-index-note":
            elements = tree.xpath(".//t:table[@xml:id='id64']", namespaces={**ns, "xml": "http://www.w3.org/XML/1998/namespace"})
            if len(elements) != 1:
                raise ValueError("index note challenge locus changed")
            elements[0].getparent().remove(elements[0])
        elif name == "misattach-forward-note":
            elements = tree.xpath("./t:text/t:body//t:ref", namespaces=ns)
            if not elements or elements[0].get("target") != "#id52":
                raise ValueError("note attachment challenge locus changed")
            elements[0].set("target", "#id53")
        else:
            elements = tree.xpath(".//t:seg[@xml:id='page-1']", namespaces={**ns, "xml": "http://www.w3.org/XML/1998/namespace"})
            if len(elements) != 1 or elements[0].get(XML_ID) != "page-1":
                raise ValueError("page marker challenge locus changed")
            elements[0].getparent().remove(elements[0])
        changed = etree.tostring(tree, encoding="UTF-8", xml_declaration=True)
        if changed == original:
            raise ValueError(f"{name} did not change candidate bytes")
        try:
            _oracle(manifest, MutatedCandidate(candidate, changed))  # type: ignore[arg-type]
        except ValueError as exc:
            results.append({"mutation": name, "result": "rejected", "reason": str(exc)})
        else:
            raise ValueError(f"{name} escaped the oracle")
    print(json.dumps({"baseline": "pass", "candidate_sha256": candidate.sha256, "mutations": results}, sort_keys=True))


if __name__ == "__main__":
    main()
