"""Independent exact-source check for the held N18328 electronic candidate."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "raw/tcp/high-range/N18328/N18328.xml"
CANDIDATE = ROOT / "library/works/convicts-visitor/integration/convicts-n18328-electronic-v1/candidate.tei.xml"
SOURCE_SHA = "2f5d266ebf91471784de4a7f95cd47ac3fd806b908a1589d97f47c10a1069871"
NS = "{http://www.tei-c.org/ns/1.0}"
REVISION = "convicts-n18328-electronic-agent-v1"
IDENTITY = {
    "work_id": "convicts-visitor",
    "textual_form_id": "convicts-visitor-tcp-retained",
    "edition_id": "convicts-visitor-tcp-electronic",
    "acquisition_id": "convicts-visitor-tcp-acquired",
}


def _compare(source: ET.Element, candidate: ET.Element, location: str) -> None:
    """Compare every source node, attribute, text, tail, and child position."""
    if source.tag != candidate.tag:
        raise ValueError(f"source element differs at {location}")
    if source.attrib != candidate.attrib:
        raise ValueError(f"source attributes differ at {location}")
    if source.text != candidate.text or source.tail != candidate.tail:
        raise ValueError(f"source text/order differs at {location}")
    if len(source) != len(candidate):
        raise ValueError(f"source child count differs at {location}")
    for position, (left, right) in enumerate(zip(source, candidate), 1):
        _compare(left, right, f"{location}/{left.tag.removeprefix(NS)}[{position}]")


def check_candidate_bytes(source_bytes: bytes, candidate_bytes: bytes) -> dict[str, object]:
    if len(source_bytes) != 140639 or sha256(source_bytes).hexdigest() != SOURCE_SHA:
        raise ValueError("retained N18328 source bytes differ")
    if b"</teiHeader>" not in source_bytes or b"</teiHeader>" not in candidate_bytes:
        raise ValueError("TEI header boundary absent")
    source = ET.fromstring(source_bytes)
    candidate = ET.fromstring(candidate_bytes)
    if source.tag != NS + "TEI" or candidate.tag != source.tag:
        raise ValueError("single TEI root required")
    source_texts = source.findall(NS + "text")
    candidate_texts = candidate.findall(NS + "text")
    if len(source_texts) != 1 or len(candidate_texts) != 1:
        raise ValueError("one complete source text required")
    source_text, candidate_text = source_texts[0], candidate_texts[0]
    if [child.tag for child in source_text] != [NS + "front", NS + "body"]:
        raise ValueError("source front/body boundary differs")
    body = source_text.find(NS + "body")
    if body is None or len(body) != 1 or body[0].tag != NS + "div" or body[0].get("type") != "text":
        raise ValueError("source whole-work body boundary differs")
    _compare(source_text, candidate_text, "TEI/text")
    if source_bytes.split(b"</teiHeader>", 1)[1] != candidate_bytes.split(b"</teiHeader>", 1)[1]:
        raise ValueError("source text bytes after header differ")

    header = candidate.find(NS + "teiHeader")
    if header is None:
        raise ValueError("candidate TEI header absent")
    values = {node.get("type"): node.text for node in header.iter(NS + "idno")
              if node.get("type") in IDENTITY or node.get("type") in {"source_sha256", "source_bytes", "sha256", "representation_revision"}}
    expected = IDENTITY | {"source_sha256": SOURCE_SHA, "source_bytes": str(len(source_bytes)),
                           "sha256": SOURCE_SHA, "representation_revision": REVISION}
    if any(values.get(key) != value for key, value in expected.items()):
        raise ValueError("candidate header identity/source binding differs")
    changes = [node for node in header.iter(NS + "change") if node.get("{http://www.w3.org/XML/1998/namespace}id") == REVISION]
    if len(changes) != 1:
        raise ValueError("candidate revision binding differs")
    source_header = source.find(NS + "teiHeader")
    if source_header is None:
        raise ValueError("source header absent")
    # The original header remains readable. Remove only the two identified
    # binding additions and compare every surviving source header node.
    source_desc = header.find(NS + "fileDesc/" + NS + "sourceDesc")
    revision_desc = header.find(NS + "revisionDesc")
    if source_desc is None or revision_desc is None:
        raise ValueError("candidate header structure differs")
    bindings = [node for node in source_desc if node.tag == NS + "bibl"
                and any(item.get("type") == "work_id" and item.text == IDENTITY["work_id"]
                        for item in node.iter(NS + "idno"))]
    if len(bindings) != 1:
        raise ValueError("candidate source binding count differs")
    source_desc.remove(bindings[0])
    revision_desc.remove(changes[0])
    _compare(source_header, header, "TEI/teiHeader")

    names = Counter(element.tag.removeprefix(NS) for element in source_text.iter())
    if any(names[name] != count for name, count in {
        "pb": 89, "g": 387, "sp": 115, "speaker": 115,
        "lg": 7, "l": 28, "note": 1, "div": 43,
    }.items()):
        raise ValueError("source feature inventory differs")
    return {
        "status": "pass",
        "scope": "complete retained N18328 electronic XML member",
        "source_sha256": SOURCE_SHA,
        "candidate_sha256": sha256(candidate_bytes).hexdigest(),
        "source_text_sha256": sha256(ET.tostring(source_text, encoding="utf-8")).hexdigest(),
        "source_text_elements": sum(names.values()),
        "source_feature_counts": dict(sorted(names.items())),
        "comparison": "All text and header source nodes, attributes, text, tails, and order match; source text suffix bytes match.",
    }


def main() -> None:
    result = check_candidate_bytes(SOURCE.read_bytes(), CANDIDATE.read_bytes())
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
