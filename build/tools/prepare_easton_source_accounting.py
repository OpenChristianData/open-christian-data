"""Bind the retained Easton JSONL lines to the unchanged native lexical TEI."""

from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "raw/bible_dictionaries/eastons.jsonl"
MASTER = ROOT / "library/works/eastons-bible-dictionary/integration/easton-current-v1/candidate.tei.xml"
OUT = MASTER.parent
ACQUISITION = ROOT / "library/works/eastons-bible-dictionary/forms/eastons-bible-dictionary-retained-electronic/editions/eastons-bible-dictionary-retained-electronic-witness/acquisitions/eastons-bible-dictionary-retained-source.json"
HISTORICAL = Path("D:/Library/Open Christian Data/candidate-reviews/jwbickel-dictionaries-20260928-v1/eastons-bible-dictionary/package/source-accountability.json")
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
SOURCE_SHA = "978e09fdb66e9c6b722085f868c0cc84030df9e15c6188a06390f3822888082a"
MASTER_SHA = "d3095b72265507523bbb1d83bd8d3aecb82efb2f68ec352bfd9b3bc3128c6bba"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: dict) -> None:
    payload = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    with path.open("xb") as stream:
        stream.write(payload)


def unique_object(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSONL field: {key}")
        result[key] = value
    return result


def main() -> None:
    if digest(SOURCE) != SOURCE_SHA or digest(MASTER) != MASTER_SHA:
        raise ValueError("Easton retained source or prepared native TEI drifted")
    acquisition = json.loads(ACQUISITION.read_text(encoding="utf-8"))
    scope = acquisition["source_scope"]
    root = ET.parse(MASTER).getroot()
    body = root.find(f"{TEI}text/{TEI}body")
    if body is None:
        raise ValueError("Easton native body missing")
    entries = list(body)
    census: list[dict] = []
    definition_count = 0
    with SOURCE.open("rb") as stream:
        for order, line in enumerate(stream, 1):
            if not line.strip() or order > len(entries):
                raise ValueError(f"Easton source line/entry mismatch: {order}")
            record = json.loads(line.decode("utf-8"), object_pairs_hook=unique_object)
            if set(record) != {"term", "definitions"} or not isinstance(record["term"], str):
                raise ValueError(f"Easton source fields/term mismatch: {order}")
            definitions = record["definitions"]
            if not isinstance(definitions, list) or not definitions or any(not isinstance(value, str) for value in definitions):
                raise ValueError(f"Easton source definitions mismatch: {order}")
            entry = entries[order - 1]
            prefix = f"eastons-bible-dictionary-entry-{order:05d}"
            if entry.tag != f"{TEI}entry" or entry.get("n") != str(order) or entry.get(XML_ID) != prefix:
                raise ValueError(f"Easton entry identity/order mismatch: {order}")
            if [child.tag for child in entry] != [f"{TEI}form", f"{TEI}sense"]:
                raise ValueError(f"Easton entry structure mismatch: {order}")
            form, sense = entry
            if len(form) != 1 or form[0].tag != f"{TEI}orth" or form[0].get("type") != "headword" or form[0].text != record["term"]:
                raise ValueError(f"Easton source headword mismatch: {order}")
            if sense.get(XML_ID) != prefix + "-sense" or len(sense) != len(definitions):
                raise ValueError(f"Easton sense/definition count mismatch: {order}")
            for number, (node, value) in enumerate(zip(sense, definitions), 1):
                if node.tag != f"{TEI}def" or node.get("n") != str(number) or node.get(XML_ID) != f"{prefix}-definition-{number:03d}" or node.text != value or len(node):
                    raise ValueError(f"Easton definition order/content mismatch: {order}/{number}")
            census.append({"id": prefix, "source_order": order, "source_record_sha256": hashlib.sha256(line).hexdigest(), "definition_count": len(definitions)})
            definition_count += len(definitions)
    if len(census) != len(entries) or len(census) != 3963 or definition_count != 7464:
        raise ValueError("Easton whole-member entry/definition count mismatch")
    accounting = {
        "contract": "ocd-easton-current-source-accounting-v1",
        "entry_kind": "dictionary-entry",
        "projection_context": {
            "entry_kind": "dictionary-entry",
            "source_selector": {"tei_entry_profile": "easton-native-lexical-v1"},
            "source_scope": scope,
            "source_unit_count": len(census),
            "source_selected_units": [item["id"] for item in census],
            "source_census": census,
            "source_excerpt_sha256": SOURCE_SHA,
        },
        "source_path": "raw/bible_dictionaries/eastons.jsonl",
        "source_sha256": SOURCE_SHA,
        "candidate_master_sha256": MASTER_SHA,
        "definition_count": definition_count,
        "historical_crosswalk": {"path": HISTORICAL.as_posix(), "sha256": digest(HISTORICAL)},
        "technical_scope": "Exact retained electronic JSONL line order, term, and ordered definitions; no print-edition or rights claim.",
    }
    proof = {
        "contract": "ocd-easton-current-source-proof-v1",
        "status": "pass",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "source_path": accounting["source_path"],
        "source_sha256": SOURCE_SHA,
        "candidate_master_path": MASTER.relative_to(ROOT).as_posix(),
        "candidate_master_sha256": MASTER_SHA,
        "entry_count": len(census),
        "definition_count": definition_count,
        "first_entry": census[0]["id"],
        "last_entry": census[-1]["id"],
        "comparison": "Every JSONL term and ordered definition equals its native orth/def text; entry, sense and definition identifiers and n attributes are exact.",
        "rights_clearance": "unresolved",
        "publication_authorized": False,
    }
    save(OUT / "source-accounting.json", accounting)
    save(OUT / "source-proof.json", proof)
    print(json.dumps({"source_accounting_sha256": digest(OUT / "source-accounting.json"), "source_proof_sha256": digest(OUT / "source-proof.json"), "entries": len(census), "definitions": definition_count}, sort_keys=True))


if __name__ == "__main__":
    main()
