"""Direct source/tree conservation audit without importing producer or oracle."""
from hashlib import sha256
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
NS = "{http://www.tei-c.org/ns/1.0}"
WORK = "donne-devotions-upon-emergent-occasions"
OUTPUT = ROOT / "reports/_logs/donne-reconciliation-20261001-v2"
CANDIDATE = Path("D:/Library/Open Christian Data/candidate-reviews/donne-devotions-20261001-g")


def fingerprint(n):
    return (n.tag, sorted(n.attrib.items()), n.text, n.tail, tuple(fingerprint(c) for c in n))


def main():
    source = (ROOT / "raw/gutenberg/pg23772.txt").read_bytes()
    lines = source.decode("utf8").split("\r\n")
    assert len(lines) == 7647 and "\r\n".join(lines).encode() == source
    old_raw = (ROOT / "reports/_logs/donne-reconciliation-20261001-v1/historical-package/content.tei.xml").read_bytes()
    old = ET.fromstring(old_raw)
    narrow = ET.parse(ROOT / "reports/_logs/donne-reconciliation-20261001-v1/scoped-candidate/package/content.tei.xml").getroot()
    raw = (CANDIDATE / "package/content.tei.xml").read_bytes()
    current = ET.fromstring(raw)
    numbers = list(range(1, 6491)) + list(range(7296, 7648))
    carriers = [n for n in current.find(NS + "text").iter(NS + "seg") if n.get("type") == "source-line"]
    assert len(carriers) == 6842 and [int(n.get("n")) for n in carriers] == numbers
    assert all("".join(n.itertext()) == lines[i - 1] for n, i in zip(carriers, numbers, strict=True))
    historical_sections = {int(n.get("n")): n for n in old.find(NS + "text/" + NS + "body/" + NS + "div")}
    sections = [s for part in current.find(NS + "text") for s in part[0]]
    assert len(sections) == 9
    for node in sections:
        assert fingerprint(node) == fingerprint(historical_sections[int(node.get("n"))])
    assert fingerprint(current.find(NS + "text/" + NS + "body")) == fingerprint(narrow.find(NS + "text/" + NS + "body"))
    life = next(n for n in sections if n.get("n") == "93")
    assert [lines[i - 1] for i in (84, 86, 88, 95, 1476)] == ["THE LIFE OF DR. JOHN DONNE     v", "DEVOTIONS                      1", "DEATH'S DUEL                 161", "(_Taken from the life by Izaak Walton_).", "I.W."]
    assert len(list(life.iter(NS + "lg"))) >= 11
    assert len([n for n in life.iter(NS + "seg") if "[Illustration]" in "".join(n.itertext())]) == 2
    assert len(list(life.iter(NS + "floatingText"))) == 2
    mirror = OUTPUT / "scoped-candidate"
    mirror.mkdir(parents=True, exist_ok=False)
    (mirror / "package").mkdir()
    digests = {}
    for p in sorted((CANDIDATE / "package").iterdir()):
        content = p.read_bytes()
        (mirror / "package" / p.name).write_bytes(content)
        digests[p.name] = sha256(content).hexdigest()
    validation = (CANDIDATE / "validation.json").read_bytes()
    (mirror / "validation.json").write_bytes(validation)
    (mirror / "mirror-provenance.json").write_text(json.dumps(dict(source=CANDIDATE.as_posix(), exact_member_hashes=digests, validation_sha256=sha256(validation).hexdigest()), indent=2) + "\n", encoding="utf8")
    receipt = dict(status="pass", source_sha256=sha256(source).hexdigest(), candidate_tei_sha256=sha256(raw).hexdigest(),
        source_carriers=7647, represented_carriers=6842, retained_only_sermon_carriers=805, source_ranges=[[1,6490],[7296,7647]],
        direct_native_sections=9, all_tags_attributes_text_tails_hierarchy_conserved=True, original_devotions_body_unchanged=True,
        walton_attribution="Taken from the life by Izaak Walton; I.W. closing; Contents page v", illustration_placeholders=2,
        embedded_documents=2, producer_oracle_imported=False, prior_exposure="Owner inspected historical route; no blind reviewer claim.")
    (OUTPUT / "direct-conservation.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf8")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
