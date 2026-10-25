"""Direct retained-source comparison of Green note/image relationships."""

import hashlib
import json
from pathlib import Path

from lxml import etree


def main():
    root = Path(__file__).resolve().parents[2]
    log = root / "reports/_logs/green-current-reconciliation-20261002-v1"
    path = root / "library/works/elisha-w-green-life-1888/integration/green-current-v3/candidate.tei.xml"
    raw = (root / "raw/docsouth/l763-greenew-exact-1888/greenew.xml").read_bytes()
    source = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, no_network=True))
    current = etree.fromstring(path.read_bytes())
    t = "{http://www.tei-c.org/ns/1.0}"
    x = "{http://www.w3.org/XML/1998/namespace}id"
    text = current.find(t + "text")
    ids = {}
    for node in text.iter():
        if x in node.attrib:
            if node.get(x) in ids:
                raise ValueError("Duplicate native ID")
            ids[node.get(x)] = node
    records = []
    for local, field in (("ref", "target"), ("note", "corresp")):
        original = list(source.find("text").iter(local))
        actual = list(text.iter(t + local))
        if len(original) != 12 or len(actual) != 12:
            raise ValueError("Exact note/ref count differs")
        for position, (a, b) in enumerate(zip(original, actual), 1):
            if b.get(x) != a.get("id") or b.get(field) != "#" + a.get("target") or b.get(field)[1:] not in ids:
                raise ValueError("Wrong source-native note/ref linkage")
            target = ids[b.get(field)[1:]]
            if target.tag != t + ("note" if local == "ref" else "ref"):
                raise ValueError("Wrong paired role")
            records.append({"role": local, "position": position, "source_id": a.get("id"), "source_target": a.get("target"), "tei_field": field, "tei_target": b.get(field)})
    figures = []
    originals = list(source.find("text").iter("figure"))
    actuals = list(text.iter(t + "figure"))
    if len(originals) != 3 or len(actuals) != 3:
        raise ValueError("Exact image count differs")
    for a, b in zip(originals, actuals):
        graphic = b.find(t + "graphic")
        expected = "https://docsouth.unc.edu/neh/greenew/" + a.get("entity") + ".jpg"
        if graphic is None or graphic.get(x) != a.get("id") or graphic.get("n") != a.get("entity") or graphic.get("url") != expected:
            raise ValueError("Source-declared image linkage differs")
        figures.append({"source_id": a.get("id"), "tei_id_carrier": "graphic", "entity": a.get("entity"), "url": expected, "retained_binary": False})
    proof = {"status": "pass", "method": "Direct lxml retained P4 source vs current TEI link comparison, no producer/oracle imports", "source_sha256": hashlib.sha256(raw).hexdigest(), "candidate_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "closed_links": records, "unretained_graphics": figures, "qualification": "Fragment prefix normalization and source-figure ID relocation to graphic follow the historical P5 mapping; only note target-to-corresp field alias changes current linkage. Image URL derivation is source entity filename plus acquired URL base, not downloaded/image-content verification.", "prior_probe_qualification": "Initial in-memory diagnostic incorrectly expected historical figure ID on figure rather than its graphic carrier; it stopped before producing evidence. Current check explicitly verifies the historical carrier relocation, without any candidate/source change."}
    destination = log / "source-relationship-review.json"
    output = (json.dumps(proof, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if destination.exists() and destination.read_bytes() != output:
        raise FileExistsError("Frozen relationship receipt differs")
    destination.write_bytes(output)
    print(json.dumps({"status": "pass", "source_links": len(records), "graphics": len(figures)}))


if __name__ == "__main__":
    main()
