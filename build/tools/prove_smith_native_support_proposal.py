"""Focused in-memory proof of the unapplied Smith native lexical profile."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from lxml import etree


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports/_logs/smiths-bible-dictionary-current-reconciliation-20261002-v1/native-support-proposal"
MODULE = OUT / "reference_entries.after.py"
CANDIDATE = ROOT / "library/works/smiths-bible-dictionary/integration/smith-current-v1/candidate.tei.xml"
EXPECTED_MODULE = "37addf99c4327533995f185d15b3a0b56ce63fb4ea6e2f7a4584e94995e25e08"
EXPECTED_CANDIDATE = "c4f3ff3a981f30dd816e6904af014e7eceb619d419f0f4f478fb1dcb34d43d8e"
IDENTITY = {
    "work_id": "smiths-bible-dictionary",
    "textual_form_id": "smiths-bible-dictionary-retained-electronic",
    "edition_id": "smiths-bible-dictionary-retained-electronic-witness",
}
SELECTOR = {"tei_entry_profile": "smith-native-lexical-v1"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rejected(action: object, error_type: type[Exception]) -> bool:
    try:
        action()
    except error_type:
        return True
    return False


def main() -> None:
    if sha(MODULE) != EXPECTED_MODULE or sha(CANDIDATE) != EXPECTED_CANDIDATE:
        raise ValueError("Smith candidate or proposed adapter drifted")
    spec = importlib.util.spec_from_file_location("smith_reference_proposal", MODULE)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load Smith proposed adapter")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = ET.parse(CANDIDATE).getroot()
    if module._easton_profile(root, IDENTITY, SELECTOR) is not True:
        raise ValueError("Smith exact profile was not admitted")
    if not rejected(lambda: module._easton_profile(root, IDENTITY, {"tei_entry_profile": "hitchcock-native-lexical-v1"}), module.UnsupportedStructure):
        raise ValueError("Cross-work profile was admitted")
    wrong = dict(IDENTITY, edition_id="unverified-edition")
    if not rejected(lambda: module._easton_profile(root, wrong, SELECTOR), module.UnsupportedStructure):
        raise ValueError("Wrong Smith edition was admitted")
    wrong_root = copy.deepcopy(root)
    wrong_root.set(module.XML_ID, "unverified-root")
    if not rejected(lambda: module._easton_profile(wrong_root, IDENTITY, SELECTOR), module.UnsupportedStructure):
        raise ValueError("Wrong Smith root was admitted")
    if not rejected(lambda: module._easton_profile(root, IDENTITY, {"tei_entry_profile": ["smith-native-lexical-v1"]}), module.UnsupportedStructure):
        raise ValueError("Non-string profile was admitted")
    body = root.find(f".//{{{module.TEI_NS}}}body")
    if body is None or len(body) != 4560:
        raise ValueError("Expected Smith native entry count differs")
    paths = module._paths(root)
    first = body[0]
    second = body[1]
    headword, definitions = module._easton_lexical(first, 1, paths, work_id=IDENTITY["work_id"])
    if headword != first[0][0].text or definitions != [node.text for node in first[1]]:
        raise ValueError("Producer altered literal Smith lexical content")
    if len(second[1]) < 2:
        raise ValueError("Smith second entry has no multi-definition proof surface")
    missing = copy.deepcopy(second)
    missing[1].remove(missing[1][0])
    if not rejected(lambda: module._easton_lexical(missing, 2, {missing: "/entry[2]", **{node: "/node" for node in missing.iter() if node is not missing}}, work_id=IDENTITY["work_id"]), module.UnsupportedStructure):
        raise ValueError("Missing Smith definition was admitted")
    reordered = copy.deepcopy(second)
    reordered[1][0].set("n", "2")
    if not rejected(lambda: module._easton_lexical(reordered, 2, {node: "/node" for node in reordered.iter()}, work_id=IDENTITY["work_id"]), module.UnsupportedStructure):
        raise ValueError("Reordered Smith definition was admitted")
    unknown = copy.deepcopy(root)
    unknown_body = unknown.find(f".//{{{module.TEI_NS}}}body")
    if unknown_body is None:
        raise ValueError("Smith body absent")
    unknown_body[0].set("ana", "invented")
    if not rejected(lambda: module._validate_attributes(unknown, module._paths(unknown), easton=True), module.UnsupportedStructure):
        raise ValueError("Unknown Smith native attribute was admitted")
    literal = copy.deepcopy(first)
    literal[0][0].text = "\t" + literal[0][0].text + "\n"
    literal[1][0].text += " \n"
    literal_head, literal_blocks = module._easton_lexical(literal, 1, {node: "/node" for node in literal.iter()}, work_id=IDENTITY["work_id"])
    if not literal_head.startswith("\t") or not literal_head.endswith("\n") or not literal_blocks[0].endswith(" \n"):
        raise ValueError("Literal Smith lexical whitespace was normalized")
    lxml_root = etree.fromstring(ET.tostring(root, encoding="utf-8"))
    lxml_body = lxml_root.find(f".//{{{module.TEI_NS}}}body")
    if lxml_body is None:
        raise ValueError("Smith checker body absent")
    for entry in list(lxml_body)[2:]:
        lxml_body.remove(entry)
    rows, anchors, inventory, exclusions, warnings, selection = module._checker_easton_entries(lxml_root, IDENTITY, "en", "tei-v2", "Retained electronic witness", "dictionary-entry", None)
    if len(rows) != 2 or rows[0]["headword"] != headword or rows[0]["definition_blocks"] != definitions or selection["selected_units"] != 2 or exclusions or warnings or len(anchors) != 2 or not inventory:
        raise ValueError("Independent checker altered Smith sample rows or inventory")
    result = {
        "contract": "ocd-smith-native-support-focused-proof-v1",
        "status": "pass",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "candidate_sha256": EXPECTED_CANDIDATE,
        "proposed_adapter_sha256": EXPECTED_MODULE,
        "sample_rows": 2,
        "source_entries": 4560,
        "checks": ["exact Smith identity/profile/root", "cross-work/wrong-edition/wrong-root/non-string rejection", "literal headword/definition conservation", "missing/reordered definition rejection", "unknown attribute rejection", "literal whitespace conservation", "independent lxml sample rows and inventory"],
        "source_body_comparison": "reports/_logs/smith-coordinator-source-review-20261002-v1/review.json",
    }
    path = OUT / "focused-proof.json"
    with path.open("xb") as stream:
        stream.write((json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode())
    print(json.dumps({"status": "pass", "proof_sha256": sha(path), "sample_rows": 2}))


if __name__ == "__main__":
    main()
